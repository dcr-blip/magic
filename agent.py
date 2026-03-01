"""Autonomous agent powered by Claude with web browsing and code execution."""

import json
import sys

import anthropic
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text

from internship_scraper import find_internships
from tools import execute_python, fetch_page, read_file, web_search, write_file

console = Console()

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information using DuckDuckGo. "
            "Returns a list of results with titles, URLs, and snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Max number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch and extract the text content of a web page from a URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "execute_python",
        "description": (
            "Execute Python code and return stdout/stderr. "
            "Use this for calculations, data processing, or any programmatic task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The Python code to execute"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file from disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file on disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "find_internships",
        "description": (
            "Search for internship listings at companies with 50-500 employees. "
            "Pulls from The Muse API and Indeed, enriching results with company size "
            "data. Returns a formatted list of matching positions with company name, "
            "size, location, and application URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": (
                        "Role or skill keywords to filter by, "
                        "e.g. 'software engineering', 'data science', 'marketing'. "
                        "Leave blank to search all internships."
                    ),
                    "default": "",
                },
                "location": {
                    "type": "string",
                    "description": (
                        "City or region filter, e.g. 'New York', 'San Francisco', 'Remote'. "
                        "Leave blank for all locations."
                    ),
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of listings to return (default: 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
]

TOOL_FUNCTIONS = {
    "web_search": web_search,
    "fetch_page": fetch_page,
    "execute_python": execute_python,
    "read_file": read_file,
    "write_file": write_file,
    "find_internships": find_internships,
}

SYSTEM_PROMPT = """\
You are an autonomous agent that can browse the web, write and execute Python code,
read/write files, and search for internship opportunities at mid-sized companies.

Guidelines:
- Search the web to gather current information before making claims.
- Verify facts by cross-referencing multiple sources when accuracy matters.
- Use execute_python for any calculations or data transformations.
- Use write_file to persist results or generated code for the user.
- Use find_internships when the user wants internship listings; it automatically
  filters to companies with 50-500 employees. You can call it multiple times with
  different keywords or locations to broaden the search.
- When finished, summarise what you did and what you found.
"""


class Agent:
    def __init__(self, model: str = "claude-sonnet-4-6", max_iterations: int = 20):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_iterations = max_iterations
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear conversation history, starting fresh."""
        self.history = []

    def run(self, task: str) -> str:
        """Start a brand-new conversation with *task* and return the final reply."""
        self.reset()
        return self.chat(task)

    def chat(self, message: str) -> str:
        """
        Add *message* to the ongoing conversation and return the agent's reply.
        Conversation history is preserved across calls so the agent remembers context.
        """
        self.history.append({"role": "user", "content": message})
        return self._run_loop()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        fn = TOOL_FUNCTIONS.get(tool_name)
        if fn is None:
            return f"Unknown tool: {tool_name}"
        return fn(**tool_input)

    def _call_api(self) -> tuple[anthropic.types.Message, str]:
        """
        Stream a response from Claude.

        Shows a spinner until the first text token arrives, then streams text
        directly to stdout. Returns (final_message, full_text).
        """
        full_text = ""
        spinner_active = True

        live = Live(
            Spinner("dots", text="[dim]Thinking...[/dim]"),
            console=console,
            transient=True,   # erase spinner line when stopped
            refresh_per_second=12,
        )
        live.start()

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.history,
            ) as stream:
                for text in stream.text_stream:
                    if spinner_active:
                        spinner_active = False
                        live.stop()
                    full_text += text
                    sys.stdout.write(text)
                    sys.stdout.flush()

                response = stream.get_final_message()
        finally:
            if spinner_active:
                live.stop()

        if full_text:
            sys.stdout.write("\n")
            sys.stdout.flush()

        return response, full_text

    def _run_loop(self) -> str:
        for iteration in range(self.max_iterations):
            if iteration > 0:
                console.print(Rule(style="dim"))

            response, streamed_text = self._call_api()
            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return streamed_text

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    # Display tool call header
                    args_str = json.dumps(block.input, indent=2)
                    args_display = args_str if len(args_str) <= 300 else args_str[:300] + "..."
                    console.print(
                        Text.assemble(
                            ("⚙  ", "bold cyan"),
                            (block.name, "cyan"),
                            ("  ", ""),
                            (args_display, "dim"),
                        )
                    )

                    # Execute with spinner
                    result = ""
                    with Live(
                        Spinner("dots", text=f"[dim]Running {block.name}...[/dim]"),
                        console=console,
                        transient=True,
                        refresh_per_second=12,
                    ):
                        result = self._execute_tool(block.name, block.input)

                    # Show a preview of the result
                    result_str = str(result)
                    preview = result_str[:400] + ("..." if len(result_str) > 400 else "")
                    console.print(f"[dim green]   ↳ {preview}[/dim green]")

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        }
                    )

                self.history.append({"role": "user", "content": tool_results})
            else:
                break

        return "Agent reached the maximum number of iterations without completing the task."
