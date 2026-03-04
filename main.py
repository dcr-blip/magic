#!/usr/bin/env python3
"""Entry point for the autonomous agent.

Usage:
  python main.py                         Interactive AI agent (needs ANTHROPIC_API_KEY)
  python main.py "some task"             Single AI task (needs ANTHROPIC_API_KEY)
  python main.py --scrape                Scrape job boards directly (FREE, no API key)
  python main.py --scrape --keywords "data science" --location "NYC"
  python main.py --companies "Stripe, Notion, Figma"
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

load_dotenv()

console = Console()

_HELP_TEXT = """\
[bold]Commands[/bold]
  [cyan]reset[/cyan]   Clear conversation history and start fresh
  [cyan]help[/cyan]    Show this message
  [cyan]quit[/cyan]    Exit

[bold]Tips[/bold]
  The agent remembers previous messages within a session.
  Type [cyan]reset[/cyan] to start a new conversation at any time.\
"""

_BANNER = Panel(
    Text.from_markup(
        "[bold white]Autonomous Agent[/bold white]  [dim]powered by Claude[/dim]\n"
        "[dim]Web · Shell · GitHub · Weather · News · Data · Charts · Code[/dim]"
    ),
    border_style="blue",
    padding=(0, 2),
)


def _check_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set.")
        console.print("Copy [dim].env.example[/dim] to [dim].env[/dim] and add your API key.")
        console.print(
            "\n[dim]Tip: Use [cyan]--scrape[/cyan] or [cyan]--companies[/cyan] "
            "to scrape job boards without an API key.[/dim]"
        )
        sys.exit(1)


def _run_single_task(task: str) -> None:
    """Run one task and exit (non-interactive mode)."""
    from agent import Agent

    console.print(Panel(task, title="Task", border_style="dim"))
    agent = Agent()
    agent.run(task)


def _run_repl() -> None:
    """Interactive multi-turn conversation loop."""
    from agent import Agent

    console.print(_BANNER)
    console.print(
        "[dim]Type [/dim][cyan]help[/cyan][dim] for commands or just describe what you want.[/dim]\n"
    )

    agent = Agent()

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "reset":
            agent.reset()
            console.print("[dim]Conversation cleared. Starting fresh.[/dim]")
            console.print(Rule(style="dim"))
            continue

        if cmd == "help":
            console.print(Panel(_HELP_TEXT, border_style="dim"))
            continue

        console.print(Rule(style="dim"))
        console.print("[bold green]Agent[/bold green]")
        agent.chat(user_input)
        console.print()


def _run_scrape(keywords: str, location: str, max_results: int) -> None:
    """Scrape job boards directly — no Claude API key needed."""
    from internship_scraper import find_internships

    console.print(
        f"[bold]Scraping 6 job boards[/bold] for [cyan]{keywords}[/cyan]"
        + (f" in [cyan]{location}[/cyan]" if location else "")
        + f" (max {max_results} results)...\n"
    )
    result = find_internships(keywords=keywords, location=location, max_results=max_results)
    console.print(result)


def _run_companies(companies: str) -> None:
    """Search specific companies for internships — no Claude API key needed."""
    from internship_scraper import scrape_company_internships

    console.print(f"[bold]Searching for internships at:[/bold] [cyan]{companies}[/cyan]\n")
    result = scrape_company_internships(companies=companies, keywords="internship")
    console.print(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous Agent — AI-powered or direct job scraping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples (FREE, no API key needed):\n"
            "  python main.py --scrape\n"
            '  python main.py --scrape --keywords "data science" --location "NYC"\n'
            '  python main.py --companies "Stripe, Notion, Figma"\n'
            "\n"
            "Examples (needs ANTHROPIC_API_KEY):\n"
            "  python main.py                    # Interactive AI agent\n"
            '  python main.py "find internships" # Single AI task\n'
        ),
    )
    parser.add_argument("task", nargs="*", help="Task for the AI agent (needs API key)")
    parser.add_argument("--scrape", action="store_true", help="Scrape job boards directly (FREE)")
    parser.add_argument("--keywords", default="software engineering", help="Job search keywords")
    parser.add_argument("--location", default="", help="Location filter (e.g. 'NYC', 'Remote')")
    parser.add_argument("--max-results", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--companies", type=str, default="", help="Comma-separated company list")

    args = parser.parse_args()

    # Direct scraping modes — no API key needed
    if args.scrape:
        _run_scrape(args.keywords, args.location, args.max_results)
        return

    if args.companies:
        _run_companies(args.companies)
        return

    # AI agent modes — need API key
    _check_api_key()

    if args.task:
        _run_single_task(" ".join(args.task))
    else:
        _run_repl()


if __name__ == "__main__":
    main()
