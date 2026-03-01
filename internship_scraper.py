"""Internship scraping logic targeting companies with 50-500 employees."""

import json
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# ---------------------------------------------------------------------------
# Company-size helpers
# ---------------------------------------------------------------------------

# The Muse API returns one of these fixed strings for company size.
_MUSE_SIZE_RANGES: dict[str, tuple[int, int]] = {
    "1-200 Employees": (1, 200),
    "201-500 Employees": (201, 500),
    "501-1,000 Employees": (501, 1000),
    "1,001-5,000 Employees": (1001, 5000),
    "5,001-10,000 Employees": (5001, 10000),
    "10,001+ Employees": (10001, 10**9),
}

# Muse size labels that overlap with the 50-500 range we care about.
_MUSE_TARGET_SIZES = {"1-200 Employees", "201-500 Employees"}


def _size_in_range(size_str: str, lo: int = 50, hi: int = 500) -> bool:
    """Return True if *size_str* plausibly represents a company in [lo, hi]."""
    if not size_str or size_str.lower() == "unknown":
        return False

    # Known Muse labels
    if size_str in _MUSE_SIZE_RANGES:
        bucket_lo, bucket_hi = _MUSE_SIZE_RANGES[size_str]
        return bucket_lo <= hi and bucket_hi >= lo

    # Numeric range like "51-200" or "201–500"
    m = re.search(r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)", size_str)
    if m:
        bucket_lo = int(m.group(1).replace(",", ""))
        bucket_hi = int(m.group(2).replace(",", ""))
        return bucket_lo <= hi and bucket_hi >= lo

    # Single number like "300 employees" or "~150"
    m = re.search(r"(\d[\d,]+)", size_str)
    if m:
        count = int(m.group(1).replace(",", ""))
        return lo <= count <= hi

    return False


# ---------------------------------------------------------------------------
# Source 1: The Muse public API (free, no key required)
# ---------------------------------------------------------------------------

def _scrape_muse(keywords: str = "", location: str = "", max_pages: int = 3) -> list[dict]:
    """
    Query The Muse public jobs API for internships.
    Only returns listings whose company size falls in the 1-500 range.
    """
    results: list[dict] = []
    base_url = "https://www.themuse.com/api/public/jobs"

    for page in range(1, max_pages + 1):
        params: dict = {"level": "Internship", "page": page, "descending": "true"}
        if keywords:
            params["category"] = keywords
        if location:
            params["location"] = location

        try:
            resp = requests.get(base_url, params=params, timeout=12)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        jobs = data.get("results", [])
        if not jobs:
            break

        for job in jobs:
            company = job.get("company", {})
            size_label = company.get("size", "")

            if size_label not in _MUSE_TARGET_SIZES:
                continue

            locations = [loc.get("name", "") for loc in job.get("locations", [])]
            results.append(
                {
                    "title": job.get("name", ""),
                    "company": company.get("name", ""),
                    "company_size": size_label,
                    "location": ", ".join(filter(None, locations)) or "Not specified",
                    "url": job.get("refs", {}).get("landing_page", ""),
                    "source": "The Muse",
                }
            )

        time.sleep(0.4)

    return results


# ---------------------------------------------------------------------------
# Source 2: Indeed HTML scraping (best-effort; site structure may change)
# ---------------------------------------------------------------------------

_INDEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _scrape_indeed(keywords: str = "", location: str = "", max_results: int = 20) -> list[dict]:
    """
    Scrape Indeed job search for internship listings.
    Company size is not available directly; callers should enrich via lookup.
    """
    query = f"{keywords} internship" if keywords else "internship"
    params = {"q": query, "l": location, "sort": "date", "limit": 25}

    try:
        resp = requests.get(
            "https://www.indeed.com/jobs",
            params=params,
            headers=_INDEED_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Indeed has changed its HTML structure several times; try multiple selectors.
    cards = (
        soup.select("div.job_seen_beacon")
        or soup.select("div[class*='jobCard']")
        or soup.select("li[class*='css-']")
    )

    jobs: list[dict] = []
    for card in cards[:max_results]:
        title_el = card.select_one("h2.jobTitle span[title], h2[class*='jobTitle'] span")
        company_el = card.select_one(
            "[data-testid='company-name'], span.companyName, [class*='companyName']"
        )
        location_el = card.select_one(
            "[data-testid='text-location'], div.companyLocation, [class*='companyLocation']"
        )
        link_el = card.select_one("a[id^='job_'], a[data-jk], h2.jobTitle a")

        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        location_text = location_el.get_text(strip=True) if location_el else ""
        href = link_el.get("href", "") if link_el else ""
        if href and not href.startswith("http"):
            href = f"https://www.indeed.com{href}"

        if title and company:
            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "company_size": None,
                    "location": location_text or "Not specified",
                    "url": href,
                    "source": "Indeed",
                }
            )

    return jobs


