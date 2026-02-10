"""Simple Moving Average crossover strategy."""

import pandas as pd

from trading.core.models import Side, Signal
from trading.strategies.base import Strategy


class SMACrossover(Strategy):
    """Buy when the short SMA crosses above the long SMA, sell on the reverse.

    Parameters:
        short_window: Lookback period for the fast moving average.
        long_window: Lookback period for the slow moving average.
    """

    def __init__(self, short_window: int = 20, long_window: int = 50):
        self.short_window = short_window
        self.long_window = long_window

    @property
    def name(self) -> str:
        return f"SMA Crossover ({self.short_window}/{self.long_window})"

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        df = data.copy()
        df["sma_short"] = df["Close"].rolling(window=self.short_window).mean()
        df["sma_long"] = df["Close"].rolling(window=self.long_window).mean()
        df.dropna(inplace=True)

        signals: list[Signal] = []
        prev_short = None
        prev_long = None

        for timestamp, row in df.iterrows():
            short_val = row["sma_short"]
            long_val = row["sma_long"]

            if prev_short is not None and prev_long is not None:
                # Golden cross: short crosses above long
                if prev_short <= prev_long and short_val > long_val:
                    signals.append(Signal(
                        symbol="",
                        side=Side.BUY,
                        strength=min(1.0, (short_val - long_val) / long_val * 100),
                        timestamp=timestamp,
                        reason=f"Golden cross: SMA{self.short_window} crossed above SMA{self.long_window}",
                    ))
                # Death cross: short crosses below long
                elif prev_short >= prev_long and short_val < long_val:
                    signals.append(Signal(
                        symbol="",
                        side=Side.SELL,
                        strength=min(1.0, (long_val - short_val) / long_val * 100),
                        timestamp=timestamp,
                        reason=f"Death cross: SMA{self.short_window} crossed below SMA{self.long_window}",
                    ))

            prev_short = short_val
            prev_long = long_val

        return signals
