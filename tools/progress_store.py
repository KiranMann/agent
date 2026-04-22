"""Progress Store Module for Agent Progress Updates.

This module provides an in-memory, thread-safe storage system for tracking
agent execution progress across different sessions. It's designed to be
lightweight and fast for real-time progress updates.
"""

# pylint: disable=unused-argument,broad-exception-caught

import atexit
import threading
import time
from dataclasses import dataclass

from common.configs.agent_config_settings import get_agent_config
from common.logging.core import logger


@dataclass
class ProgressUpdate:
    """Represents a single progress update for an agent session."""

    message: str
    timestamp: float
    step_type: str  # 'agent_start', 'tool_start', 'tool_end', 'agent_end'
    details: str | None = None
    agent_name: str | None = None
    tool_name: str | None = None


class ProgressStore:
    """Thread-safe in-memory store for agent progress updates.

    This store is designed for temporary progress tracking during agent
    execution. Progress data is automatically cleaned up after completion
    to prevent memory leaks.
    """

    def __init__(self) -> None:
        """Initialize the progress store with empty state and start cleanup thread."""
        self._store: dict[str, ProgressUpdate] = {}
        self._lock = threading.RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._cleanup_stop_event = threading.Event()
        self._start_cleanup_thread()

    def update_progress(
        self,
        session_id: str,
        message: str,
        step_type: str,
        details: str | None = None,
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        """Update progress for a specific session.

        Args:
            session_id: Unique identifier for the session
            message: User-friendly progress message
            step_type: Type of progress step (agent_start, tool_start, etc.)
            details: Optional additional details
            agent_name: Name of the agent (if applicable)
            tool_name: Name of the tool (if applicable)
        """
        with self._lock:
            self._store[session_id] = ProgressUpdate(
                message=message,
                timestamp=time.time(),
                step_type=step_type,
                details=details,
                agent_name=agent_name,
                tool_name=tool_name,
            )

    def get_progress(self, session_id: str) -> ProgressUpdate | None:
        """Get current progress for a session.

        Args:
            session_id: Unique identifier for the session
        Returns:
            ProgressUpdate object if found, None otherwise
        """
        with self._lock:
            return self._store.get(session_id)

    def clear_progress(self, session_id: str) -> bool:
        """Clear progress data for a session.

        Args:
            session_id: Unique identifier for the session
        Returns:
            True if session was found and cleared, False otherwise
        """
        with self._lock:
            return self._store.pop(session_id, None) is not None

    def get_all_sessions(self) -> list[str]:
        """Get list of all active session IDs.

        Returns:
            List of session IDs currently in the store
        """
        with self._lock:
            return list(self._store.keys())

    def cleanup_old_sessions(self, max_age_seconds: int | None = None) -> int:
        """Clean up sessions older than specified age.

        Args:
            max_age_seconds: Maximum age in seconds (default: from config)

        Returns:
            Number of sessions cleaned up
        """
        if max_age_seconds is None:
            config = get_agent_config()
            max_age_seconds = config.INTERIM_PROGRESS_STORE_MAX_AGE_SECONDS
        current_time = time.time()
        cleaned_count = 0

        with self._lock:
            expired_sessions = [
                session_id
                for session_id, progress in self._store.items()
                if current_time - progress.timestamp > max_age_seconds
            ]

            for session_id in expired_sessions:
                self._store.pop(session_id, None)
                cleaned_count += 1

        return cleaned_count

    def get_store_size(self) -> int:
        """Get the current number of sessions in the store.

        Returns:
            Number of active sessions
        """
        with self._lock:
            return len(self._store)

    def _start_cleanup_thread(self) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_worker, daemon=True, name="ProgressStoreCleanup"
            )
            self._cleanup_thread.start()

    def _cleanup_worker(self) -> None:
        """Background worker that periodically cleans up old sessions."""
        config = get_agent_config()
        max_age_seconds = config.INTERIM_PROGRESS_STORE_MAX_AGE_SECONDS
        cleanup_cycle_seconds = config.INTERIM_PROGRESS_STORE_CLEANUP_CYCLE_SECONDS

        while not self._cleanup_stop_event.is_set():
            try:
                # Clean up sessions older than configured max age
                cleaned_count = self.cleanup_old_sessions(max_age_seconds=max_age_seconds)
                if cleaned_count > 0:
                    logger.debug(f"Progress store: Cleaned up {cleaned_count} old sessions")

                # Wait for configured cleanup cycle before next cleanup, or until stop event
                self._cleanup_stop_event.wait(timeout=cleanup_cycle_seconds)

            except Exception as e:
                logger.debug(f"Progress store cleanup error: {e}")
                # Wait a bit before retrying
                self._cleanup_stop_event.wait(timeout=60)

    def stop_cleanup(self) -> None:
        """Stop the background cleanup thread."""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_stop_event.set()
            self._cleanup_thread.join(timeout=5)

    def force_cleanup_now(self) -> int:
        """Force immediate cleanup of old sessions.

        Returns:
            Number of sessions cleaned up
        """
        config = get_agent_config()
        return self.cleanup_old_sessions(max_age_seconds=config.INTERIM_PROGRESS_STORE_MAX_AGE_SECONDS)


# Global singleton instance
progress_store: ProgressStore = ProgressStore()

# Register cleanup on exit
atexit.register(progress_store.stop_cleanup)


# Utility functions for common progress messages
def get_agent_start_message(agent_name: str) -> str:
    """Get user-friendly message for agent start."""
    agent_messages = {
        "FinancialCompanionAgent": "Looking into your request...",
        "SavingsAgent": "Reviewing your spending and saving...",
        "ProductsAgent": "Gathering product information...",
        "HomebuyingAgent": "Getting home buying options ready...",
    }
    return agent_messages.get(agent_name, "Working on your request...")


def get_tool_start_message(tool_name: str) -> str:
    """Get user-friendly message for tool start."""
    tool_messages = {
        "handle_savings_request": "Accessing transaction information...",
        "handle_products_request": "Loading product details...",
        "handle_homebuying_request": "Calculating home buying options...",
        "get_account_balance": "Checking account balance...",
        "get_transaction_history": "Loading transaction history...",
        "calculate_borrowing_power": "Calculating borrowing power...",
        "get_product_information": "Loading product information...",
        "search_properties": "Searching property database...",
        "calculate_repayments": "Calculating loan repayments...",
        "build_bills_payments_widget": "Checking upcoming bills...",
    }
    return tool_messages.get(tool_name, "Working on your request...")


def get_tool_end_message(tool_name: str) -> str:
    """Get user-friendly message for tool completion."""
    tool_messages = {
        "handle_savings_request": "Account information loaded. Processing results...",
        "handle_products_request": "Product details loaded. Processing results...",
        "handle_homebuying_request": "Home buying options calculated. Processing results...",
        "get_account_balance": "Account balance loaded. Processing results...",
        "get_transaction_history": "Transaction history loaded. Processing results...",
        "calculate_borrowing_power": "Borrowing power calculated. Processing results...",
        "get_product_information": "Product information loaded. Processing results...",
        "search_properties": "Property search completed. Processing results...",
        "calculate_repayments": "Loan repayments calculated. Processing results...",
        "build_bills_payments_widget": "Bill summary created. Processing results...",
    }
    return tool_messages.get(tool_name, "Processing results...")


def get_agent_end_message(agent_name: str) -> str:
    """Get user-friendly message for agent completion."""
    if agent_name == "FinancialCompanionAgent":
        return "Finalising response..."
    else:
        return "Considering next steps..."