# ---------------------------------------------------------------------------
# Source 3: LinkedIn via DuckDuckGo search (avoids login walls)
# ---------------------------------------------------------------------------

def _scrape_linkedin_via_search(
    keywords: str = "", location: str = "", max_results: int = 15,
) -> list[dict]:
    """Find LinkedIn internship postings using DuckDuckGo site-search."""
    query_parts = ["site:linkedin.com/jobs internship"]
    if keywords:
        query_parts.append(keywords)
    if location:
        query_parts.append(location)
    query = " ".join(query_parts)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    jobs: list[dict] = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")

        if "internship" not in title.lower() and "intern" not in title.lower():
            if "internship" not in body.lower() and "intern" not in body.lower():
                continue

        # Try to extract company from title (LinkedIn format: "Title at Company")
        company = ""
        for sep in [" at ", " - ", " | "]:
            if sep in title:
                company = title.split(sep, 1)[1].split(" | ")[0].split(" - ")[0].strip()
                title = title.split(sep, 1)[0].strip()
                break

        # Extract location from body if present
        loc = ""
        loc_match = re.search(r"(?:Location|location)[:\s]+([^·\n]+)", body)
        if loc_match:
            loc = loc_match.group(1).strip()

        if title:
            jobs.append({
                "title": title,
                "company": company or "Unknown",
                "company_size": None,
                "location": loc or location or "Not specified",
                "url": url,
                "source": "LinkedIn",
            })

    return jobs


# ---------------------------------------------------------------------------
# Source 4: Glassdoor via DuckDuckGo search
# ---------------------------------------------------------------------------

def _scrape_glassdoor_via_search(
    keywords: str = "", location: str = "", max_results: int = 15,
) -> list[dict]:
    """Find Glassdoor internship postings using DuckDuckGo site-search."""
    query_parts = ["site:glassdoor.com internship job"]
    if keywords:
        query_parts.append(keywords)
    if location:
        query_parts.append(location)
    query = " ".join(query_parts)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    jobs: list[dict] = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")

        if "internship" not in title.lower() and "intern" not in title.lower():
            if "internship" not in body.lower() and "intern" not in body.lower():
                continue

        company = ""
        # Glassdoor titles often: "Company Intern Title" or "Title - Company"
        for sep in [" - ", " | ", " at "]:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    company = parts[-1].strip().replace(" | Glassdoor", "").strip()
                    title = sep.join(parts[:-1]).strip()
                break

        if title:
            jobs.append({
                "title": title,
                "company": company or "Unknown",
                "company_size": None,
                "location": location or "Not specified",
                "url": url,
                "source": "Glassdoor",
            })

    return jobs


# ---------------------------------------------------------------------------
# Source 5: SimplyHired HTML scraping
# ---------------------------------------------------------------------------

