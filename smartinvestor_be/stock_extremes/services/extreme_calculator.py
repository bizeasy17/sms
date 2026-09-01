from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class StockExtremeAccumulator:
    daily_max_return: Decimal | None = None
    daily_min_return: Decimal | None = None
    weekly_max_return: Decimal | None = None
    weekly_min_return: Decimal | None = None
    monthly_max_return: Decimal | None = None
    monthly_min_return: Decimal | None = None
    max_runup: Decimal | None = None
    max_drawdown: Decimal | None = None
    source_start_date: date | None = None
    source_end_date: date | None = None
    _running_min: Decimal | None = None
    _running_max: Decimal | None = None

    def add_return(self, frequency, period_return):
        prefix = {"D": "daily", "W": "weekly", "M": "monthly"}[frequency]
        max_field = f"{prefix}_max_return"
        min_field = f"{prefix}_min_return"
        current_max = getattr(self, max_field)
        current_min = getattr(self, min_field)
        if current_max is None or period_return > current_max:
            setattr(self, max_field, period_return)
        if current_min is None or period_return < current_min:
            setattr(self, min_field, period_return)

    def add_daily_price(self, trade_date, price):
        if self.source_start_date is None or trade_date < self.source_start_date:
            self.source_start_date = trade_date
        if self.source_end_date is None or trade_date > self.source_end_date:
            self.source_end_date = trade_date

        if self._running_min is None or price < self._running_min:
            self._running_min = price
        if self._running_max is None or price > self._running_max:
            self._running_max = price

        runup = price / self._running_min - Decimal("1")
        drawdown = price / self._running_max - Decimal("1")
        if self.max_runup is None or runup > self.max_runup:
            self.max_runup = runup
        if self.max_drawdown is None or drawdown < self.max_drawdown:
            self.max_drawdown = drawdown
