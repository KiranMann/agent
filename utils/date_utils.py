"""Date utilities for production and testing environments."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from common.configs.app_config_settings import AppConfig


def _get_current_date() -> datetime:
    """Get current date, handling both production and test environments.

    In test mode (MOCK_API_FLAG=true), returns the seed date from EVAL_SEED_DATE.
    In production, returns the actual current datetime.

    Returns:
        datetime: Current date or seed date for testing
    """
    if AppConfig.MOCK_API_FLAG is True:
        seed_date = os.getenv("EVAL_SEED_DATE")
        if not seed_date:
            raise ValueError("EVAL_SEED_DATE must be set when MOCK_API_FLAG is true")
        return datetime.strptime(seed_date, "%Y-%m-%d")

    return datetime.now()


def _get_current_date_string() -> str:
    """Get current date string using inject_date with empty prompt.

    Returns:
        str: Current date string in the format used by inject_date
    """
    # Use inject_date with empty string to get just the date portion
    date_injected = inject_date("")
    # Extract just the date part (everything after the newline)
    return date_injected.strip()


def inject_date(prompt: str) -> str:
    """Given a prompt, add the current date and timezone to be used in responses.

    Note: This injects the eval date when MOCK_API_FLAG is True
    """
    date = _get_current_date()
    now = datetime.combine(
        date.date(),
        datetime.min.time(),
        tzinfo=ZoneInfo("Australia/Sydney"),
    )

    contextual_prompt = prompt + now.strftime("\nToday's date and timezone: %B %d, %Y in %Z(%z)\n")
    return contextual_prompt


def get_formatted_date() -> str:
    """Get the formatted date string used in prompt injection.

    Returns the date in the same format as inject_date(): "January 29, 2026 in AEDT(+1100)"
    Note: Returns the eval date when MOCK_API_FLAG is True
    """
    date = _get_current_date()
    now = datetime.combine(
        date.date(),
        datetime.min.time(),
        tzinfo=ZoneInfo("Australia/Sydney"),
    )
    return now.strftime("%B %d, %Y in %Z(%z)")
