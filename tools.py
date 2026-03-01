"""Tool implementations for the autonomous agent."""

import csv
import io
import json
import os
import sqlite3
import subprocess
import sys

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

from internship_scraper import find_internships  # noqa: F401  (re-exported as a tool)

# ---------------------------------------------------------------------------
# Safety: commands blocked from shell execution
# ---------------------------------------------------------------------------
_BLOCKED_SHELL_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){",
    "fork bomb",
    "> /dev/sda",
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
]


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        output = []
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r['title']}\n   URL: {r['href']}\n   {r['body']}")
        return "\n\n".join(output)
    except Exception as e:
        return f"Search error: {e}"


def fetch_page(url: str, max_chars: int = 8000) -> str:
    """Fetch and extract text content from a URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AutonomousAgent/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[Content truncated at {max_chars} chars]"
        return text
    except Exception as e:
        return f"Error fetching page: {e}"


def execute_python(code: str, timeout: int = 30) -> str:
    """Execute Python code in a subprocess and return the output."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}"
        if not output:
            output = "(no output)"
        output += f"\nExit code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Code execution timed out after {timeout}s"
    except Exception as e:
        return f"Error executing code: {e}"


def read_file(path: str) -> str:
    """Read the contents of a file from disk."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 10000:
            content = content[:10000] + "\n\n[File truncated at 10000 chars]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file on disk."""
    try:
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


# ---------------------------------------------------------------------------
# Shell commands
# ---------------------------------------------------------------------------

def run_shell(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return its output."""
    cmd_lower = command.lower().strip()
    for pattern in _BLOCKED_SHELL_PATTERNS:
        if pattern in cmd_lower:
            return f"Blocked: '{command}' matches dangerous pattern '{pattern}'."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("" if not output else "\n") + f"STDERR:\n{result.stderr}"
        if not output:
            output = "(no output)"
        output += f"\nExit code: {result.returncode}"
        if len(output) > 10000:
            output = output[:10000] + "\n[Output truncated at 10000 chars]"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error running command: {e}"


# ---------------------------------------------------------------------------
# API integrations
# ---------------------------------------------------------------------------

def github_api(endpoint: str, method: str = "GET", params: str = "") -> str:
    """Call the GitHub API. Requires GITHUB_TOKEN env var for private repos."""
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = endpoint if endpoint.startswith("http") else f"https://api.github.com/{endpoint.lstrip('/')}"

    try:
        parsed_params = json.loads(params) if params else {}
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=parsed_params, timeout=15)
        elif method.upper() == "POST":
            resp = requests.post(url, headers=headers, json=parsed_params, timeout=15)
        else:
            resp = requests.request(method.upper(), url, headers=headers, json=parsed_params, timeout=15)

        resp.raise_for_status()
        data = resp.json()
        text = json.dumps(data, indent=2)
        if len(text) > 10000:
            text = text[:10000] + "\n[Response truncated at 10000 chars]"
        return text
    except requests.exceptions.HTTPError as e:
        return f"GitHub API error {resp.status_code}: {resp.text[:500]}"
    except Exception as e:
        return f"GitHub API error: {e}"


def get_weather(location: str) -> str:
    """Get current weather for a location using wttr.in (no API key needed)."""
    try:
        url = f"https://wttr.in/{requests.utils.quote(location)}?format=j1"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]

        city = area.get("areaName", [{}])[0].get("value", location)
        country = area.get("country", [{}])[0].get("value", "")
        temp_c = current.get("temp_C", "?")
        temp_f = current.get("temp_F", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "")
        humidity = current.get("humidity", "?")
        wind_mph = current.get("windspeedMiles", "?")
        feels_c = current.get("FeelsLikeC", "?")
        feels_f = current.get("FeelsLikeF", "?")

        return (
            f"Weather for {city}, {country}:\n"
            f"  Condition: {desc}\n"
            f"  Temperature: {temp_c}°C / {temp_f}°F\n"
            f"  Feels like: {feels_c}°C / {feels_f}°F\n"
            f"  Humidity: {humidity}%\n"
            f"  Wind: {wind_mph} mph"
        )
    except Exception as e:
        return f"Weather error: {e}"


def get_news(query: str, max_results: int = 5) -> str:
    """Search for recent news articles using DuckDuckGo News."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        if not results:
            return "No news found."
        output = []
        for i, r in enumerate(results, 1):
            date = r.get("date", "")
            source = r.get("source", "")
            output.append(
                f"{i}. {r['title']}\n"
                f"   Source: {source} | {date}\n"
                f"   URL: {r['url']}\n"
                f"   {r.get('body', '')}"
            )
        return "\n\n".join(output)
    except Exception as e:
        return f"News search error: {e}"


# ---------------------------------------------------------------------------
# Data & analysis
# ---------------------------------------------------------------------------

def query_db(db_path: str, query: str, params: str = "[]") -> str:
    """Run a SQL query against a SQLite database and return results."""
    try:
        parsed_params = json.loads(params) if params else []
    except json.JSONDecodeError:
        parsed_params = []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, parsed_params)

        if query.strip().upper().startswith("SELECT") or query.strip().upper().startswith("PRAGMA"):
            rows = cursor.fetchall()
            if not rows:
                conn.close()
                return "Query returned 0 rows."
            columns = rows[0].keys()
            output = ["\t".join(columns)]
            for row in rows[:500]:
                output.append("\t".join(str(v) for v in row))
            result = "\n".join(output)
            if len(rows) > 500:
                result += f"\n[Showing 500 of {len(rows)} rows]"
            conn.close()
            return result
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return f"Query executed. Rows affected: {affected}"
    except Exception as e:
        return f"Database error: {e}"


