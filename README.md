# Magic Trading Bot

An algorithmic trading backtesting and analysis framework in Python featuring multi-factor signal fusion, volume flow analysis, market structure detection, pattern recognition, and options flow sentiment.

## Features

### Strategies
- **SMA Crossover** — Golden/death cross on configurable moving averages
- **RSI** — Overbought/oversold mean reversion
- **Bollinger Bands** — Mean reversion on band touches
- **Composite Multi-Factor** (default) — Fuses all analysis modules into a single weighted score

### Technical Indicators
- **SMA 50/200** with golden/death cross detection
- **RSI** (14-period) with overbought/oversold zones
- **MACD** (12/26/9) with signal line and histogram
- **Bollinger Bands** with %B position
- **VWAP** (Volume Weighted Average Price)
- **ATR** (Average True Range) for volatility
- **Stochastic Oscillator** (%K / %D)

### Volume Analysis
- **On-Balance Volume (OBV)** — cumulative directional volume
- **Accumulation/Distribution Line** — Chaikin A/D
- **Money Flow Index (MFI)** — volume-weighted RSI
- **Volume-Price Trend (VPT)**
- **Net Volume Flow** — rolling buy vs sell pressure ratio
- **Volume Spike Detection** — climax buys/sells and dry-ups

### Options Flow
- **Put/Call Ratio** — volume and open interest
- **Unusual Options Activity** — contracts where volume >> open interest
- **Max Pain** — strike with minimum option holder payout
- **Sentiment Scoring** — converts options data into a -1 to +1 score

### Market Structure
- **Trend Detection** — SMA alignment, slope, and price position
- **Swing Points** — Higher Highs, Higher Lows, Lower Highs, Lower Lows
- **Support & Resistance** — clustered swing levels with strength counts
- **Price vs Structure** — whether price is near/testing S/R levels

### Pattern Recognition
- **Structural**: Double Top/Bottom, Head & Shoulders (regular + inverse)
- **Flags**: Bull Flag, Bear Flag
- **Candlestick**: Bullish/Bearish Engulfing, Hammer, Shooting Star, Morning/Evening Star

### Backtesting Engine
- Stop-loss and take-profit enforcement
- Commission modeling
- Position sizing (% of capital)
- Equity curve, max drawdown, Sharpe ratio

## Quick Start

```bash
pip install -r requirements.txt

# Backtest with composite strategy (default)
python main.py

# Full analysis report for a symbol
python main.py --analyze AAPL

# Scan multiple symbols for the latest signal
python main.py --scan AAPL MSFT GOOGL TSLA AMZN

# Backtest a specific strategy
python main.py --strategy rsi --symbol TSLA --plot

# Composite with custom dates
python main.py --symbol NVDA --start 2023-01-01 --end 2025-01-01 --plot
```

## CLI Modes

| Mode | Flag | Description |
|------|------|-------------|
| Backtest | *(default)* | Run strategy against historical data, show P&L |
| Analyze | `--analyze SYMBOL [...]` | Full multi-section report: indicators, volume, structure, patterns, options |
| Scan | `--scan SYMBOL [...]` | Quick composite signal for each symbol |

## Composite Strategy Weights

The default composite strategy scores each bar across five dimensions:

| Factor | Weight | Inputs |
|--------|--------|--------|
| Technical | 30% | SMA cross, RSI, MACD, Bollinger %B |
| Volume | 20% | MFI, net flow ratio, volume spikes |
| Market Structure | 20% | Trend direction, S/R proximity |
| Patterns | 15% | Chart and candlestick patterns |
| Options Flow | 15% | P/C ratio, unusual activity |

All weights are configurable in `config.yaml`.

## Configuration

Edit `config.yaml` to adjust:

- Initial capital and symbols
- Backtest date range
- Strategy parameters (SMA windows, RSI thresholds, etc.)
- Composite weights and signal threshold
- Risk management (position sizing, stop-loss, take-profit, commission)
- Analysis settings (volume spike thresholds, S/R clustering, options scanning)

## Project Structure

```
magic/
├── main.py                          # CLI entry point (backtest / analyze / scan)
├── config.yaml                      # Configuration
├── requirements.txt                 # Dependencies
└── trading/
    ├── core/
    │   ├── models.py                # Order, Position, Trade, Signal
    │   ├── portfolio.py             # Portfolio & position management
    │   ├── backtester.py            # Backtesting engine
    │   └── chart.py                 # Equity curve plotting
    ├── data/
    │   └── market_data.py           # Historical OHLCV & options chain fetching
    ├── strategies/
    │   ├── base.py                  # Strategy abstract base class
    │   ├── sma_crossover.py         # SMA crossover strategy
    │   ├── rsi.py                   # RSI strategy
    │   ├── bollinger.py             # Bollinger Bands strategy
    │   └── composite.py             # Multi-factor composite strategy
    └── analysis/
        ├── indicators.py            # Technical indicators (SMA, RSI, MACD, BB, VWAP, ATR, Stoch)
        ├── volume.py                # Volume flow, spikes, OBV, A/D, MFI, VPT
        ├── options_flow.py          # Options chain analysis & sentiment
        ├── market_structure.py      # Trend, swing points, support/resistance
        └── patterns.py              # Chart & candlestick pattern recognition
```
