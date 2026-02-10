"""Chart pattern recognition on OHLCV data.

Detects common price patterns by analyzing swing point sequences and
geometric relationships between highs and lows.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import numpy as np
import pandas as pd

from trading.analysis.market_structure import find_swing_points, SwingPoint, SwingType


class PatternType(Enum):
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    HAMMER = "hammer"
    SHOOTING_STAR = "shooting_star"


class PatternBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class PatternMatch:
    pattern: PatternType
    bias: PatternBias
    confidence: float      # 0-1
    start_time: datetime
    end_time: datetime
    description: str
    target_price: float | None = None

    def __str__(self):
        target = f" target=${self.target_price:.2f}" if self.target_price else ""
        return (f"{self.pattern.value} ({self.bias.value}, "
                f"{self.confidence:.0%}){target} — {self.description}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approx_equal(a: float, b: float, tolerance: float = 0.02) -> bool:
    """Check if two prices are approximately equal within tolerance %."""
    if a == 0:
        return False
    return abs(a - b) / a <= tolerance


def _get_swing_highs(swings: list[SwingPoint]) -> list[SwingPoint]:
    return [s for s in swings if s.swing_type in (SwingType.HIGHER_HIGH, SwingType.LOWER_HIGH)]


def _get_swing_lows(swings: list[SwingPoint]) -> list[SwingPoint]:
    return [s for s in swings if s.swing_type in (SwingType.HIGHER_LOW, SwingType.LOWER_LOW)]


# ---------------------------------------------------------------------------
# Multi-bar patterns (structural)
# ---------------------------------------------------------------------------

def detect_double_top(swings: list[SwingPoint], tolerance: float = 0.02) -> list[PatternMatch]:
    """Two roughly equal swing highs with a valley between them."""
    matches = []
    highs = _get_swing_highs(swings)

    for i in range(len(highs) - 1):
        h1, h2 = highs[i], highs[i + 1]
        if not _approx_equal(h1.price, h2.price, tolerance):
            continue
        # Find a low between them
        between = [s for s in swings
                   if h1.timestamp < s.timestamp < h2.timestamp
                   and s.swing_type in (SwingType.HIGHER_LOW, SwingType.LOWER_LOW)]
        if not between:
            continue
        neckline = min(s.price for s in between)
        height = h1.price - neckline
        target = neckline - height

        matches.append(PatternMatch(
            pattern=PatternType.DOUBLE_TOP,
            bias=PatternBias.BEARISH,
            confidence=0.7,
            start_time=h1.timestamp,
            end_time=h2.timestamp,
            description=f"Peaks at ${h1.price:.2f} & ${h2.price:.2f}, neckline ${neckline:.2f}",
            target_price=target,
        ))
    return matches


def detect_double_bottom(swings: list[SwingPoint], tolerance: float = 0.02) -> list[PatternMatch]:
    """Two roughly equal swing lows with a peak between them."""
    matches = []
    lows = _get_swing_lows(swings)

    for i in range(len(lows) - 1):
        l1, l2 = lows[i], lows[i + 1]
        if not _approx_equal(l1.price, l2.price, tolerance):
            continue
        between = [s for s in swings
                   if l1.timestamp < s.timestamp < l2.timestamp
                   and s.swing_type in (SwingType.HIGHER_HIGH, SwingType.LOWER_HIGH)]
        if not between:
            continue
        neckline = max(s.price for s in between)
        height = neckline - l1.price
        target = neckline + height

        matches.append(PatternMatch(
            pattern=PatternType.DOUBLE_BOTTOM,
            bias=PatternBias.BULLISH,
            confidence=0.7,
            start_time=l1.timestamp,
            end_time=l2.timestamp,
            description=f"Troughs at ${l1.price:.2f} & ${l2.price:.2f}, neckline ${neckline:.2f}",
            target_price=target,
        ))
    return matches


def detect_head_and_shoulders(swings: list[SwingPoint], tolerance: float = 0.02) -> list[PatternMatch]:
    """Three peaks where the middle one (head) is higher than the two shoulders."""
    matches = []
    highs = _get_swing_highs(swings)

    for i in range(len(highs) - 2):
        ls, head, rs = highs[i], highs[i + 1], highs[i + 2]
        if head.price <= ls.price or head.price <= rs.price:
            continue
        if not _approx_equal(ls.price, rs.price, tolerance * 2):
            continue

        # Neckline from lows between shoulders
        between_left = [s for s in swings
                        if ls.timestamp < s.timestamp < head.timestamp
                        and s.swing_type in (SwingType.HIGHER_LOW, SwingType.LOWER_LOW)]
        between_right = [s for s in swings
                         if head.timestamp < s.timestamp < rs.timestamp
                         and s.swing_type in (SwingType.HIGHER_LOW, SwingType.LOWER_LOW)]
        if not between_left or not between_right:
            continue

        neckline = (min(s.price for s in between_left) + min(s.price for s in between_right)) / 2
        height = head.price - neckline
        target = neckline - height

        matches.append(PatternMatch(
            pattern=PatternType.HEAD_AND_SHOULDERS,
            bias=PatternBias.BEARISH,
            confidence=0.75,
            start_time=ls.timestamp,
            end_time=rs.timestamp,
            description=(f"LS=${ls.price:.2f} Head=${head.price:.2f} RS=${rs.price:.2f}, "
                         f"neckline=${neckline:.2f}"),
            target_price=target,
        ))
    return matches


def detect_inverse_head_and_shoulders(swings: list[SwingPoint], tolerance: float = 0.02) -> list[PatternMatch]:
    """Three troughs where the middle one is lower than the two shoulders."""
    matches = []
    lows = _get_swing_lows(swings)

    for i in range(len(lows) - 2):
        ls, head, rs = lows[i], lows[i + 1], lows[i + 2]
        if head.price >= ls.price or head.price >= rs.price:
            continue
        if not _approx_equal(ls.price, rs.price, tolerance * 2):
            continue

        between_left = [s for s in swings
                        if ls.timestamp < s.timestamp < head.timestamp
                        and s.swing_type in (SwingType.HIGHER_HIGH, SwingType.LOWER_HIGH)]
        between_right = [s for s in swings
                         if head.timestamp < s.timestamp < rs.timestamp
                         and s.swing_type in (SwingType.HIGHER_HIGH, SwingType.LOWER_HIGH)]
        if not between_left or not between_right:
            continue

        neckline = (max(s.price for s in between_left) + max(s.price for s in between_right)) / 2
        height = neckline - head.price
        target = neckline + height

        matches.append(PatternMatch(
            pattern=PatternType.INVERSE_HEAD_AND_SHOULDERS,
            bias=PatternBias.BULLISH,
            confidence=0.75,
            start_time=ls.timestamp,
            end_time=rs.timestamp,
            description=(f"LS=${ls.price:.2f} Head=${head.price:.2f} RS=${rs.price:.2f}, "
                         f"neckline=${neckline:.2f}"),
            target_price=target,
        ))
    return matches


# ---------------------------------------------------------------------------
# Candlestick patterns (single/few bar)
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(df: pd.DataFrame) -> list[PatternMatch]:
    """Detect single and multi-candle patterns."""
    matches = []
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    ts = df.index

    for i in range(2, len(df)):
        body = abs(c[i] - o[i])
        full_range = h[i] - l[i]
        if full_range == 0:
            continue

        upper_shadow = h[i] - max(o[i], c[i])
        lower_shadow = min(o[i], c[i]) - l[i]

        # Hammer (bullish reversal)
        if (lower_shadow >= 2 * body and upper_shadow <= body * 0.3
                and c[i - 1] < o[i - 1]):  # prior bar bearish
            matches.append(PatternMatch(
                pattern=PatternType.HAMMER,
                bias=PatternBias.BULLISH,
                confidence=0.6,
                start_time=ts[i],
                end_time=ts[i],
                description=f"Hammer at ${c[i]:.2f} — long lower shadow after decline",
            ))

        # Shooting Star (bearish reversal)
        if (upper_shadow >= 2 * body and lower_shadow <= body * 0.3
                and c[i - 1] > o[i - 1]):  # prior bar bullish
            matches.append(PatternMatch(
                pattern=PatternType.SHOOTING_STAR,
                bias=PatternBias.BEARISH,
                confidence=0.6,
                start_time=ts[i],
                end_time=ts[i],
                description=f"Shooting star at ${c[i]:.2f} — long upper shadow after rally",
            ))

        # Bullish Engulfing
        if (c[i - 1] < o[i - 1] and c[i] > o[i]
                and o[i] <= c[i - 1] and c[i] >= o[i - 1]):
            matches.append(PatternMatch(
                pattern=PatternType.BULLISH_ENGULFING,
                bias=PatternBias.BULLISH,
                confidence=0.65,
                start_time=ts[i - 1],
                end_time=ts[i],
                description=f"Bullish engulfing at ${c[i]:.2f}",
            ))

        # Bearish Engulfing
        if (c[i - 1] > o[i - 1] and c[i] < o[i]
                and o[i] >= c[i - 1] and c[i] <= o[i - 1]):
            matches.append(PatternMatch(
                pattern=PatternType.BEARISH_ENGULFING,
                bias=PatternBias.BEARISH,
                confidence=0.65,
                start_time=ts[i - 1],
                end_time=ts[i],
                description=f"Bearish engulfing at ${c[i]:.2f}",
            ))

        # Morning Star (3-bar bullish reversal)
        if i >= 2:
            body_prev2 = abs(c[i - 2] - o[i - 2])
            body_prev1 = abs(c[i - 1] - o[i - 1])
            if (c[i - 2] < o[i - 2]           # bar1: bearish
                    and body_prev1 < body_prev2 * 0.3  # bar2: small body (star)
                    and c[i] > o[i]             # bar3: bullish
                    and c[i] > (o[i - 2] + c[i - 2]) / 2):  # closes above bar1 midpoint
                matches.append(PatternMatch(
                    pattern=PatternType.MORNING_STAR,
                    bias=PatternBias.BULLISH,
                    confidence=0.7,
                    start_time=ts[i - 2],
                    end_time=ts[i],
                    description=f"Morning star at ${c[i]:.2f}",
                ))

        # Evening Star (3-bar bearish reversal)
        if i >= 2:
            body_prev2 = abs(c[i - 2] - o[i - 2])
            body_prev1 = abs(c[i - 1] - o[i - 1])
            if (c[i - 2] > o[i - 2]
                    and body_prev1 < body_prev2 * 0.3
                    and c[i] < o[i]
                    and c[i] < (o[i - 2] + c[i - 2]) / 2):
                matches.append(PatternMatch(
                    pattern=PatternType.EVENING_STAR,
                    bias=PatternBias.BEARISH,
                    confidence=0.7,
                    start_time=ts[i - 2],
                    end_time=ts[i],
                    description=f"Evening star at ${c[i]:.2f}",
                ))

    return matches


# ---------------------------------------------------------------------------
# Flag patterns
# ---------------------------------------------------------------------------

def detect_flags(df: pd.DataFrame, pole_bars: int = 10, flag_bars: int = 15) -> list[PatternMatch]:
    """Detect bull and bear flags.

    A flag is a strong move (pole) followed by a gentle counter-trend consolidation.
    """
    matches = []
    close = df["Close"].values
    ts = df.index
    n = len(df)

    for i in range(pole_bars, n - flag_bars):
        # Pole: strong move over pole_bars
        pole_start_price = close[i - pole_bars]
        pole_end_price = close[i]
        pole_change = (pole_end_price - pole_start_price) / pole_start_price

        if abs(pole_change) < 0.05:
            continue  # need at least 5% move for a pole

        # Flag: consolidation over next flag_bars
        flag_slice = close[i:min(i + flag_bars, n)]
        if len(flag_slice) < 5:
            continue
        flag_change = (flag_slice[-1] - flag_slice[0]) / flag_slice[0]
        flag_volatility = np.std(np.diff(flag_slice) / flag_slice[:-1])

        # Flag should retrace less than 50% of pole and have low volatility
        if abs(flag_change) > abs(pole_change) * 0.5:
            continue
        if flag_volatility > abs(pole_change) / pole_bars * 2:
            continue

        end_idx = min(i + flag_bars - 1, n - 1)
        pole_height = abs(pole_end_price - pole_start_price)

        if pole_change > 0 and flag_change <= 0:
            target = flag_slice[-1] + pole_height
            matches.append(PatternMatch(
                pattern=PatternType.BULL_FLAG,
                bias=PatternBias.BULLISH,
                confidence=0.65,
                start_time=ts[i - pole_bars],
                end_time=ts[end_idx],
                description=f"Bull flag: pole +{pole_change:.1%}, flag retracing {flag_change:.1%}",
                target_price=target,
            ))
        elif pole_change < 0 and flag_change >= 0:
            target = flag_slice[-1] - pole_height
            matches.append(PatternMatch(
                pattern=PatternType.BEAR_FLAG,
                bias=PatternBias.BEARISH,
                confidence=0.65,
                start_time=ts[i - pole_bars],
                end_time=ts[end_idx],
                description=f"Bear flag: pole {pole_change:.1%}, flag retracing +{flag_change:.1%}",
                target_price=target,
            ))

    return matches


# ---------------------------------------------------------------------------
# Master scanner
# ---------------------------------------------------------------------------

def scan_all_patterns(df: pd.DataFrame, swing_lookback: int = 5) -> list[PatternMatch]:
    """Run all pattern detectors and return combined results."""
    swings = find_swing_points(df, swing_lookback)

    all_matches: list[PatternMatch] = []
    all_matches.extend(detect_double_top(swings))
    all_matches.extend(detect_double_bottom(swings))
    all_matches.extend(detect_head_and_shoulders(swings))
    all_matches.extend(detect_inverse_head_and_shoulders(swings))
    all_matches.extend(detect_candlestick_patterns(df))
    all_matches.extend(detect_flags(df))

    # Sort by time
    all_matches.sort(key=lambda m: m.end_time)
    return all_matches
