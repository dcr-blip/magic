"""Technical indicators computed on OHLCV DataFrames.

All functions accept a DataFrame with at minimum Close (and Volume where
noted) and return a new DataFrame with the indicator columns appended.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def add_sma_pair(df: pd.DataFrame, short: int = 50, long: int = 200) -> pd.DataFrame:
    """Add SMA-short and SMA-long columns plus a cross signal column.

    Adds:
        sma_{short}, sma_{long}, sma_cross (+1 golden cross, -1 death cross, 0 none)
    """
    out = df.copy()
    out[f"sma_{short}"] = sma(out["Close"], short)
    out[f"sma_{long}"] = sma(out["Close"], long)
    short_col = out[f"sma_{short}"]
    long_col = out[f"sma_{long}"]
    above = (short_col > long_col).astype(int)
    out["sma_cross"] = above.diff().fillna(0).astype(int)  # +1 golden, -1 death
    return out


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using exponential moving average of gains/losses."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add RSI column."""
    out = df.copy()
    out["rsi"] = compute_rsi(out["Close"], period)
    return out


# ---------------------------------------------------------------------------
# VWAP (Volume Weighted Average Price)
# ---------------------------------------------------------------------------

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add intraday-style VWAP (cumulative reset not applied — rolling daily)."""
    out = df.copy()
    typical = (out["High"] + out["Low"] + out["Close"]) / 3
    out["vwap"] = (typical * out["Volume"]).cumsum() / out["Volume"].cumsum()
    return out


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Add MACD line, signal line, and histogram."""
    out = df.copy()
    ema_fast = ema(out["Close"], fast)
    ema_slow = ema(out["Close"], slow)
    out["macd"] = ema_fast - ema_slow
    out["macd_signal"] = ema(out["macd"], signal)
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    return out


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Add Bollinger Bands (upper, mid, lower) and %B."""
    out = df.copy()
    out["bb_mid"] = sma(out["Close"], period)
    std = out["Close"].rolling(window=period).std()
    out["bb_upper"] = out["bb_mid"] + std_dev * std
    out["bb_lower"] = out["bb_mid"] - std_dev * std
    band_width = out["bb_upper"] - out["bb_lower"]
    out["bb_pct_b"] = np.where(band_width != 0, (out["Close"] - out["bb_lower"]) / band_width, 0.5)
    return out


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add Average True Range."""
    out = df.copy()
    high_low = out["High"] - out["Low"]
    high_close = (out["High"] - out["Close"].shift()).abs()
    low_close = (out["Low"] - out["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    out["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()
    return out


# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------

def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Add Stochastic %K and %D."""
    out = df.copy()
    low_min = out["Low"].rolling(window=k_period).min()
    high_max = out["High"].rolling(window=k_period).max()
    denom = high_max - low_min
    out["stoch_k"] = np.where(denom != 0, 100 * (out["Close"] - low_min) / denom, 50)
    out["stoch_d"] = pd.Series(out["stoch_k"]).rolling(window=d_period).mean()
    return out


# ---------------------------------------------------------------------------
# Convenience: add all indicators at once
# ---------------------------------------------------------------------------

def add_all_indicators(
    df: pd.DataFrame,
    sma_short: int = 50,
    sma_long: int = 200,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_std: float = 2.0,
    atr_period: int = 14,
    stoch_k: int = 14,
    stoch_d: int = 3,
) -> pd.DataFrame:
    """Compute all technical indicators and return enriched DataFrame."""
    out = df.copy()
    out = add_sma_pair(out, sma_short, sma_long)
    out = add_rsi(out, rsi_period)
    out = add_vwap(out)
    out = add_macd(out, macd_fast, macd_slow, macd_signal)
    out = add_bollinger(out, bb_period, bb_std)
    out = add_atr(out, atr_period)
    out = add_stochastic(out, stoch_k, stoch_d)
    return out
