"""Equity curve and trade visualization."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from trading.core.backtester import BacktestResult


def plot_equity_curve(result: BacktestResult, output_path: str = "equity_curve.png"):
    """Save an equity curve chart to disk."""
    if not result.equity_curve:
        print("No equity data to plot.")
        return

    dates = [d for d, _ in result.equity_curve]
    equities = [e for _, e in result.equity_curve]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(dates, equities, linewidth=1.5, color="#2196F3")
    ax.axhline(y=result.initial_capital, color="gray", linestyle="--", linewidth=0.8)
    ax.fill_between(
        dates, result.initial_capital, equities,
        where=[e >= result.initial_capital for e in equities],
        alpha=0.15, color="green",
    )
    ax.fill_between(
        dates, result.initial_capital, equities,
        where=[e < result.initial_capital for e in equities],
        alpha=0.15, color="red",
    )
    ax.set_title(f"{result.strategy_name} — {result.symbol}", fontsize=13)
    ax.set_ylabel("Portfolio Value ($)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Equity curve saved to {output_path}")
