"""Composite strategy — fuses signals from technical indicators, volume analysis,
market structure, pattern recognition, and options flow into a single score.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from trading.core.models import Side, Signal
from trading.strategies.base import Strategy
from trading.analysis.indicators import add_all_indicators
from trading.analysis.volume import (
    add_volume_analysis, detect_volume_spikes, compute_net_volume_flow,
)
from trading.analysis.market_structure import analyze_structure, Trend
from trading.analysis.patterns import scan_all_patterns, PatternBias
from trading.analysis.options_flow import (
    fetch_options_snapshot, options_sentiment_score,
)


class CompositeStrategy(Strategy):
    """Multi-factor strategy that scores each bar across all analysis modules.

    Signal weights (configurable):
        - Technical indicators (SMA cross, RSI, MACD, Bollinger): 30%
        - Volume analysis (flow, spikes, MFI): 20%
        - Market structure (trend, S/R proximity): 20%
        - Pattern recognition: 15%
        - Options flow: 15%

    A composite score > +threshold triggers BUY; < -threshold triggers SELL.
    """

    def __init__(
        self,
        # SMA
        sma_short: int = 50,
        sma_long: int = 200,
        # RSI
        rsi_period: int = 14,
        rsi_overbought: float = 70,
        rsi_oversold: float = 30,
        # Bollinger
        bb_period: int = 20,
        bb_std: float = 2.0,
        # Volume
        vol_spike_threshold: float = 2.0,
        vol_lookback: int = 20,
        mfi_period: int = 14,
        # Structure
        swing_lookback: int = 5,
        # Options
        use_options: bool = True,
        # Scoring
        signal_threshold: float = 0.35,
        # Weights
        weight_technical: float = 0.30,
        weight_volume: float = 0.20,
        weight_structure: float = 0.20,
        weight_patterns: float = 0.15,
        weight_options: float = 0.15,
    ):
        self.sma_short = sma_short
        self.sma_long = sma_long
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.vol_spike_threshold = vol_spike_threshold
        self.vol_lookback = vol_lookback
        self.mfi_period = mfi_period
        self.swing_lookback = swing_lookback
        self.use_options = use_options
        self.signal_threshold = signal_threshold
        self.w_tech = weight_technical
        self.w_vol = weight_volume
        self.w_struct = weight_structure
        self.w_pat = weight_patterns
        self.w_opt = weight_options

    @property
    def name(self) -> str:
        return "Composite Multi-Factor"

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        # --- Enrich data with indicators ---
        df = add_all_indicators(
            data,
            sma_short=self.sma_short,
            sma_long=self.sma_long,
            rsi_period=self.rsi_period,
            bb_period=self.bb_period,
            bb_std=self.bb_std,
        )
        df = add_volume_analysis(df, mfi_period=self.mfi_period, flow_period=self.vol_lookback)

        # --- Pre-compute analysis that doesn't vary per bar ---
        structure = analyze_structure(
            data,
            swing_lookback=self.swing_lookback,
            sma_short=self.sma_short,
            sma_long=self.sma_long,
        )
        patterns = scan_all_patterns(data, swing_lookback=self.swing_lookback)
        vol_alerts = detect_volume_spikes(data, lookback=self.vol_lookback,
                                          spike_threshold=self.vol_spike_threshold)

        # Options (fetched once — current snapshot used as static bias)
        options_score = 0.0
        options_reason = ""
        if self.use_options:
            # Options data is live; during backtest it won't change per-bar,
            # so we fetch once and use as a constant bias.
            try:
                snap = fetch_options_snapshot(data.attrs.get("symbol", ""))
                options_score, options_reason = options_sentiment_score(snap)
            except Exception:
                options_score, options_reason = 0.0, "Options unavailable"

        # Build quick-lookup sets for volume alerts and patterns
        vol_alert_map: dict[datetime, str] = {}
        for va in vol_alerts:
            vol_alert_map[va.timestamp] = va.alert_type

        # Patterns: map end_time -> list of patterns active on that date
        pattern_map: dict[datetime, list] = {}
        for p in patterns:
            pattern_map.setdefault(p.end_time, []).append(p)

        # --- Score each bar ---
        signals: list[Signal] = []
        df_clean = df.dropna(subset=[f"sma_{self.sma_short}", f"sma_{self.sma_long}", "rsi"])

        for timestamp, row in df_clean.iterrows():
            reasons = []

            # ===== TECHNICAL SCORE (-1 to +1) =====
            tech_score = 0.0

            # SMA cross
            sma_cross = row.get("sma_cross", 0)
            if sma_cross > 0:
                tech_score += 0.4
                reasons.append(f"SMA{self.sma_short}/{self.sma_long} golden cross")
            elif sma_cross < 0:
                tech_score -= 0.4
                reasons.append(f"SMA{self.sma_short}/{self.sma_long} death cross")

            # Price vs SMA
            close = row["Close"]
            sma_s = row[f"sma_{self.sma_short}"]
            sma_l = row[f"sma_{self.sma_long}"]
            if close > sma_s > sma_l:
                tech_score += 0.15
            elif close < sma_s < sma_l:
                tech_score -= 0.15

            # RSI
            rsi_val = row.get("rsi", 50)
            if rsi_val < self.rsi_oversold:
                tech_score += 0.25
                reasons.append(f"RSI oversold ({rsi_val:.0f})")
            elif rsi_val > self.rsi_overbought:
                tech_score -= 0.25
                reasons.append(f"RSI overbought ({rsi_val:.0f})")

            # MACD histogram
            macd_hist = row.get("macd_hist", 0)
            if macd_hist > 0:
                tech_score += 0.1
            elif macd_hist < 0:
                tech_score -= 0.1

            # Bollinger %B
            pct_b = row.get("bb_pct_b", 0.5)
            if pct_b < 0:
                tech_score += 0.15
                reasons.append("Below lower Bollinger Band")
            elif pct_b > 1:
                tech_score -= 0.15
                reasons.append("Above upper Bollinger Band")

            tech_score = np.clip(tech_score, -1.0, 1.0)

            # ===== VOLUME SCORE (-1 to +1) =====
            vol_score = 0.0

            # MFI
            mfi_val = row.get("mfi", 50)
            if mfi_val < 20:
                vol_score += 0.3
                reasons.append(f"MFI oversold ({mfi_val:.0f})")
            elif mfi_val > 80:
                vol_score -= 0.3
                reasons.append(f"MFI overbought ({mfi_val:.0f})")

            # Net flow ratio
            flow_ratio = row.get("flow_ratio", 0.5)
            if flow_ratio > 0.65:
                vol_score += 0.3
                reasons.append(f"Strong buying flow ({flow_ratio:.0%})")
            elif flow_ratio < 0.35:
                vol_score -= 0.3
                reasons.append(f"Strong selling flow ({flow_ratio:.0%})")

            # Volume spike
            alert_type = vol_alert_map.get(timestamp)
            if alert_type == "climax_buy":
                vol_score += 0.4
                reasons.append("Volume climax (buy)")
            elif alert_type == "climax_sell":
                vol_score -= 0.4
                reasons.append("Volume climax (sell)")

            vol_score = np.clip(vol_score, -1.0, 1.0)

            # ===== STRUCTURE SCORE (-1 to +1) =====
            struct_score = 0.0

            if structure.trend in (Trend.STRONG_UPTREND, Trend.UPTREND):
                struct_score += 0.4 * structure.trend_strength
            elif structure.trend in (Trend.STRONG_DOWNTREND, Trend.DOWNTREND):
                struct_score -= 0.4 * structure.trend_strength

            # Proximity to S/R
            for sup in structure.support_levels[:3]:
                if abs(close - sup.price) / close < 0.02:
                    struct_score += 0.3
                    reasons.append(f"Near support ${sup.price:.2f}")
                    break
            for res in structure.resistance_levels[:3]:
                if abs(close - res.price) / close < 0.02:
                    struct_score -= 0.3
                    reasons.append(f"Near resistance ${res.price:.2f}")
                    break

            struct_score = np.clip(struct_score, -1.0, 1.0)

            # ===== PATTERN SCORE (-1 to +1) =====
            pat_score = 0.0
            bar_patterns = pattern_map.get(timestamp, [])
            for p in bar_patterns:
                if p.bias == PatternBias.BULLISH:
                    pat_score += p.confidence * 0.5
                    reasons.append(str(p.pattern.value))
                elif p.bias == PatternBias.BEARISH:
                    pat_score -= p.confidence * 0.5
                    reasons.append(str(p.pattern.value))
            pat_score = np.clip(pat_score, -1.0, 1.0)

            # ===== OPTIONS SCORE (static) =====
            opt_score = options_score  # already -1 to +1
            if options_reason and abs(opt_score) > 0.1:
                reasons.append(options_reason)

            # ===== COMPOSITE SCORE =====
            composite = (
                self.w_tech * tech_score
                + self.w_vol * vol_score
                + self.w_struct * struct_score
                + self.w_pat * pat_score
                + self.w_opt * opt_score
            )

            if composite >= self.signal_threshold:
                signals.append(Signal(
                    symbol="",
                    side=Side.BUY,
                    strength=min(1.0, composite),
                    timestamp=timestamp,
                    reason=" | ".join(reasons) if reasons else "Composite bullish",
                ))
            elif composite <= -self.signal_threshold:
                signals.append(Signal(
                    symbol="",
                    side=Side.SELL,
                    strength=min(1.0, abs(composite)),
                    timestamp=timestamp,
                    reason=" | ".join(reasons) if reasons else "Composite bearish",
                ))

        return signals