_SIMPLYHIRED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _scrape_simplyhired(
    keywords: str = "", location: str = "", max_results: int = 20,
) -> list[dict]:
    """Scrape SimplyHired for internship listings."""
    query = f"{keywords} internship" if keywords else "internship"
    params = {"q": query, "pn": "1"}
    if location:
        params["l"] = location

    try:
        resp = requests.get(
            "https://www.simplyhired.com/search",
            params=params,
            headers=_SIMPLYHIRED_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    cards = (
        soup.select("article[data-testid='searchSerpJob']")
        or soup.select("div.SerpJob")
        or soup.select("li.SerpJob")
        or soup.select("article.SerpJob")
    )

    jobs: list[dict] = []
    for card in cards[:max_results]:
        title_el = card.select_one(
            "h2 a, h3 a, [data-testid='searchSerpJobTitle'] a, a.SerpJob-link"
        )
        company_el = card.select_one(
            "[data-testid='companyName'], span.JobPosting-labelWithIcon, "
            "span.jobposting-company, .SerpJob-metaInfo span"
        )
        location_el = card.select_one(
            "[data-testid='searchSerpJobLocation'], span.jobposting-location, "
            ".SerpJob-metaInfoLeft span:nth-of-type(2)"
        )

        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        loc_text = location_el.get_text(strip=True) if location_el else ""
        href = title_el.get("href", "") if title_el else ""
        if href and not href.startswith("http"):
            href = f"https://www.simplyhired.com{href}"

        if title and company:
            jobs.append({
                "title": title,
                "company": company,
                "company_size": None,
                "location": loc_text or "Not specified",
                "url": href,
                "source": "SimplyHired",
            })

    return jobs


# ---------------------------------------------------------------------------
# Source 6: ZipRecruiter via DuckDuckGo search
# ---------------------------------------------------------------------------

def _scrape_ziprecruiter_via_search(
    keywords: str = "", location: str = "", max_results: int = 15,
) -> list[dict]:
    """Find ZipRecruiter internship postings using DuckDuckGo site-search."""
    query_parts = ["site:ziprecruiter.com/jobs internship"]
    if keywords:
        query_parts.append(keywords)
    if location:
        query_parts.append(location)
    query = " ".join(query_parts)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    jobs: list[dict] = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")

        if "internship" not in title.lower() and "intern" not in title.lower():
            if "internship" not in body.lower() and "intern" not in body.lower():
                continue

        company = ""
        for sep in [" - ", " | ", " at "]:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    company = parts[-1].strip().replace(" | ZipRecruiter", "").strip()
                    title = sep.join(parts[:-1]).strip()
                break

        if title:
            jobs.append({
                "title": title,
                "company": company or "Unknown",
                "company_size": None,
                "location": location or "Not specified",
                "url": url,
                "source": "ZipRecruiter",
            })

    return jobs


# ---------------------------------------------------------------------------
# Company-size lookup via web search
# ---------------------------------------------------------------------------

def _lookup_company_size(company_name: str) -> Optional[str]:
    """
    Estimate employee count for *company_name* using a DuckDuckGo search.
    Returns a string like "51-200" or "350", or None if nothing found.
    """
    try:
        query = f"{company_name} number of employees company size"
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=4))

        combined = " ".join(
            r.get("body", "") + " " + r.get("title", "") for r in results
        )

        # Try "X-Y employees" first, then "X employees"
        for pattern in [
            r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s*employees",
            r"(\d[\d,]+)\+?\s*employees",
            r"employees[:\s]+(\d[\d,]+)",
        ]:
            m = re.search(pattern, combined, re.IGNORECASE)
            if m:
                groups = m.groups()
                if len(groups) == 2 and groups[1]:
                    lo = int(groups[0].replace(",", ""))
                    hi = int(groups[1].replace(",", ""))
                    return f"{lo}-{hi}"
                else:
                    return groups[0].replace(",", "")

        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _deduplicate(listings: list[dict]) -> list[dict]:
    """Remove duplicate listings by (company, title) key."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for listing in listings:
        key = (listing["company"].lower().strip(), listing["title"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(listing)
    return unique


def _enrich_and_filter(listings: list[dict]) -> list[dict]:
    """Look up company size for listings that don't have it, then filter to 50-500."""
    filtered: list[dict] = []
    for listing in listings:
        size = listing.get("company_size")

        if size is None and listing["company"] and listing["company"] != "Unknown":
            size = _lookup_company_size(listing["company"])
            listing["company_size"] = size
            time.sleep(0.3)  # be polite to the search API

        if size and _size_in_range(size):
            filtered.append(listing)
        elif not size:
            listing["company_size"] = "Unknown"
            filtered.append(listing)

    return filtered


