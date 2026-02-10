# Magic Trading Bot

An algorithmic trading backtesting framework in Python.

## Features

- **3 built-in strategies**: SMA Crossover, RSI, Bollinger Bands
- **Backtesting engine** with stop-loss, take-profit, and commission modeling
- **Portfolio tracker** with equity curve, drawdown, and Sharpe ratio
- **Equity curve charts** saved as PNG
- **YAML config** for easy parameter tuning

## Quick Start

```bash
pip install -r requirements.txt

# Run with defaults (SMA crossover on AAPL)
python main.py

# Use a specific strategy and symbol
python main.py --strategy rsi --symbol TSLA

# Bollinger Bands with custom dates and chart output
python main.py --strategy bollinger --symbol MSFT --start 2023-06-01 --end 2024-06-01 --plot
```

## Strategies

| Name | Flag | Description |
|------|------|-------------|
| SMA Crossover | `--strategy sma` | Buy on golden cross, sell on death cross |
| RSI | `--strategy rsi` | Buy when oversold, sell when overbought |
| Bollinger Bands | `--strategy bollinger` | Mean-reversion on band touches |

## Configuration

Edit `config.yaml` to adjust:

- Initial capital
- Symbols to trade
- Backtest date range
- Strategy parameters (window sizes, thresholds)
- Risk management (position sizing, stop-loss, take-profit, commission)

## Project Structure

```
magic/
├── main.py                  # CLI entry point
├── config.yaml              # Configuration
├── requirements.txt         # Dependencies
└── trading/
    ├── core/
    │   ├── models.py        # Order, Position, Trade, Signal
    │   ├── portfolio.py     # Portfolio & position management
    │   ├── backtester.py    # Backtesting engine
    │   └── chart.py         # Equity curve plotting
    ├── data/
    │   └── market_data.py   # Historical data fetching (yfinance)
    └── strategies/
        ├── base.py          # Strategy abstract base class
        ├── sma_crossover.py # SMA crossover strategy
        ├── rsi.py           # RSI strategy
        └── bollinger.py     # Bollinger Bands strategy
```
