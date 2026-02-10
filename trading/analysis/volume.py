"""Volume analysis — flow, spikes, and accumulation/distribution."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class VolumeAlert:
    """A notable volume event."""
    timestamp: datetime
    alert_type: str   # "spike", "climax_buy", "climax_sell", "dry_up"
    magnitude: float   # how extreme (multiples of average)
    description: str


# ---------------------------------------------------------------------------
# On-Balance Volume (OBV)
# ---------------------------------------------------------------------------

def compute_obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — cumulative volume biased by price direction."""
    direction = np.sign(df["Close"].diff()).fillna(0)
    return (direction * df["Volume"]).cumsum()


# ---------------------------------------------------------------------------
# Accumulation / Distribution Line
# ---------------------------------------------------------------------------

def compute_ad_line(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution line (Chaikin)."""
    high_low = df["High"] - df["Low"]
    clv = np.where(high_low != 0,
                   ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / high_low,
                   0.0)
    return (pd.Series(clv, index=df.index) * df["Volume"]).cumsum()


# ---------------------------------------------------------------------------
# Money Flow Index (MFI)
# ---------------------------------------------------------------------------

def compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index — volume-weighted RSI."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    raw_mf = typical * df["Volume"]
    direction = typical.diff()
    pos_mf = raw_mf.where(direction > 0, 0.0).rolling(window=period).sum()
    neg_mf = raw_mf.where(direction <= 0, 0.0).rolling(window=period).sum()
    ratio = np.where(neg_mf != 0, pos_mf / neg_mf, 100.0)
    return pd.Series(100 - (100 / (1 + ratio)), index=df.index)


# ---------------------------------------------------------------------------
# Volume-Price Trend (VPT)
# ---------------------------------------------------------------------------

def compute_vpt(df: pd.DataFrame) -> pd.Series:
    """Volume-Price Trend — cumulative volume scaled by % price change."""
    pct = df["Close"].pct_change().fillna(0)
    return (pct * df["Volume"]).cumsum()


# ---------------------------------------------------------------------------
# Volume Spike Detection
# ---------------------------------------------------------------------------

def detect_volume_spikes(
    df: pd.DataFrame,
    lookback: int = 20,
    spike_threshold: float = 2.0,
    dry_up_threshold: float = 0.4,
) -> list[VolumeAlert]:
    """Detect unusual volume bars relative to rolling average.

    Args:
        df: OHLCV DataFrame.
        lookback: Rolling window for average volume.
        spike_threshold: Multiples above average to flag as spike.
        dry_up_threshold: Fraction below average to flag as volume dry-up.

    Returns:
        List of VolumeAlert objects.
    """
    avg_vol = df["Volume"].rolling(window=lookback).mean()
    alerts: list[VolumeAlert] = []

    for timestamp, row in df.iterrows():
        av = avg_vol.get(timestamp)
        if av is None or np.isnan(av) or av == 0:
            continue

        ratio = row["Volume"] / av
        price_change = row["Close"] - row["Open"]

        if ratio >= spike_threshold:
            if price_change > 0:
                alert_type = "climax_buy"
                desc = (f"Volume spike {ratio:.1f}x avg with price UP "
                        f"(${price_change:+.2f})")
            elif price_change < 0:
                alert_type = "climax_sell"
                desc = (f"Volume spike {ratio:.1f}x avg with price DOWN "
                        f"(${price_change:+.2f})")
            else:
                alert_type = "spike"
                desc = f"Volume spike {ratio:.1f}x avg, price unchanged"
            alerts.append(VolumeAlert(timestamp, alert_type, ratio, desc))

        elif ratio <= dry_up_threshold:
            alerts.append(VolumeAlert(
                timestamp, "dry_up", ratio,
                f"Volume dry-up at {ratio:.2f}x avg — potential breakout pending",
            ))

    return alerts


# ---------------------------------------------------------------------------
# Net Volume Flow
# ---------------------------------------------------------------------------

def compute_net_volume_flow(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Compute rolling net volume flow (buy vs sell pressure).

    Bars where Close > Open are counted as buying volume; the rest as selling.
    Returns DataFrame with columns: buy_vol, sell_vol, net_flow, flow_ratio.
    """
    out = df.copy()
    is_up = out["Close"] >= out["Open"]
    out["buy_vol"] = out["Volume"].where(is_up, 0.0).rolling(window=period).sum()
    out["sell_vol"] = out["Volume"].where(~is_up, 0.0).rolling(window=period).sum()
    out["net_flow"] = out["buy_vol"] - out["sell_vol"]
    total = out["buy_vol"] + out["sell_vol"]
    out["flow_ratio"] = np.where(total != 0, out["buy_vol"] / total, 0.5)
    return out[["buy_vol", "sell_vol", "net_flow", "flow_ratio"]]


# ---------------------------------------------------------------------------
# Convenience: add all volume columns
# ---------------------------------------------------------------------------

def add_volume_analysis(df: pd.DataFrame, mfi_period: int = 14, flow_period: int = 20) -> pd.DataFrame:
    """Add all volume-derived columns to the DataFrame."""
    out = df.copy()
    out["obv"] = compute_obv(out)
    out["ad_line"] = compute_ad_line(out)
    out["mfi"] = compute_mfi(out, mfi_period)
    out["vpt"] = compute_vpt(out)

    flow = compute_net_volume_flow(out, flow_period)
    for col in flow.columns:
        out[col] = flow[col]

    return out
