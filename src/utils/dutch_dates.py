"""
Dutch date formatting utilities.

Provides Dutch day/month names and helper functions for formatting dates
in Dutch locale. Used by scheduling services and voice agents.
"""
from datetime import datetime, timedelta


DUTCH_DAYS = {
    0: "maandag",
    1: "dinsdag",
    2: "woensdag",
    3: "donderdag",
    4: "vrijdag",
    5: "zaterdag",
    6: "zondag"
}

DUTCH_MONTHS = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december"
}


def get_dutch_date(date: datetime, include_time: bool = False) -> str:
    """
    Format a date in Dutch (e.g., 'maandag 2 februari 2026').

    Args:
        date: The datetime to format
        include_time: Whether to include time (e.g., '10:00')

    Returns:
        Dutch formatted date string
    """
    day_name = DUTCH_DAYS[date.weekday()]
    month_name = DUTCH_MONTHS[date.month]
    if include_time:
        return f"{day_name} {date.day} {month_name} {date.year}, {date.strftime('%H:%M')}"
    return f"{day_name} {date.day} {month_name}"


def get_next_business_days(start_date: datetime, num_days: int) -> list[datetime]:
    """
    Get the next N business days (Mon-Fri) from start_date.

    Args:
        start_date: The starting date (not included in result)
        num_days: Number of business days to return

    Returns:
        List of datetime objects representing business days
    """
    business_days = []
    current = start_date
    while len(business_days) < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            business_days.append(current)
    return business_days
