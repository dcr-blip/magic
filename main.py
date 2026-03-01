#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

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


def main() -> None:
    _check_api_key()

    if len(sys.argv) > 1:
        _run_single_task(" ".join(sys.argv[1:]))
    else:
        _run_repl()


if __name__ == "__main__":
    main()
