"""Relative Strength Index (RSI) strategy."""

import pandas as pd

from trading.core.models import Side, Signal
from trading.strategies.base import Strategy


class RSIStrategy(Strategy):
    """Buy when RSI drops below the oversold threshold, sell when it rises above overbought.

    Parameters:
        period: RSI calculation period.
        overbought: Threshold above which the asset is considered overbought.
        oversold: Threshold below which the asset is considered oversold.
    """

    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

    @property
    def name(self) -> str:
        return f"RSI ({self.period}, {self.oversold}/{self.overbought})"

    @staticmethod
    def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        df = data.copy()
        df["rsi"] = self._compute_rsi(df["Close"], self.period)
        df.dropna(inplace=True)

        signals: list[Signal] = []
        prev_rsi = None

        for timestamp, row in df.iterrows():
            rsi = row["rsi"]

            if prev_rsi is not None:
                # Crossed below oversold -> buy signal
                if prev_rsi >= self.oversold and rsi < self.oversold:
                    signals.append(Signal(
                        symbol="",
                        side=Side.BUY,
                        strength=min(1.0, (self.oversold - rsi) / self.oversold),
                        timestamp=timestamp,
                        reason=f"RSI dropped below oversold ({rsi:.1f} < {self.oversold})",
                    ))
                # Crossed above overbought -> sell signal
                elif prev_rsi <= self.overbought and rsi > self.overbought:
                    signals.append(Signal(
                        symbol="",
                        side=Side.SELL,
                        strength=min(1.0, (rsi - self.overbought) / (100 - self.overbought)),
                        timestamp=timestamp,
                        reason=f"RSI rose above overbought ({rsi:.1f} > {self.overbought})",
                    ))

            prev_rsi = rsi

        return signals
