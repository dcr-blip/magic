"""Market data fetching and caching."""

import pandas as pd
import yfinance as yf


def fetch_ohlcv(symbol: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV data for a symbol using yfinance.

    Args:
        symbol: Ticker symbol (e.g. "AAPL").
        start: Start date string "YYYY-MM-DD".
        end: End date string "YYYY-MM-DD".
        interval: Data interval (1d, 1h, 5m, etc.).

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, interval=interval)
    if df.empty:
        raise ValueError(f"No data returned for {symbol} from {start} to {end}")
    # Normalize column names
    df.columns = [c.strip().title() for c in df.columns]
    # Keep only OHLCV columns
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[keep]


def fetch_multiple(symbols: list[str], start: str, end: str, interval: str = "1d") -> dict[str, pd.DataFrame]:
    """Fetch OHLCV data for multiple symbols.

    Returns:
        Dict mapping symbol -> DataFrame.
    """
    data = {}
    for symbol in symbols:
        try:
            data[symbol] = fetch_ohlcv(symbol, start, end, interval)
        except ValueError as e:
            print(f"Warning: {e}")
    return data
