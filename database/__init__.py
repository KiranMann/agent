"""Database module for Financial Companion.

This module provides SQLAlchemy-based database access with async support.
It includes models, session management, and database utilities.
"""

from common.database.models import Conversation, ConversationMessage
from common.database.sqlalchemy_setup import Base, DatabaseManager, db_manager, get_db_session, is_database_configured

__all__ = [
    "Base",
    # Models
    "Conversation",
    "ConversationMessage",
    "DatabaseManager",
    "db_manager",
    "get_db_session",
    "is_database_configured",
]
