"""Discord bot that wraps the autonomous agent."""

import asyncio
import logging
import os

import discord
from dotenv import load_dotenv

from agent import Agent

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discord_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
BOT_PREFIX = os.getenv("BOT_PREFIX", "!agent")
MAX_DISCORD_LEN = 2000  # Discord's message character limit

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Per-channel agent instances so each channel keeps its own conversation.
_agents: dict[int, Agent] = {}


def _get_agent(channel_id: int) -> Agent:
    """Return (or create) a headless Agent for *channel_id*."""
    if channel_id not in _agents:
        _agents[channel_id] = Agent(headless=True)
    return _agents[channel_id]


def _split_message(text: str) -> list[str]:
    """Split *text* into chunks that fit within Discord's 2000-char limit."""
    if len(text) <= MAX_DISCORD_LEN:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= MAX_DISCORD_LEN:
            chunks.append(text)
            break

        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, MAX_DISCORD_LEN)
        if split_at == -1 or split_at < MAX_DISCORD_LEN // 2:
            split_at = MAX_DISCORD_LEN

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (id={bot.user.id})")
    log.info(f"Prefix: '{BOT_PREFIX}'  |  Serving {len(bot.guilds)} guild(s)")


@bot.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == bot.user:
        return

    content = message.content.strip()

    # --- Check for prefix or mention ---
    prompt = ""
    if content.lower().startswith(BOT_PREFIX):
        prompt = content[len(BOT_PREFIX):].strip()
    elif bot.user in message.mentions:
        # Strip the mention itself
        prompt = content.replace(f"<@{bot.user.id}>", "").strip()
    else:
        return  # Not addressed to us

    if not prompt:
        await message.reply(
            f"Hi! Send me a message after `{BOT_PREFIX}` and I'll get to work.\n"
            f"Commands: `{BOT_PREFIX} reset` — clear conversation memory."
        )
        return

    # --- Built-in commands ---
    if prompt.lower() == "reset":
        agent = _get_agent(message.channel.id)
        agent.reset()
        await message.reply("Conversation memory cleared.")
        return

    if prompt.lower() == "help":
        await message.reply(
            f"**Agent Bot — Help**\n"
            f"`{BOT_PREFIX} <your request>` — ask the agent anything\n"
            f"`{BOT_PREFIX} reset` — clear conversation memory\n"
            f"`{BOT_PREFIX} help` — show this message\n\n"
            f"I can search the web, run code, query APIs, analyse data, "
            f"find internships, and more."
        )
        return

    # --- Run the agent ---
    agent = _get_agent(message.channel.id)

    # Show typing indicator while the agent works
    async with message.channel.typing():
        try:
            # Run the blocking agent in a thread so we don't block the event loop
            reply = await asyncio.to_thread(agent.chat, prompt)
        except Exception as e:
            log.exception("Agent error")
            reply = f"Something went wrong: {e}"

    if not reply or not reply.strip():
        reply = "(The agent returned an empty response.)"

    # Send the reply, splitting if necessary
    chunks = _split_message(reply)
    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(chunk)
        else:
            await message.channel.send(chunk)


def main():
    if not DISCORD_TOKEN:
        print(
            "Error: DISCORD_TOKEN not set.\n"
            "1. Go to https://discord.com/developers/applications\n"
            "2. Create an application → Bot → copy the token\n"
            "3. Add DISCORD_TOKEN=your_token to your .env file\n"
            "4. Invite the bot to your server with the OAuth2 URL generator\n"
            "   (scopes: bot | permissions: Send Messages, Read Message History)"
        )
        raise SystemExit(1)

    log.info("Starting Discord bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
