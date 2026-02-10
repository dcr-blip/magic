#!/usr/bin/env python3
"""Magic Trading Bot — CLI entry point.

Usage:
    python main.py                                  # Run composite strategy on defaults
    python main.py --strategy sma --symbol AAPL     # Single strategy
    python main.py --strategy composite --symbol TSLA --plot
    python main.py --analyze AAPL                   # Full analysis report (no backtest)
    python main.py --scan AAPL MSFT GOOGL           # Scan multiple symbols for signals
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
from trading.strategies.composite import CompositeStrategy
from trading.analysis.indicators import add_all_indicators
from trading.analysis.volume import add_volume_analysis, detect_volume_spikes
from trading.analysis.market_structure import analyze_structure
from trading.analysis.patterns import scan_all_patterns
from trading.analysis.options_flow import fetch_options_snapshot, options_sentiment_score


STRATEGY_MAP = {
    "sma": SMACrossover,
    "sma_crossover": SMACrossover,
    "rsi": RSIStrategy,
    "bollinger": BollingerBands,
    "bb": BollingerBands,
    "composite": CompositeStrategy,
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
    elif name == "composite":
        params = strategies_cfg.get("composite", {})
        return CompositeStrategy(
            sma_short=params.get("sma_short", 50),
            sma_long=params.get("sma_long", 200),
            rsi_period=params.get("rsi_period", 14),
            rsi_overbought=params.get("rsi_overbought", 70),
            rsi_oversold=params.get("rsi_oversold", 30),
            bb_period=params.get("bb_period", 20),
            bb_std=params.get("bb_std", 2.0),
            vol_spike_threshold=params.get("vol_spike_threshold", 2.0),
            vol_lookback=params.get("vol_lookback", 20),
            mfi_period=params.get("mfi_period", 14),
            swing_lookback=params.get("swing_lookback", 5),
            use_options=params.get("use_options", True),
            signal_threshold=params.get("signal_threshold", 0.35),
            weight_technical=params.get("weight_technical", 0.30),
            weight_volume=params.get("weight_volume", 0.20),
            weight_structure=params.get("weight_structure", 0.20),
            weight_patterns=params.get("weight_patterns", 0.15),
            weight_options=params.get("weight_options", 0.15),
        )
    else:
        print(f"Unknown strategy: {name}")
        print(f"Available: {', '.join(STRATEGY_MAP.keys())}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Full analysis report (--analyze)
# ---------------------------------------------------------------------------

def run_analysis(symbol: str, cfg: dict, start: str, end: str):
    """Print a comprehensive analysis report for a single symbol."""
    print(f"\n{'='*60}")
    print(f"  FULL ANALYSIS: {symbol}")
    print(f"{'='*60}")

    print(f"\nFetching data for {symbol} ({start} to {end})...")
    data = fetch_ohlcv(symbol, start, end)
    print(f"  {len(data)} bars loaded.\n")

    analysis_cfg = cfg.get("analysis", {})

    # --- Technical Indicators ---
    comp_cfg = cfg.get("strategies", {}).get("composite", {})
    enriched = add_all_indicators(
        data,
        sma_short=comp_cfg.get("sma_short", 50),
        sma_long=comp_cfg.get("sma_long", 200),
    )
    last = enriched.iloc[-1]
    print("--- Technical Indicators (latest bar) ---")
    for col in ["sma_50", "sma_200", "rsi", "vwap", "macd", "macd_signal",
                "macd_hist", "bb_upper", "bb_mid", "bb_lower", "bb_pct_b",
                "atr", "stoch_k", "stoch_d"]:
        if col in last.index:
            print(f"  {col:>16s}: {last[col]:>10.2f}")

    sma_cross = last.get("sma_cross", 0)
    if sma_cross > 0:
        print("  >>> SMA 50/200 GOLDEN CROSS on latest bar")
    elif sma_cross < 0:
        print("  >>> SMA 50/200 DEATH CROSS on latest bar")

    # --- Volume Analysis ---
    print("\n--- Volume Analysis ---")
    vol_enriched = add_volume_analysis(data)
    vol_last = vol_enriched.iloc[-1]
    for col in ["obv", "ad_line", "mfi", "vpt", "buy_vol", "sell_vol", "net_flow", "flow_ratio"]:
        if col in vol_last.index:
            val = vol_last[col]
            if col == "flow_ratio":
                print(f"  {col:>16s}: {val:>10.2%}")
            else:
                print(f"  {col:>16s}: {val:>14,.0f}")

    vol_cfg = analysis_cfg.get("volume", {})
    spikes = detect_volume_spikes(
        data,
        lookback=vol_cfg.get("lookback", 20),
        spike_threshold=vol_cfg.get("spike_threshold", 2.0),
    )
    if spikes:
        print(f"\n  Volume alerts ({len(spikes)} total, showing last 10):")
        for alert in spikes[-10:]:
            print(f"    [{alert.timestamp:%Y-%m-%d}] {alert.description}")
    else:
        print("  No volume spikes detected.")

    # --- Market Structure ---
    struct_cfg = analysis_cfg.get("market_structure", {})
    structure = analyze_structure(
        data,
        swing_lookback=struct_cfg.get("swing_lookback", 5),
        cluster_pct=struct_cfg.get("cluster_pct", 0.015),
    )
    print(f"\n{structure.summary()}")

    # --- Pattern Recognition ---
    pat_cfg = analysis_cfg.get("patterns", {})
    patterns = scan_all_patterns(data, swing_lookback=pat_cfg.get("swing_lookback", 5))
    print(f"\n--- Pattern Recognition ({len(patterns)} found, showing last 15) ---")
    if patterns:
        for p in patterns[-15:]:
            print(f"  [{p.end_time:%Y-%m-%d}] {p}")
    else:
        print("  No patterns detected.")

    # --- Options Flow ---
    print("\n--- Options Flow ---")
    opts_cfg = analysis_cfg.get("options", {})
    snap = fetch_options_snapshot(
        symbol,
        vol_oi_threshold=opts_cfg.get("vol_oi_threshold", 3.0),
        min_volume=opts_cfg.get("min_volume", 100),
        max_expiries=opts_cfg.get("max_expiries", 4),
    )
    if snap:
        print(snap.summary())
        score, reason = options_sentiment_score(snap)
        print(f"\n  Options sentiment: {score:+.2f} — {reason}")
    else:
        print("  Options data unavailable for this symbol.")

    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Magic Trading Bot — Backtest & Analyze")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--symbol", default=None, help="Ticker symbol (overrides config)")
    parser.add_argument("--strategy", default="composite", choices=list(STRATEGY_MAP.keys()),
                        help="Strategy to use (default: composite)")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=None, help="Initial capital")
    parser.add_argument("--plot", action="store_true", help="Save equity curve chart")
    parser.add_argument("--analyze", nargs="+", metavar="SYMBOL",
                        help="Run full analysis report (no backtest)")
    parser.add_argument("--scan", nargs="+", metavar="SYMBOL",
                        help="Quick scan multiple symbols for signals")
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if config_path.exists():
        cfg = load_config(str(config_path))
    else:
        print(f"Config file not found: {config_path}, using defaults.")
        cfg = {}

    backtest_cfg = cfg.get("backtest", {})
    start_date = args.start or backtest_cfg.get("start_date", "2024-01-01")
    end_date = args.end or backtest_cfg.get("end_date", "2025-01-01")

    # --- Analysis mode ---
    if args.analyze:
        for symbol in args.analyze:
            try:
                run_analysis(symbol, cfg, start_date, end_date)
            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")
        return

    # --- Scan mode ---
    if args.scan:
        print(f"Scanning {len(args.scan)} symbols with composite scoring...\n")
        for symbol in args.scan:
            try:
                data = fetch_ohlcv(symbol, start_date, end_date)
                strategy = build_strategy("composite", cfg)
                signals = strategy.generate_signals(data)
                if signals:
                    last = signals[-1]
                    print(f"  {symbol:>6s}: {last.side.value:4s} (strength {last.strength:.2f}) "
                          f"— {last.reason[:80]}")
                else:
                    print(f"  {symbol:>6s}: No signals generated")
            except Exception as e:
                print(f"  {symbol:>6s}: Error — {e}")
        return

    # --- Backtest mode (default) ---
    symbols = [args.symbol] if args.symbol else cfg.get("symbols", ["AAPL"])
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
