"""Internship scraping logic targeting companies with 50-500 employees."""

import re
import time
from typing import Optional

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

def find_internships(
    keywords: str = "software engineering",
    location: str = "",
    max_results: int = 20,
) -> str:
    """
    Search for internship listings at companies with 50-500 employees.

    Pulls from The Muse (company size known) and Indeed (size looked up
    via web search). Returns a formatted list of matching positions.

    Args:
        keywords:    Role or skill keywords, e.g. "software engineering", "data science".
        location:    City/region filter, e.g. "New York" or "Remote". Leave blank for all.
        max_results: Maximum number of results to return (default 20).

    Returns:
        A human-readable string with matching internship listings.
    """
    all_listings: list[dict] = []

    # --- Source 1: The Muse (size already known) ---
    muse = _scrape_muse(keywords=keywords, location=location)
    all_listings.extend(muse)

    # --- Source 2: Indeed (size unknown, will look up) ---
    indeed = _scrape_indeed(keywords=keywords, location=location, max_results=25)
    all_listings.extend(indeed)

    # --- Deduplicate by (company, title) ---
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for listing in all_listings:
        key = (listing["company"].lower().strip(), listing["title"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(listing)

    # --- Enrich Indeed listings with company size lookup, then filter ---
    filtered: list[dict] = []
    for listing in unique:
        size = listing.get("company_size")

        if size is None and listing["company"]:
            size = _lookup_company_size(listing["company"])
            listing["company_size"] = size
            time.sleep(0.3)  # be polite to the search API

        if size and _size_in_range(size):
            filtered.append(listing)
        elif not size:
            # Keep unknowns so the agent can investigate further
            listing["company_size"] = "Unknown"
            filtered.append(listing)

    if not filtered:
        return (
            "No internship listings found for companies with 50-500 employees. "
            "Try broader keywords or leave location blank."
        )

    capped = filtered[:max_results]
    lines = [
        f"Found {len(capped)} internship listing(s) "
        f"(companies targeting ~50-500 employees):\n"
    ]
    for i, job in enumerate(capped, 1):
        size_display = job.get("company_size") or "Unknown"
        lines.append(
            f"{i}. {job['title']}\n"
            f"   Company:  {job['company']} ({size_display} employees)\n"
            f"   Location: {job['location']}\n"
            f"   URL:      {job['url'] or 'N/A'}\n"
            f"   Source:   {job['source']}\n"
        )

    return "\n".join(lines)
