"""Base strategy interface."""

from abc import ABC, abstractmethod

import pandas as pd

from trading.core.models import Signal


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Analyze price data and produce trading signals.

        Args:
            data: DataFrame with at least Open, High, Low, Close, Volume columns.
                  Index should be a DatetimeIndex.

        Returns:
            List of Signal objects.
        """
