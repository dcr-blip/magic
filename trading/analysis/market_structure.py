"""Market structure analysis — trend, support/resistance, swing points."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import numpy as np
import pandas as pd


class Trend(Enum):
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    SIDEWAYS = "sideways"
    DOWNTREND = "downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


class SwingType(Enum):
    HIGHER_HIGH = "HH"
    HIGHER_LOW = "HL"
    LOWER_HIGH = "LH"
    LOWER_LOW = "LL"


@dataclass
class SwingPoint:
    timestamp: datetime
    price: float
    swing_type: SwingType


@dataclass
class Level:
    """A support or resistance price level."""
    price: float
    strength: int     # how many times tested
    level_type: str   # "support" or "resistance"
    first_seen: datetime
    last_tested: datetime


@dataclass
class StructureAnalysis:
    """Full market structure breakdown for a symbol."""
    trend: Trend
    swing_points: list[SwingPoint]
    support_levels: list[Level]
    resistance_levels: list[Level]
    trend_strength: float           # 0-1
    price_vs_structure: str         # e.g. "above all support, near resistance"
    summary_text: str

    def summary(self) -> str:
        lines = [
            f"--- Market Structure ---",
            f"  Trend: {self.trend.value}  (strength {self.trend_strength:.0%})",
            f"  {self.price_vs_structure}",
        ]
        if self.support_levels:
            sup = ", ".join(f"${l.price:.2f}(x{l.strength})" for l in self.support_levels[:5])
            lines.append(f"  Support:    {sup}")
        if self.resistance_levels:
            res = ", ".join(f"${l.price:.2f}(x{l.strength})" for l in self.resistance_levels[:5])
            lines.append(f"  Resistance: {res}")
        if self.swing_points:
            recent = self.swing_points[-6:]
            swings = " → ".join(f"{s.swing_type.value}({s.price:.2f})" for s in recent)
            lines.append(f"  Swings: {swings}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Swing point detection
# ---------------------------------------------------------------------------

def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> list[SwingPoint]:
    """Identify local highs and lows (swing points).

    A swing high is a bar whose High is higher than the `lookback` bars on each side.
    A swing low is a bar whose Low is lower than the `lookback` bars on each side.
    """
    highs = df["High"].values
    lows = df["Low"].values
    timestamps = df.index
    n = len(df)

    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(lookback, n - lookback):
        # Swing high
        is_high = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_high = False
                break
        if is_high:
            swing_highs.append((i, highs[i]))

        # Swing low
        is_low = True
        for j in range(1, lookback + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_low = False
                break
        if is_low:
            swing_lows.append((i, lows[i]))

    # Classify as HH/LH and HL/LL
    points: list[SwingPoint] = []

    prev_high = None
    for idx, price in swing_highs:
        if prev_high is None:
            st = SwingType.HIGHER_HIGH
        elif price > prev_high:
            st = SwingType.HIGHER_HIGH
        else:
            st = SwingType.LOWER_HIGH
        points.append(SwingPoint(timestamps[idx], price, st))
        prev_high = price

    prev_low = None
    for idx, price in swing_lows:
        if prev_low is None:
            st = SwingType.HIGHER_LOW
        elif price > prev_low:
            st = SwingType.HIGHER_LOW
        else:
            st = SwingType.LOWER_LOW
        points.append(SwingPoint(timestamps[idx], price, st))
        prev_low = price

    points.sort(key=lambda p: p.timestamp)
    return points


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

def find_support_resistance(
    df: pd.DataFrame,
    swing_lookback: int = 5,
    cluster_pct: float = 0.015,
) -> tuple[list[Level], list[Level]]:
    """Find support and resistance levels by clustering swing points.

    Swing lows within `cluster_pct` of each other form support; swing highs form resistance.
    """
    highs = df["High"].values
    lows = df["Low"].values
    timestamps = df.index
    n = len(df)

    raw_highs: list[tuple[datetime, float]] = []
    raw_lows: list[tuple[datetime, float]] = []

    for i in range(swing_lookback, n - swing_lookback):
        is_high = all(highs[i] > highs[i - j] and highs[i] > highs[i + j]
                       for j in range(1, swing_lookback + 1))
        if is_high:
            raw_highs.append((timestamps[i], highs[i]))

        is_low = all(lows[i] < lows[i - j] and lows[i] < lows[i + j]
                      for j in range(1, swing_lookback + 1))
        if is_low:
            raw_lows.append((timestamps[i], lows[i]))

    supports = _cluster_levels(raw_lows, cluster_pct, "support")
    resistances = _cluster_levels(raw_highs, cluster_pct, "resistance")

    # Sort by strength descending
    supports.sort(key=lambda l: l.strength, reverse=True)
    resistances.sort(key=lambda l: l.strength, reverse=True)

    return supports, resistances


def _cluster_levels(
    points: list[tuple[datetime, float]],
    cluster_pct: float,
    level_type: str,
) -> list[Level]:
    """Group nearby price points into levels."""
    if not points:
        return []

    sorted_pts = sorted(points, key=lambda p: p[1])
    levels: list[Level] = []
    used = set()

    for i, (ts_i, price_i) in enumerate(sorted_pts):
        if i in used:
            continue
        cluster_prices = [price_i]
        cluster_times = [ts_i]
        used.add(i)

        for j in range(i + 1, len(sorted_pts)):
            if j in used:
                continue
            ts_j, price_j = sorted_pts[j]
            if abs(price_j - price_i) / price_i <= cluster_pct:
                cluster_prices.append(price_j)
                cluster_times.append(ts_j)
                used.add(j)
            else:
                break  # sorted, so no more nearby

        levels.append(Level(
            price=float(np.mean(cluster_prices)),
            strength=len(cluster_prices),
            level_type=level_type,
            first_seen=min(cluster_times),
            last_tested=max(cluster_times),
        ))

    return levels


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def detect_trend(df: pd.DataFrame, sma_short: int = 50, sma_long: int = 200) -> tuple[Trend, float]:
    """Determine trend using SMA alignment and price position.

    Returns:
        (Trend enum, strength 0-1).
    """
    if len(df) < sma_long:
        return Trend.SIDEWAYS, 0.0

    close = df["Close"]
    sma_s = close.rolling(sma_short).mean()
    sma_l = close.rolling(sma_long).mean()

    last_close = close.iloc[-1]
    last_sma_s = sma_s.iloc[-1]
    last_sma_l = sma_l.iloc[-1]

    if np.isnan(last_sma_s) or np.isnan(last_sma_l):
        return Trend.SIDEWAYS, 0.0

    score = 0.0

    # Price above/below SMAs
    if last_close > last_sma_s:
        score += 0.25
    else:
        score -= 0.25
    if last_close > last_sma_l:
        score += 0.25
    else:
        score -= 0.25

    # SMA alignment
    if last_sma_s > last_sma_l:
        score += 0.25
    else:
        score -= 0.25

    # SMA slope (last 10 bars)
    if len(sma_s.dropna()) >= 10:
        slope = (sma_s.iloc[-1] - sma_s.iloc[-10]) / sma_s.iloc[-10]
        score += np.clip(slope * 10, -0.25, 0.25)

    # Map score to trend
    if score >= 0.75:
        trend = Trend.STRONG_UPTREND
    elif score >= 0.25:
        trend = Trend.UPTREND
    elif score <= -0.75:
        trend = Trend.STRONG_DOWNTREND
    elif score <= -0.25:
        trend = Trend.DOWNTREND
    else:
        trend = Trend.SIDEWAYS

    strength = min(1.0, abs(score))
    return trend, strength


# ---------------------------------------------------------------------------
# Full structure analysis
# ---------------------------------------------------------------------------

def analyze_structure(
    df: pd.DataFrame,
    swing_lookback: int = 5,
    cluster_pct: float = 0.015,
    sma_short: int = 50,
    sma_long: int = 200,
) -> StructureAnalysis:
    """Run full market structure analysis."""
    trend, strength = detect_trend(df, sma_short, sma_long)
    swings = find_swing_points(df, swing_lookback)
    supports, resistances = find_support_resistance(df, swing_lookback, cluster_pct)

    last_price = df["Close"].iloc[-1]

    # Describe price vs structure
    near_sup = [s for s in supports if abs(last_price - s.price) / last_price < 0.02]
    near_res = [r for r in resistances if abs(last_price - r.price) / last_price < 0.02]
    above_sup = [s for s in supports if last_price > s.price]
    below_res = [r for r in resistances if last_price < r.price]

    parts = []
    if near_sup:
        parts.append(f"Testing support at ${near_sup[0].price:.2f}")
    elif above_sup:
        parts.append(f"Above {len(above_sup)} support level(s)")
    if near_res:
        parts.append(f"Testing resistance at ${near_res[0].price:.2f}")
    elif below_res:
        parts.append(f"Below {len(below_res)} resistance level(s)")
    price_desc = "; ".join(parts) if parts else "No clear S/R nearby"

    # Build summary
    summary_parts = [f"Trend: {trend.value} ({strength:.0%})"]
    if swings:
        recent = [s.swing_type.value for s in swings[-4:]]
        summary_parts.append(f"Recent swings: {' → '.join(recent)}")
    summary_parts.append(price_desc)

    return StructureAnalysis(
        trend=trend,
        swing_points=swings,
        support_levels=supports,
        resistance_levels=resistances,
        trend_strength=strength,
        price_vs_structure=price_desc,
        summary_text="; ".join(summary_parts),
    )
