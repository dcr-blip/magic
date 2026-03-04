#!/usr/bin/env python3
"""
Discord Job Scraper Bot — $0 cost, no AI API keys needed.

Scrapes 6 public job boards and posts results to Discord with rich embeds,
pagination buttons, CSV export, saved searches, and scheduled auto-posting.

Sources (all free):
  The Muse (API) · Indeed · LinkedIn · Glassdoor · SimplyHired · ZipRecruiter

Usage:
  1. Add DISCORD_TOKEN to your .env file
  2. python scraper_bot.py

Discord commands:
  !jobs <keywords>                Search all boards
  !jobs <keywords> in <location>  Filter by location
  !companies <list>               Target specific companies
  !export                         Export last results as CSV
  !save <name> <keywords>         Save a search preset
  !saved                          List saved presets
  !run <name>                     Run a saved preset
  !sources                        Show source status
  !help                           Show help
"""

import asyncio
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

from internship_scraper import (
    find_internships,
    scrape_company_internships,
    _scrape_muse,
    _scrape_indeed,
    _scrape_linkedin_via_search,
    _scrape_glassdoor_via_search,
    _scrape_simplyhired,
    _scrape_ziprecruiter_via_search,
    _deduplicate,
    _enrich_and_filter,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scraper_bot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SCRAPE_CHANNEL_ID = os.getenv("SCRAPE_CHANNEL_ID", "")
SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "12"))
AUTO_SCRAPE_KEYWORDS = os.getenv("AUTO_SCRAPE_KEYWORDS", "software engineering")
AUTO_SCRAPE_LOCATION = os.getenv("AUTO_SCRAPE_LOCATION", "")
RESULTS_PER_PAGE = 5
MAX_DISCORD_LEN = 2000
DATA_DIR = Path(__file__).parent / ".scraper_data"
SAVED_SEARCHES_FILE = DATA_DIR / "saved_searches.json"

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Per-channel state: stores last scrape results for pagination/export
_channel_results: dict[int, list[dict]] = {}
_channel_pages: dict[int, int] = {}

# Embed color
EMBED_COLOR = 0x5865F2  # Discord blurple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)


def _load_saved_searches() -> dict:
    _ensure_data_dir()
    if SAVED_SEARCHES_FILE.exists():
        return json.loads(SAVED_SEARCHES_FILE.read_text())
    return {}


def _save_searches(data: dict):
    _ensure_data_dir()
    SAVED_SEARCHES_FILE.write_text(json.dumps(data, indent=2))


def _parse_jobs_command(text: str) -> tuple[str, str]:
    """Parse '!jobs <keywords> in <location>' into (keywords, location)."""
    text = text.strip()
    if not text:
        return ("software engineering", "")
    lower = text.lower()
    idx = lower.rfind(" in ")
    if idx > 0:
        return (text[:idx].strip(), text[idx + 4:].strip())
    return (text, "")


def _build_job_embed(job: dict, index: int) -> discord.Embed:
    """Build a Discord embed for a single job listing."""
    title = job.get("title", "Untitled")
    if len(title) > 256:
        title = title[:253] + "..."

    embed = discord.Embed(
        title=f"{index}. {title}",
        url=job.get("url") or None,
        color=EMBED_COLOR,
    )
    embed.add_field(name="Company", value=job.get("company", "Unknown"), inline=True)
    size = job.get("company_size") or "Unknown"
    embed.add_field(name="Size", value=f"{size} employees" if size != "Unknown" else size, inline=True)
    embed.add_field(name="Location", value=job.get("location", "Not specified"), inline=True)
    embed.set_footer(text=f"Source: {job.get('source', 'Unknown')}")
    return embed


def _build_page_embeds(jobs: list[dict], page: int) -> tuple[list[discord.Embed], int]:
    """Build embeds for one page of results. Returns (embeds, total_pages)."""
    total_pages = max(1, (len(jobs) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * RESULTS_PER_PAGE
    end = start + RESULTS_PER_PAGE
    page_jobs = jobs[start:end]

    embeds = []

    # Header embed
    header = discord.Embed(
        title=f"Job Results — Page {page + 1}/{total_pages}",
        description=f"Found **{len(jobs)}** listings total. Showing {start + 1}-{min(end, len(jobs))}.",
        color=EMBED_COLOR,
    )
    header.timestamp = datetime.now(timezone.utc)
    embeds.append(header)

    # One embed per job
    for i, job in enumerate(page_jobs, start=start + 1):
        embeds.append(_build_job_embed(job, i))

    return embeds, total_pages


def _build_nav_view(page: int, total_pages: int) -> discord.ui.View:
    """Build prev/next/export navigation buttons."""
    view = discord.ui.View(timeout=300)

    prev_btn = discord.ui.Button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="page_prev",
        disabled=(page <= 0),
    )
    next_btn = discord.ui.Button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        custom_id="page_next",
        disabled=(page >= total_pages - 1),
    )
    export_btn = discord.ui.Button(
        label="Export CSV",
        style=discord.ButtonStyle.success,
        custom_id="export_csv",
        emoji="\U0001F4BE",
    )

    view.add_item(prev_btn)
    view.add_item(next_btn)
    view.add_item(export_btn)
    return view


