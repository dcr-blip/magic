"""Options flow analysis — put/call ratios and unusual activity detection.

Uses yfinance options chain data to gauge institutional sentiment.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class OptionsSnapshot:
    """Aggregated options metrics for a single expiry scan."""
    symbol: str
    scan_date: datetime
    total_call_volume: int
    total_put_volume: int
    total_call_oi: int
    total_put_oi: int
    put_call_volume_ratio: float
    put_call_oi_ratio: float
    max_pain: float
    highest_call_oi_strike: float
    highest_put_oi_strike: float
    unusual_activity: list["UnusualOption"]

    def summary(self) -> str:
        lines = [
            f"--- Options Flow: {self.symbol} ({self.scan_date:%Y-%m-%d}) ---",
            f"  Call Volume: {self.total_call_volume:,}  |  Put Volume: {self.total_put_volume:,}",
            f"  Call OI:     {self.total_call_oi:,}  |  Put OI:     {self.total_put_oi:,}",
            f"  P/C Vol Ratio:  {self.put_call_volume_ratio:.2f}",
            f"  P/C OI Ratio:   {self.put_call_oi_ratio:.2f}",
            f"  Max Pain:       ${self.max_pain:.2f}",
            f"  Top Call OI Strike: ${self.highest_call_oi_strike:.2f}",
            f"  Top Put OI Strike:  ${self.highest_put_oi_strike:.2f}",
        ]
        if self.unusual_activity:
            lines.append(f"  Unusual Activity ({len(self.unusual_activity)} contracts):")
            for ua in self.unusual_activity[:10]:
                lines.append(f"    {ua}")
        return "\n".join(lines)


@dataclass
class UnusualOption:
    """A single option contract with volume >> open interest."""
    contract_type: str   # "call" or "put"
    strike: float
    expiry: str
    volume: int
    open_interest: int
    vol_oi_ratio: float
    implied_volatility: float

    def __str__(self):
        return (f"{self.contract_type.upper()} ${self.strike:.0f} "
                f"exp={self.expiry} vol={self.volume:,} oi={self.open_interest:,} "
                f"vol/oi={self.vol_oi_ratio:.1f}x iv={self.implied_volatility:.0%}")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def fetch_options_snapshot(
    symbol: str,
    vol_oi_threshold: float = 3.0,
    min_volume: int = 100,
    max_expiries: int = 4,
) -> OptionsSnapshot | None:
    """Fetch and analyze current options chain for a symbol.

    Args:
        symbol: Ticker symbol.
        vol_oi_threshold: Volume/OI ratio to flag as unusual.
        min_volume: Minimum volume to consider a contract.
        max_expiries: How many near-term expiries to scan.

    Returns:
        OptionsSnapshot or None if options data is unavailable.
    """
    ticker = yf.Ticker(symbol)
    try:
        expiries = ticker.options
    except Exception:
        return None

    if not expiries:
        return None

    expiries = expiries[:max_expiries]

    all_calls = []
    all_puts = []
    unusual: list[UnusualOption] = []

    for expiry in expiries:
        try:
            chain = ticker.option_chain(expiry)
        except Exception:
            continue

        calls = chain.calls
        puts = chain.puts

        if not calls.empty:
            all_calls.append(calls)
            _find_unusual(calls, "call", expiry, vol_oi_threshold, min_volume, unusual)

        if not puts.empty:
            all_puts.append(puts)
            _find_unusual(puts, "put", expiry, vol_oi_threshold, min_volume, unusual)

    if not all_calls and not all_puts:
        return None

    calls_df = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
    puts_df = pd.concat(all_puts, ignore_index=True) if all_puts else pd.DataFrame()

    total_call_vol = int(calls_df["volume"].sum()) if not calls_df.empty else 0
    total_put_vol = int(puts_df["volume"].sum()) if not puts_df.empty else 0
    total_call_oi = int(calls_df["openInterest"].sum()) if not calls_df.empty else 0
    total_put_oi = int(puts_df["openInterest"].sum()) if not puts_df.empty else 0

    pc_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 0.0
    pc_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 0.0

    max_pain = _compute_max_pain(calls_df, puts_df)

    highest_call_strike = 0.0
    if not calls_df.empty:
        highest_call_strike = float(calls_df.loc[calls_df["openInterest"].idxmax(), "strike"])
    highest_put_strike = 0.0
    if not puts_df.empty:
        highest_put_strike = float(puts_df.loc[puts_df["openInterest"].idxmax(), "strike"])

    # Sort unusual by vol/oi descending
    unusual.sort(key=lambda u: u.vol_oi_ratio, reverse=True)

    return OptionsSnapshot(
        symbol=symbol,
        scan_date=datetime.now(),
        total_call_volume=total_call_vol,
        total_put_volume=total_put_vol,
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        put_call_volume_ratio=pc_vol,
        put_call_oi_ratio=pc_oi,
        max_pain=max_pain,
        highest_call_oi_strike=highest_call_strike,
        highest_put_oi_strike=highest_put_strike,
        unusual_activity=unusual,
    )


def _find_unusual(
    contracts: pd.DataFrame,
    contract_type: str,
    expiry: str,
    threshold: float,
    min_vol: int,
    result: list[UnusualOption],
):
    """Scan a set of contracts for unusual volume/OI ratios."""
    for _, row in contracts.iterrows():
        vol = int(row.get("volume", 0) or 0)
        oi = int(row.get("openInterest", 0) or 0)
        if vol < min_vol:
            continue
        ratio = vol / oi if oi > 0 else vol  # if OI is 0, any volume is unusual
        if ratio >= threshold:
            result.append(UnusualOption(
                contract_type=contract_type,
                strike=float(row["strike"]),
                expiry=expiry,
                volume=vol,
                open_interest=oi,
                vol_oi_ratio=ratio,
                implied_volatility=float(row.get("impliedVolatility", 0) or 0),
            ))


def _compute_max_pain(calls_df: pd.DataFrame, puts_df: pd.DataFrame) -> float:
    """Compute max-pain strike — the price at which option holders lose the most.

    For each candidate strike, compute the total intrinsic value that would be
    paid out to all option holders if the underlying expired at that strike.
    Max pain is the strike that minimizes total payout.
    """
    if calls_df.empty and puts_df.empty:
        return 0.0

    strikes = set()
    if not calls_df.empty:
        strikes.update(calls_df["strike"].unique())
    if not puts_df.empty:
        strikes.update(puts_df["strike"].unique())

    if not strikes:
        return 0.0

    min_pain = float("inf")
    max_pain_strike = 0.0

    for candidate in sorted(strikes):
        call_pain = 0.0
        if not calls_df.empty:
            itm = calls_df[calls_df["strike"] < candidate]
            if not itm.empty:
                call_pain = ((candidate - itm["strike"]) * itm["openInterest"]).sum()

        put_pain = 0.0
        if not puts_df.empty:
            itm = puts_df[puts_df["strike"] > candidate]
            if not itm.empty:
                put_pain = ((itm["strike"] - candidate) * itm["openInterest"]).sum()

        total = call_pain + put_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = candidate

    return float(max_pain_strike)


# ---------------------------------------------------------------------------
# Sentiment scoring
# ---------------------------------------------------------------------------

def options_sentiment_score(snapshot: OptionsSnapshot | None) -> tuple[float, str]:
    """Convert an options snapshot into a sentiment score.

    Returns:
        (score, reasoning) where score is -1.0 (very bearish) to +1.0 (very bullish).
    """
    if snapshot is None:
        return 0.0, "No options data available"

    reasons = []
    score = 0.0

    # Put/Call volume ratio
    pcr = snapshot.put_call_volume_ratio
    if pcr < 0.5:
        score += 0.3
        reasons.append(f"Low P/C ratio ({pcr:.2f}) — bullish sentiment")
    elif pcr > 1.0:
        score -= 0.3
        reasons.append(f"High P/C ratio ({pcr:.2f}) — bearish sentiment")
    elif pcr > 1.5:
        # Extreme fear can be contrarian bullish
        score += 0.1
        reasons.append(f"Extreme P/C ratio ({pcr:.2f}) — contrarian bullish")

    # Unusual call vs put activity
    unusual_calls = [u for u in snapshot.unusual_activity if u.contract_type == "call"]
    unusual_puts = [u for u in snapshot.unusual_activity if u.contract_type == "put"]
    if len(unusual_calls) > len(unusual_puts) * 2:
        score += 0.3
        reasons.append(f"Heavy unusual call activity ({len(unusual_calls)} calls vs {len(unusual_puts)} puts)")
    elif len(unusual_puts) > len(unusual_calls) * 2:
        score -= 0.3
        reasons.append(f"Heavy unusual put activity ({len(unusual_puts)} puts vs {len(unusual_calls)} calls)")

    # Clamp
    score = max(-1.0, min(1.0, score))

    if not reasons:
        reasons.append("Neutral options flow")

    return score, "; ".join(reasons)
