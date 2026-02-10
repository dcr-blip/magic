"""Market data fetching — historical OHLCV and options chains."""

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
        The DataFrame's attrs["symbol"] is set for downstream use.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, interval=interval)
    if df.empty:
        raise ValueError(f"No data returned for {symbol} from {start} to {end}")
    # Normalize column names
    df.columns = [c.strip().title() for c in df.columns]
    # Keep only OHLCV columns
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep]
    df.attrs["symbol"] = symbol
    return df


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


def fetch_options_chain(symbol: str, max_expiries: int = 4) -> dict:
    """Fetch options chain data for a symbol.

    Returns:
        Dict with keys: expiries, calls, puts (list of DataFrames per expiry).
    """
    ticker = yf.Ticker(symbol)
    try:
        expiries = list(ticker.options[:max_expiries])
    except Exception:
        return {"expiries": [], "calls": [], "puts": []}

    calls_list = []
    puts_list = []
    for expiry in expiries:
        try:
            chain = ticker.option_chain(expiry)
            chain.calls["expiry"] = expiry
            chain.puts["expiry"] = expiry
            calls_list.append(chain.calls)
            puts_list.append(chain.puts)
        except Exception:
            continue

    return {
        "expiries": expiries,
        "calls": calls_list,
        "puts": puts_list,
    }


def get_current_price(symbol: str) -> float:
    """Get the most recent closing price for a symbol."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1d")
    if hist.empty:
        raise ValueError(f"No current price data for {symbol}")
    return float(hist["Close"].iloc[-1])