def _jobs_to_csv(jobs: list[dict]) -> str:
    """Convert job listings to a CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["title", "company", "company_size", "location", "url", "source"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(jobs)
    return output.getvalue()


async def _run_scrape(keywords: str, location: str, max_results: int = 20) -> list[dict]:
    """Run the scraper in a thread and return raw job dicts."""
    def _do_scrape():
        all_listings: list[dict] = []
        all_listings.extend(_scrape_muse(keywords=keywords, location=location))
        all_listings.extend(_scrape_indeed(keywords=keywords, location=location, max_results=20))
        all_listings.extend(_scrape_linkedin_via_search(keywords=keywords, location=location))
        all_listings.extend(_scrape_glassdoor_via_search(keywords=keywords, location=location))
        all_listings.extend(_scrape_simplyhired(keywords=keywords, location=location))
        all_listings.extend(_scrape_ziprecruiter_via_search(keywords=keywords, location=location))
        unique = _deduplicate(all_listings)
        filtered = _enrich_and_filter(unique)
        return filtered[:max_results]

    return await asyncio.to_thread(_do_scrape)


async def _run_company_scrape(companies: str) -> list[dict]:
    """Run company-targeted scrape and return raw job dicts."""
    def _do_scrape():
        # Re-use the text output, but we need raw dicts too.
        # Call the internal functions directly for raw data.
        from internship_scraper import _lookup_company_size
        from duckduckgo_search import DDGS

        company_list = [c.strip() for c in companies.split(",") if c.strip()]
        all_results: list[dict] = []

        for company_name in company_list:
            company_listings: list[dict] = []
            for site, source_label in [
                ("linkedin.com/jobs", "LinkedIn"),
                ("glassdoor.com", "Glassdoor"),
                ("indeed.com", "Indeed"),
                ("ziprecruiter.com/jobs", "ZipRecruiter"),
            ]:
                query = f'site:{site} "{company_name}" internship'
                try:
                    with DDGS() as ddgs:
                        results = list(ddgs.text(query, max_results=5))
                    for r in results:
                        clean_title = r.get("title", "")
                        for suffix in [" | LinkedIn", " | Glassdoor", " | Indeed",
                                       " | ZipRecruiter", " | SimplyHired"]:
                            clean_title = clean_title.replace(suffix, "")
                        company_listings.append({
                            "title": clean_title.strip(),
                            "company": company_name,
                            "company_size": None,
                            "location": "Not specified",
                            "url": r.get("href", ""),
                            "source": source_label,
                        })
                    time.sleep(0.3)
                except Exception:
                    continue

            size = _lookup_company_size(company_name)
            for listing in company_listings:
                listing["company_size"] = size or "Unknown"
            all_results.extend(company_listings)

        return _deduplicate(all_results)

    return await asyncio.to_thread(_do_scrape)


async def _send_results(channel, jobs: list[dict], page: int = 0):
    """Send paginated embed results to a channel."""
    _channel_results[channel.id] = jobs
    _channel_pages[channel.id] = page

    if not jobs:
        embed = discord.Embed(
            title="No Results Found",
            description="No internship listings matched your criteria. Try broader keywords.",
            color=0xFF0000,
        )
        await channel.send(embed=embed)
        return

    embeds, total_pages = _build_page_embeds(jobs, page)
    view = _build_nav_view(page, total_pages)
    await channel.send(embeds=embeds, view=view)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (id={bot.user.id})")
    log.info(f"Serving {len(bot.guilds)} guild(s) | $0 cost — no AI API key needed")

    if SCRAPE_CHANNEL_ID:
        bot.loop.create_task(_auto_scrape_loop())


async def _auto_scrape_loop():
    """Periodically scrape and post to a designated channel."""
    await bot.wait_until_ready()
    channel = bot.get_channel(int(SCRAPE_CHANNEL_ID))
    if not channel:
        log.warning(f"SCRAPE_CHANNEL_ID={SCRAPE_CHANNEL_ID} not found, auto-posting disabled.")
        return

    log.info(f"Auto-posting to #{channel.name} every {SCRAPE_INTERVAL_HOURS}h")
    while not bot.is_closed():
        try:
            log.info("Running scheduled scrape...")
            jobs = await _run_scrape(AUTO_SCRAPE_KEYWORDS, AUTO_SCRAPE_LOCATION, 15)

            header = discord.Embed(
                title="Scheduled Job Scrape",
                description=(
                    f"Keywords: **{AUTO_SCRAPE_KEYWORDS}**"
                    + (f" | Location: **{AUTO_SCRAPE_LOCATION}**" if AUTO_SCRAPE_LOCATION else "")
                    + f"\nFound **{len(jobs)}** listings from 6 sources."
                ),
                color=EMBED_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            await channel.send(embed=header)
            await _send_results(channel, jobs)
            log.info("Scheduled scrape posted.")
        except Exception:
            log.exception("Auto-scrape error")

        await asyncio.sleep(SCRAPE_INTERVAL_HOURS * 3600)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Handle button clicks for pagination and export."""
    if not interaction.data:
        return

    custom_id = interaction.data.get("custom_id", "")
    channel_id = interaction.channel_id

    if custom_id == "export_csv":
        jobs = _channel_results.get(channel_id, [])
        if not jobs:
            await interaction.response.send_message("No results to export.", ephemeral=True)
            return

        csv_text = _jobs_to_csv(jobs)
        file = discord.File(
            io.BytesIO(csv_text.encode("utf-8")),
            filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        await interaction.response.send_message("Here's your CSV export:", file=file, ephemeral=True)
        return

    if custom_id in ("page_prev", "page_next"):
        jobs = _channel_results.get(channel_id, [])
        if not jobs:
            await interaction.response.send_message("No results loaded.", ephemeral=True)
            return

        page = _channel_pages.get(channel_id, 0)
        if custom_id == "page_prev":
            page = max(0, page - 1)
        else:
            total_pages = max(1, (len(jobs) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
            page = min(total_pages - 1, page + 1)

        _channel_pages[channel_id] = page
        embeds, total_pages = _build_page_embeds(jobs, page)
        view = _build_nav_view(page, total_pages)
        await interaction.response.edit_message(embeds=embeds, view=view)
        return


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    content = message.content.strip()
    lower = content.lower()

    # --- !help ---
    if lower == "!help":
        embed = discord.Embed(title="Job Scraper Bot", color=EMBED_COLOR)
        embed.description = "Scrapes 6 job boards for free — no AI API keys needed."
        embed.add_field(
            name="Search Commands",
            value=(
                "`!jobs <keywords>` — Search all boards\n"
                "`!jobs <keywords> in <location>` — Filter by location\n"
                "`!companies <list>` — Target specific companies"
            ),
            inline=False,
        )
        embed.add_field(
            name="Results",
            value=(
                "`!export` — Export last results as CSV\n"
                "Use **Previous**/**Next** buttons to paginate"
            ),
            inline=False,
        )
        embed.add_field(
            name="Saved Searches",
            value=(
                "`!save <name> <keywords>` — Save a search preset\n"
                "`!save <name> <keywords> in <location>` — Save with location\n"
                "`!saved` — List all saved presets\n"
                "`!run <name>` — Run a saved preset"
            ),
            inline=False,
        )
        embed.add_field(
            name="Info",
            value="`!sources` — Show scraping sources and status",
            inline=False,
        )
        embed.set_footer(text="Sources: The Muse · Indeed · LinkedIn · Glassdoor · SimplyHired · ZipRecruiter")
        await message.reply(embed=embed)
        return

    # --- !jobs ---
    if lower.startswith("!jobs"):
        args = content[5:].strip()
        if args.lower() == "help":
            # redirect to !help
            content = "!help"
            # fall through handled above, just send help embed
            await message.channel.send("Use `!help` to see all commands.")
            return

        keywords, location = _parse_jobs_command(args)

        status = discord.Embed(
            title="Scraping...",
            description=(
                f"Searching 6 job boards for **{keywords}**"
                + (f" in **{location}**" if location else "")
                + "\n\nThis takes ~30-60 seconds."
            ),
            color=0xFFA500,
        )
        status_msg = await message.reply(embed=status)

        async with message.channel.typing():
            try:
                jobs = await _run_scrape(keywords, location, 30)
            except Exception as e:
                log.exception("Scrape error")
                err = discord.Embed(title="Scrape Failed", description=str(e), color=0xFF0000)
                await status_msg.edit(embed=err)
                return

        # Delete the "scraping..." message
        try:
            await status_msg.delete()
        except Exception:
            pass

        await _send_results(message.channel, jobs)
        return

    # --- !companies ---
    if lower.startswith("!companies"):
        companies = content[10:].strip()
        if not companies:
            await message.reply("Usage: `!companies Stripe, Notion, Figma`")
            return

        status = discord.Embed(
            title="Scraping...",
            description=f"Searching for internships at **{companies}**\n\nThis takes ~30-60 seconds.",
            color=0xFFA500,
        )
        status_msg = await message.reply(embed=status)

        async with message.channel.typing():
            try:
                jobs = await _run_company_scrape(companies)
            except Exception as e:
                log.exception("Company scrape error")
                err = discord.Embed(title="Scrape Failed", description=str(e), color=0xFF0000)
                await status_msg.edit(embed=err)
                return

        try:
            await status_msg.delete()
        except Exception:
            pass

        await _send_results(message.channel, jobs)
        return

    # --- !export ---
    if lower == "!export":
        jobs = _channel_results.get(message.channel.id, [])
        if not jobs:
            await message.reply("No results to export. Run `!jobs` first.")
            return

        csv_text = _jobs_to_csv(jobs)
        file = discord.File(
            io.BytesIO(csv_text.encode("utf-8")),
            filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        await message.reply("Here's your CSV export:", file=file)
        return

    # --- !save <name> <keywords [in location]> ---
    if lower.startswith("!save "):
        parts = content[6:].strip().split(None, 1)
        if len(parts) < 2:
            await message.reply("Usage: `!save my-search software engineering in NYC`")
            return

        name = parts[0].lower()
        keywords, location = _parse_jobs_command(parts[1])
        searches = _load_saved_searches()
        searches[name] = {"keywords": keywords, "location": location}
        _save_searches(searches)

        embed = discord.Embed(
            title=f"Search saved: `{name}`",
            description=f"Keywords: **{keywords}**" + (f"\nLocation: **{location}**" if location else ""),
            color=0x00FF00,
        )
        embed.set_footer(text=f"Run anytime with: !run {name}")
        await message.reply(embed=embed)
        return

    # --- !saved ---
    if lower == "!saved":
        searches = _load_saved_searches()
        if not searches:
            await message.reply("No saved searches yet. Use `!save <name> <keywords>` to create one.")
            return

        embed = discord.Embed(title="Saved Searches", color=EMBED_COLOR)
        for name, data in searches.items():
            loc = data.get("location", "")
            val = f"**{data['keywords']}**" + (f" in **{loc}**" if loc else "")
            embed.add_field(name=f"`!run {name}`", value=val, inline=False)
        await message.reply(embed=embed)
        return

    # --- !run <name> ---
    if lower.startswith("!run "):
        name = content[5:].strip().lower()
        searches = _load_saved_searches()
        if name not in searches:
            await message.reply(f"No saved search called `{name}`. Use `!saved` to list them.")
            return

        data = searches[name]
        keywords = data["keywords"]
        location = data.get("location", "")

        status = discord.Embed(
            title=f"Running saved search: `{name}`",
            description=(
                f"Keywords: **{keywords}**"
                + (f" in **{location}**" if location else "")
                + "\n\nThis takes ~30-60 seconds."
            ),
            color=0xFFA500,
        )
        status_msg = await message.reply(embed=status)

        async with message.channel.typing():
            try:
                jobs = await _run_scrape(keywords, location, 30)
            except Exception as e:
                log.exception("Scrape error")
                err = discord.Embed(title="Scrape Failed", description=str(e), color=0xFF0000)
                await status_msg.edit(embed=err)
                return

        try:
            await status_msg.delete()
        except Exception:
            pass

        await _send_results(message.channel, jobs)
        return

    # --- !sources ---
    if lower == "!sources":
        embed = discord.Embed(title="Scraping Sources", color=EMBED_COLOR)
        sources = [
            ("The Muse", "Free public API", "themuse.com"),
            ("Indeed", "HTML scraping", "indeed.com"),
            ("LinkedIn", "DuckDuckGo site-search", "linkedin.com"),
            ("Glassdoor", "DuckDuckGo site-search", "glassdoor.com"),
            ("SimplyHired", "HTML scraping", "simplyhired.com"),
            ("ZipRecruiter", "DuckDuckGo site-search", "ziprecruiter.com"),
        ]
        for name, method, site in sources:
            embed.add_field(name=name, value=f"{method}\n`{site}`", inline=True)
        embed.set_footer(text="All sources are free and public. No API keys needed.")
        await message.reply(embed=embed)
        return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if not DISCORD_TOKEN:
        print(
            "Error: DISCORD_TOKEN not set.\n\n"
            "Setup:\n"
            "  1. Go to https://discord.com/developers/applications\n"
            "  2. New Application → Bot tab → Reset Token → copy it\n"
            "  3. Enable 'Message Content Intent' under Privileged Gateway Intents\n"
            "  4. OAuth2 → URL Generator → scope: bot → permissions: Send Messages,\n"
            "     Read Message History, Attach Files, Embed Links\n"
            "  5. Add DISCORD_TOKEN=your_token to your .env file\n\n"
            "No ANTHROPIC_API_KEY needed — this bot scrapes directly for $0."
        )
        sys.exit(1)

    log.info("Starting job scraper bot ($0 cost — no AI API key needed)...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
