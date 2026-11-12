"""Malaysian business-day check (BNM follows Federal Territory of Kuala Lumpur holidays)."""

from __future__ import annotations

from datetime import date

import holidays

KL_SUBDIV = "14"  # WP Kuala Lumpur in the `holidays` package


def is_my_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in holidays.Malaysia(subdiv=KL_SUBDIV, years=d.year)
