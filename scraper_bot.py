#!/usr/bin/env python3
"""
Standalone Discord bot that scrapes job boards and posts results.

NO Claude API key required — this bot runs entirely on free, public sources:
  - The Muse (free API)
  - Indeed, SimplyHired (HTML scraping)
  - LinkedIn, Glassdoor, ZipRecruiter (DuckDuckGo site-search)

Usage:
  1. Set DISCORD_TOKEN in your .env file
  2. python scraper_bot.py

Discord commands:
  !jobs <keywords>                     — Search all boards (e.g. "!jobs software engineering")
  !jobs <keywords> in <location>       — Filter by location (e.g. "!jobs data science in NYC")
  !companies <list>                    — Target specific companies (e.g. "!companies Stripe, Notion")
  !jobs help                           — Show help

Optional: set SCRAPE_CHANNEL_ID in .env to auto-post on a schedule.
"""

import asyncio
import logging
import os
import sys

import discord
from dotenv import load_dotenv

from internship_scraper import find_internships, scrape_company_internships

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scraper_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SCRAPE_CHANNEL_ID = os.getenv("SCRAPE_CHANNEL_ID", "")  # Optional: auto-post channel
SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "12"))  # Auto-post interval
MAX_DISCORD_LEN = 2000

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def _split_message(text: str) -> list[str]:
    """Split text into chunks that fit within Discord's 2000-char limit."""
    if len(text) <= MAX_DISCORD_LEN:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= MAX_DISCORD_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, MAX_DISCORD_LEN)
        if split_at == -1 or split_at < MAX_DISCORD_LEN // 2:
            split_at = MAX_DISCORD_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _parse_jobs_command(text: str) -> tuple[str, str]:
    """Parse '!jobs <keywords> in <location>' into (keywords, location)."""
    text = text.strip()
    if not text:
        return ("software engineering", "")
    # Check for "in <location>" suffix
    lower = text.lower()
    idx = lower.rfind(" in ")
    if idx > 0:
        keywords = text[:idx].strip()
        location = text[idx + 4:].strip()
        return (keywords, location)
    return (text, "")


HELP_TEXT = """**Job Scraper Bot — Commands**

`!jobs <keywords>` — Search 6 job boards for internships
  Example: `!jobs software engineering`
  Example: `!jobs data science in New York`

`!companies <list>` — Search for internships at specific companies
  Example: `!companies Stripe, Notion, Figma`

`!jobs help` — Show this message

**Sources** (all free, no API keys needed):
The Muse · Indeed · LinkedIn · Glassdoor · SimplyHired · ZipRecruiter"""


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (id={bot.user.id})")
    log.info(f"Serving {len(bot.guilds)} guild(s) | No Claude API key needed!")

    # Start auto-posting loop if channel ID is set
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
            result = await asyncio.to_thread(
                find_internships, "software engineering", "", 15
            )
            for chunk in _split_message(result):
                await channel.send(chunk)
            log.info("Scheduled scrape posted.")
        except Exception:
            log.exception("Auto-scrape error")

        await asyncio.sleep(SCRAPE_INTERVAL_HOURS * 3600)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    content = message.content.strip()

    # --- !jobs command ---
    if content.lower().startswith("!jobs"):
        args = content[5:].strip()

        if args.lower() == "help":
            await message.reply(HELP_TEXT)
            return

        keywords, location = _parse_jobs_command(args)

        await message.reply(
            f"Scraping 6 job boards for **{keywords}**"
            + (f" in **{location}**" if location else "")
            + "... (this takes ~30-60 seconds)"
        )

        async with message.channel.typing():
            try:
                result = await asyncio.to_thread(
                    find_internships, keywords, location, 20
                )
            except Exception as e:
                log.exception("Scrape error")
                result = f"Error during scraping: {e}"

        for i, chunk in enumerate(_split_message(result)):
            if i == 0:
                await message.channel.send(chunk)
            else:
                await message.channel.send(chunk)
        return

    # --- !companies command ---
    if content.lower().startswith("!companies"):
        companies = content[10:].strip()
        if not companies:
            await message.reply("Usage: `!companies Stripe, Notion, Figma`")
            return

        await message.reply(f"Searching for internships at **{companies}**... (this takes ~30-60 seconds)")

        async with message.channel.typing():
            try:
                result = await asyncio.to_thread(
                    scrape_company_internships, companies, "internship"
                )
            except Exception as e:
                log.exception("Company scrape error")
                result = f"Error during scraping: {e}"

        for chunk in _split_message(result):
            await message.channel.send(chunk)
        return


def main():
    if not DISCORD_TOKEN:
        print(
            "Error: DISCORD_TOKEN not set.\n"
            "1. Go to https://discord.com/developers/applications\n"
            "2. Create an application → Bot → copy the token\n"
            "3. Add DISCORD_TOKEN=your_token to your .env file\n\n"
            "No ANTHROPIC_API_KEY needed! This bot scrapes directly."
        )
        sys.exit(1)

    log.info("Starting scraper bot (no Claude API key needed)...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
