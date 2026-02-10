"""Bollinger Bands mean-reversion strategy."""

import pandas as pd

from trading.core.models import Side, Signal
from trading.strategies.base import Strategy


class BollingerBands(Strategy):
    """Buy when price touches the lower band, sell when it touches the upper band.

    Parameters:
        period: Lookback period for the moving average and standard deviation.
        std_dev: Number of standard deviations for the bands.
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period = period
        self.std_dev = std_dev

    @property
    def name(self) -> str:
        return f"Bollinger Bands ({self.period}, {self.std_dev}\u03c3)"

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        df = data.copy()
        df["mid"] = df["Close"].rolling(window=self.period).mean()
        df["std"] = df["Close"].rolling(window=self.period).std()
        df["upper"] = df["mid"] + self.std_dev * df["std"]
        df["lower"] = df["mid"] - self.std_dev * df["std"]
        df.dropna(inplace=True)

        signals: list[Signal] = []
        prev_close = None
        prev_lower = None
        prev_upper = None

        for timestamp, row in df.iterrows():
            close = row["Close"]
            lower = row["lower"]
            upper = row["upper"]

            if prev_close is not None:
                # Price crosses below lower band -> buy (mean reversion)
                if prev_close >= prev_lower and close < lower:
                    band_width = upper - lower
                    if band_width > 0:
                        strength = min(1.0, (lower - close) / band_width * 10)
                    else:
                        strength = 0.5
                    signals.append(Signal(
                        symbol="",
                        side=Side.BUY,
                        strength=strength,
                        timestamp=timestamp,
                        reason=f"Price ({close:.2f}) broke below lower Bollinger Band ({lower:.2f})",
                    ))
                # Price crosses above upper band -> sell
                elif prev_close <= prev_upper and close > upper:
                    band_width = upper - lower
                    if band_width > 0:
                        strength = min(1.0, (close - upper) / band_width * 10)
                    else:
                        strength = 0.5
                    signals.append(Signal(
                        symbol="",
                        side=Side.SELL,
                        strength=strength,
                        timestamp=timestamp,
                        reason=f"Price ({close:.2f}) broke above upper Bollinger Band ({upper:.2f})",
                    ))

            prev_close = close
            prev_lower = lower
            prev_upper = upper

        return signals
