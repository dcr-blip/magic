#!/usr/bin/env python3
"""Magic Trading Bot — CLI entry point.

Usage:
    python main.py                          # Run with default config
    python main.py --config my_config.yaml  # Custom config
    python main.py --symbol TSLA            # Override symbol
    python main.py --strategy rsi           # Choose strategy
    python main.py --plot                   # Save equity curve chart
"""

import argparse
import sys
from pathlib import Path

import yaml

from trading.data.market_data import fetch_ohlcv
from trading.core.backtester import Backtester
from trading.core.chart import plot_equity_curve
from trading.strategies.sma_crossover import SMACrossover
from trading.strategies.rsi import RSIStrategy
from trading.strategies.bollinger import BollingerBands


STRATEGY_MAP = {
    "sma": SMACrossover,
    "sma_crossover": SMACrossover,
    "rsi": RSIStrategy,
    "bollinger": BollingerBands,
    "bb": BollingerBands,
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_strategy(name: str, cfg: dict):
    strategies_cfg = cfg.get("strategies", {})

    if name in ("sma", "sma_crossover"):
        params = strategies_cfg.get("sma_crossover", {})
        return SMACrossover(
            short_window=params.get("short_window", 20),
            long_window=params.get("long_window", 50),
        )
    elif name == "rsi":
        params = strategies_cfg.get("rsi", {})
        return RSIStrategy(
            period=params.get("period", 14),
            overbought=params.get("overbought", 70),
            oversold=params.get("oversold", 30),
        )
    elif name in ("bollinger", "bb"):
        params = strategies_cfg.get("bollinger_bands", {})
        return BollingerBands(
            period=params.get("period", 20),
            std_dev=params.get("std_dev", 2.0),
        )
    else:
        print(f"Unknown strategy: {name}")
        print(f"Available: {', '.join(STRATEGY_MAP.keys())}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Magic Trading Bot — Backtest trading strategies")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--symbol", default=None, help="Ticker symbol to backtest (overrides config)")
    parser.add_argument("--strategy", default="sma", choices=list(STRATEGY_MAP.keys()),
                        help="Strategy to use")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=None, help="Initial capital")
    parser.add_argument("--plot", action="store_true", help="Save equity curve chart")
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if config_path.exists():
        cfg = load_config(str(config_path))
    else:
        print(f"Config file not found: {config_path}, using defaults.")
        cfg = {}

    # Resolve parameters
    symbols = [args.symbol] if args.symbol else cfg.get("symbols", ["AAPL"])
    backtest_cfg = cfg.get("backtest", {})
    start_date = args.start or backtest_cfg.get("start_date", "2024-01-01")
    end_date = args.end or backtest_cfg.get("end_date", "2025-01-01")
    initial_capital = args.capital or cfg.get("initial_capital", 100_000.0)
    risk_cfg = cfg.get("risk", {})

    strategy = build_strategy(args.strategy, cfg)

    print(f"Strategy:  {strategy.name}")
    print(f"Period:    {start_date} to {end_date}")
    print(f"Capital:   ${initial_capital:,.2f}")
    print(f"Symbols:   {', '.join(symbols)}")
    print()

    for symbol in symbols:
        print(f"Fetching data for {symbol}...")
        try:
            data = fetch_ohlcv(symbol, start_date, end_date)
        except ValueError as e:
            print(f"  Error: {e}")
            continue

        print(f"  {len(data)} bars loaded.")

        backtester = Backtester(
            strategy=strategy,
            initial_capital=initial_capital,
            commission_pct=risk_cfg.get("commission_pct", 0.001),
            max_position_pct=risk_cfg.get("max_position_pct", 0.10),
            stop_loss_pct=risk_cfg.get("stop_loss_pct", 0.05),
            take_profit_pct=risk_cfg.get("take_profit_pct", 0.15),
        )

        result = backtester.run(symbol, data)
        print(result.summary())

        if args.plot:
            plot_equity_curve(result, output_path=f"equity_{symbol}_{args.strategy}.png")

        # Print individual trades
        if result.trades:
            print(f"\n  Trades for {symbol}:")
            for i, t in enumerate(result.trades, 1):
                print(f"    {i}. {t.side.value} {t.quantity} @ "
                      f"entry=${t.entry_price:.2f} exit=${t.exit_price:.2f} "
                      f"P&L=${t.pnl:+,.2f} ({t.pnl_pct:+.2%})")
        print()


if __name__ == "__main__":
    main()
