"""SQLAlchemy database setup and configuration module.

This module provides the foundational SQLAlchemy setup for the Financial Companion project,
including async engine creation, session management, and base model definitions.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class DatabaseManager:
    """Manages SQLAlchemy async engine and session creation.

    This class provides a centralized way to manage database connections
    using SQLAlchemy's async capabilities while maintaining compatibility
    with the existing psycopg connection pool approach.
    """

    def __init__(self) -> None:
        """Initialize the DatabaseManager with empty engine and session factory."""
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def _create_database_url(self) -> str:
        """Create the async database URL from configuration."""
        if not all([AppConfig.DB_HOST, AppConfig.DB_PORT, AppConfig.DB_USER, AppConfig.DB_PASSWORD]):
            raise ValueError("Database configuration incomplete")

        # Use asyncpg driver for async SQLAlchemy
        password = AppConfig.DB_PASSWORD or ""
        return (
            f"postgresql+asyncpg://{AppConfig.DB_USER}:"
            f"{quote_plus(password)}@{AppConfig.DB_HOST}:"
            f"{AppConfig.DB_PORT}/{AppConfig.DB_NAME}"
        )

    def get_engine(self) -> AsyncEngine:
        """Get or create the SQLAlchemy async engine.

        Returns:
            AsyncEngine: The SQLAlchemy async engine instance

        Raises:
            ValueError: If database configuration is incomplete
        """
        if self._engine is None:
            database_url = self._create_database_url()

            self._engine = create_async_engine(
                database_url,
                # Use NullPool to avoid connection pool conflicts with existing psycopg pool
                poolclass=NullPool,
                # Enable SQL logging in development
                echo=False,  # Set to True for SQL debugging
                # Connection arguments
                connect_args={
                    "server_settings": {
                        "application_name": "financial_companion_sqlalchemy",
                    }
                },
            )

            logger.info("SQLAlchemy async engine created successfully")

        return self._engine

    def get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get or create the SQLAlchemy session factory.

        Returns:
            async_sessionmaker: Factory for creating async sessions
        """
        if self._session_factory is None:
            engine = self.get_engine()
            self._session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=True,
                autocommit=False,
            )

            logger.info("SQLAlchemy session factory created successfully")

        return self._session_factory

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Get an async database session.

        This is an async context manager that provides a database session
        and ensures proper cleanup.

        Yields:
            AsyncSession: An async SQLAlchemy session

        Example:
            async with db_manager.get_session() as session:
                result = await session.execute(select(Model))
        """
        session_factory = self.get_session_factory()
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def close(self) -> None:
        """Close the database engine and clean up resources."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("SQLAlchemy engine closed successfully")


# Global database manager instance
db_manager: DatabaseManager = DatabaseManager()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Get the database session async context manager from the DatabaseManager.

    This function provides access to the DatabaseManager's session context manager
    for database operations.

    Returns:
        AsyncGenerator[AsyncSession, None]: The DatabaseManager's session context manager

    Example:
        async with get_db_session() as session:
            result = await session.execute(select(Model))
    """
    async with db_manager.get_session() as session:
        yield session


def is_database_configured() -> bool:
    """Check if database configuration is available.

    Returns:
        bool: True if database is properly configured, False otherwise
    """
    return all(
        [
            AppConfig.DB_HOST,
            AppConfig.DB_PORT,
            AppConfig.DB_USER,
            AppConfig.DB_PASSWORD,
            AppConfig.DB_NAME,
        ]
    )