def analyze_data(file_path: str, operation: str = "summary") -> str:
    """Load a CSV or JSON file and perform analysis.

    Operations: summary, head, describe, columns, shape, value_counts:<column>
    """
    try:
        if file_path.endswith(".csv"):
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                columns = reader.fieldnames or []
        elif file_path.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                rows = data
                columns = list(rows[0].keys()) if rows else []
            elif isinstance(data, dict):
                return f"JSON object with keys: {', '.join(data.keys())}\nUse a more specific path or convert to a list."
            else:
                return f"Unexpected JSON type: {type(data).__name__}"
        else:
            return "Unsupported file format. Use .csv or .json files."

        if operation == "summary":
            num_cols = []
            for col in columns:
                try:
                    [float(r[col]) for r in rows[:10] if r.get(col)]
                    num_cols.append(col)
                except (ValueError, TypeError):
                    pass
            return (
                f"File: {file_path}\n"
                f"Rows: {len(rows)}\n"
                f"Columns ({len(columns)}): {', '.join(columns)}\n"
                f"Numeric columns: {', '.join(num_cols) or 'none detected'}\n"
                f"Sample row: {json.dumps(rows[0], indent=2) if rows else 'empty'}"
            )
        elif operation == "head":
            sample = rows[:10]
            return json.dumps(sample, indent=2)
        elif operation == "columns":
            return "\n".join(f"  {i+1}. {c}" for i, c in enumerate(columns))
        elif operation == "shape":
            return f"Rows: {len(rows)}, Columns: {len(columns)}"
        elif operation.startswith("value_counts:"):
            col = operation.split(":", 1)[1].strip()
            if col not in columns:
                return f"Column '{col}' not found. Available: {', '.join(columns)}"
            counts: dict[str, int] = {}
            for r in rows:
                val = str(r.get(col, ""))
                counts[val] = counts.get(val, 0) + 1
            sorted_counts = sorted(counts.items(), key=lambda x: -x[1])[:30]
            return "\n".join(f"  {v}: {c}" for v, c in sorted_counts)
        elif operation == "describe":
            results = []
            for col in columns:
                vals = []
                for r in rows:
                    try:
                        vals.append(float(r[col]))
                    except (ValueError, TypeError, KeyError):
                        pass
                if vals:
                    vals.sort()
                    n = len(vals)
                    mean = sum(vals) / n
                    mid = n // 2
                    median = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2
                    results.append(
                        f"{col}: count={n}, min={vals[0]}, max={vals[-1]}, "
                        f"mean={mean:.2f}, median={median:.2f}"
                    )
            return "\n".join(results) if results else "No numeric columns found."
        else:
            return f"Unknown operation '{operation}'. Use: summary, head, describe, columns, shape, value_counts:<col>"
    except Exception as e:
        return f"Data analysis error: {e}"


def create_chart(data_json: str, chart_type: str = "bar", title: str = "Chart",
                 output_path: str = "chart.png", x_label: str = "", y_label: str = "") -> str:
    """Create a chart from JSON data and save as an image.

    data_json: JSON string with {"labels": [...], "values": [...]} or
               {"labels": [...], "series": {"name1": [...], "name2": [...]}}
    chart_type: bar, line, pie, scatter, hist
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: matplotlib is not installed. Run: pip install matplotlib"

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON data: {e}"

    try:
        labels = data.get("labels", [])
        values = data.get("values", [])
        series = data.get("series", {})

        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "bar":
            if series:
                import numpy as np
                x = np.arange(len(labels))
                width = 0.8 / len(series)
                for i, (name, vals) in enumerate(series.items()):
                    ax.bar(x + i * width, vals, width, label=name)
                ax.set_xticks(x + width * (len(series) - 1) / 2)
                ax.set_xticklabels(labels, rotation=45, ha="right")
                ax.legend()
            else:
                ax.bar(labels, values)
                plt.xticks(rotation=45, ha="right")
        elif chart_type == "line":
            if series:
                for name, vals in series.items():
                    ax.plot(labels, vals, marker="o", label=name)
                ax.legend()
            else:
                ax.plot(labels, values, marker="o")
            plt.xticks(rotation=45, ha="right")
        elif chart_type == "pie":
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
        elif chart_type == "scatter":
            x_vals = data.get("x", labels)
            y_vals = data.get("y", values)
            ax.scatter(x_vals, y_vals)
        elif chart_type == "hist":
            ax.hist(values, bins=data.get("bins", 20), edgecolor="black")
        else:
            plt.close(fig)
            return f"Unknown chart type '{chart_type}'. Use: bar, line, pie, scatter, hist"

        ax.set_title(title)
        if x_label:
            ax.set_xlabel(x_label)
        if y_label:
            ax.set_ylabel(y_label)

        plt.tight_layout()
        dir_path = os.path.dirname(output_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        plt.savefig(output_path, dpi=150)
        plt.close(fig)
        return f"Chart saved to {output_path}"
    except Exception as e:
        return f"Chart error: {e}"
