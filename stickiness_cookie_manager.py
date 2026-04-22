import time
from typing import Any

from common.logging.core import logger


class _StickinessCookieManager:
    """Manages AWS stickiness cookies with expiration tracking."""

    def __init__(self) -> None:
        """Initialize the cookie manager."""
        self._cookie_data: dict[str, Any] | None = None
        self._timestamp: float | None = None
        self._max_age_seconds: int = 10

    def get_cookie(self) -> dict[str, Any] | None:
        """Retrieve the stickiness cookie if still fresh.

        Returns:
            Dictionary containing the stickiness cookie if available and fresh
            (less than 10 seconds old), otherwise None.
        """
        if self._cookie_data is not None and self._timestamp is not None:
            age_seconds = time.time() - self._timestamp

            # Check if cookie is still fresh
            if age_seconds <= self._max_age_seconds:
                logger.debug(
                    "Returning cached stickiness cookie",
                    extra={"cookie_age_seconds": age_seconds},
                )
                return self._cookie_data

            # Cookie is stale, clear it
            logger.debug(
                "Stickiness cookie expired, clearing cache",
                extra={"cookie_age_seconds": age_seconds},
            )
            self._clear_cookie()

        return None

    def set_cookie(self, cookies: dict[str, Any]) -> None:
        """Set the stickiness cookie.

        Args:
            cookies: Cookies to set as the stickiness cookie.
        """
        self._cookie_data = cookies
        self._timestamp = time.time()
        logger.debug(
            "Stickiness cookie set",
            extra={"cookie_count": len(cookies), "timestamp": self._timestamp},
        )

    def _clear_cookie(self) -> None:
        """Clear the stored cookie data."""
        self._cookie_data = None
        self._timestamp = None


# Singleton instance
cookie_manager = _StickinessCookieManager()