def _format_listings(listings: list[dict], header: str = "") -> str:
    """Format a list of job dicts into a human-readable string."""
    if not listings:
        return "No internship listings found matching the criteria."

    lines = [header] if header else []
    for i, job in enumerate(listings, 1):
        size_display = job.get("company_size") or "Unknown"
        lines.append(
            f"{i}. {job['title']}\n"
            f"   Company:  {job['company']} ({size_display} employees)\n"
            f"   Location: {job['location']}\n"
            f"   URL:      {job['url'] or 'N/A'}\n"
            f"   Source:   {job['source']}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def find_internships(
    keywords: str = "software engineering",
    location: str = "",
    max_results: int = 20,
) -> str:
    """
    Search for internship listings at companies with 50-500 employees.

    Pulls from The Muse, Indeed, LinkedIn, Glassdoor, SimplyHired, and
    ZipRecruiter, enriching results with company size data.

    Args:
        keywords:    Role or skill keywords, e.g. "software engineering", "data science".
        location:    City/region filter, e.g. "New York" or "Remote". Leave blank for all.
        max_results: Maximum number of results to return (default 20).

    Returns:
        A human-readable string with matching internship listings.
    """
    all_listings: list[dict] = []

    # --- Source 1: The Muse (size already known) ---
    all_listings.extend(_scrape_muse(keywords=keywords, location=location))

    # --- Source 2: Indeed ---
    all_listings.extend(_scrape_indeed(keywords=keywords, location=location, max_results=20))

    # --- Source 3: LinkedIn via search ---
    all_listings.extend(_scrape_linkedin_via_search(keywords=keywords, location=location))

    # --- Source 4: Glassdoor via search ---
    all_listings.extend(_scrape_glassdoor_via_search(keywords=keywords, location=location))

    # --- Source 5: SimplyHired ---
    all_listings.extend(_scrape_simplyhired(keywords=keywords, location=location))

    # --- Source 6: ZipRecruiter via search ---
    all_listings.extend(_scrape_ziprecruiter_via_search(keywords=keywords, location=location))

    unique = _deduplicate(all_listings)
    filtered = _enrich_and_filter(unique)
    capped = filtered[:max_results]

    header = (
        f"Found {len(capped)} internship listing(s) from {_count_sources(capped)} source(s) "
        f"(companies targeting ~50-500 employees):\n"
    )
    return _format_listings(capped, header)


def scrape_company_internships(
    companies: str,
    keywords: str = "internship",
) -> str:
    """
    Search for internship postings at specific companies.

    Given a comma-separated list of company names, searches across multiple
    job boards and the web to find their internship openings.

    Args:
        companies: Comma-separated list of company names,
                   e.g. "Stripe, Notion, Figma, Datadog".
        keywords:  Additional keywords to narrow results (default: "internship").

    Returns:
        A human-readable string with internship listings grouped by company.
    """
    company_list = [c.strip() for c in companies.split(",") if c.strip()]
    if not company_list:
        return "No companies provided. Pass a comma-separated list of company names."

    all_results: list[dict] = []

    for company_name in company_list:
        company_listings: list[dict] = []
        search_kw = f"{company_name} {keywords}"

        # Search across multiple job boards via DuckDuckGo
        for site, source_label in [
            ("linkedin.com/jobs", "LinkedIn"),
            ("glassdoor.com", "Glassdoor"),
            ("indeed.com", "Indeed"),
            ("ziprecruiter.com/jobs", "ZipRecruiter"),
        ]:
            query = f"site:{site} \"{company_name}\" {keywords}"
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=5))
                for r in results:
                    title = r.get("title", "")
                    url = r.get("href", "")
                    body = r.get("body", "")

                    # Clean up the title
                    clean_title = title
                    for strip_suffix in [" | LinkedIn", " | Glassdoor", " | Indeed",
                                         " | ZipRecruiter", " | SimplyHired"]:
                        clean_title = clean_title.replace(strip_suffix, "")

                    company_listings.append({
                        "title": clean_title.strip(),
                        "company": company_name,
                        "company_size": None,
                        "location": "Not specified",
                        "url": url,
                        "source": source_label,
                    })
                time.sleep(0.3)
            except Exception:
                continue

        # Also try a general web search for the company's careers page
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(f"\"{company_name}\" internship careers apply", max_results=5))
            for r in results:
                url = r.get("href", "")
                title = r.get("title", "")
                # Skip if we already have this URL
                existing_urls = {j["url"] for j in company_listings}
                if url not in existing_urls and ("intern" in title.lower() or "intern" in r.get("body", "").lower()):
                    company_listings.append({
                        "title": title.strip(),
                        "company": company_name,
                        "company_size": None,
                        "location": "Not specified",
                        "url": url,
                        "source": "Web",
                    })
            time.sleep(0.3)
        except Exception:
            pass

        # Look up company size once per company
        size = _lookup_company_size(company_name)
        for listing in company_listings:
            listing["company_size"] = size or "Unknown"

        all_results.extend(company_listings)

    unique = _deduplicate(all_results)

    if not unique:
        return f"No internship postings found for: {', '.join(company_list)}"

    header = (
        f"Found {len(unique)} internship posting(s) across {len(company_list)} "
        f"targeted company/companies:\n"
    )
    return _format_listings(unique, header)


def _count_sources(listings: list[dict]) -> int:
    """Count the number of distinct sources in a list of listings."""
    return len({j["source"] for j in listings})
