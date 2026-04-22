"""Redis cache module.

This module provides Redis connection management
for the Financial Companion project. Supports both
standalone Redis (local) and Redis cluster (AWS ElastiCache).
"""

from __future__ import annotations

from redis.asyncio import Redis, RedisCluster
from redis.asyncio.cluster import ClusterNode

from common.configs.app_config_settings import AppConfig
from common.logging.core import EnhancedLoggingHandler, logger
from common.utils.runtime_utils import set_redis_secrets


class RedisConnectionManager:
    """Redis connection manager for the Financial Companion project.

    Supports both standalone Redis (local development) and
    Redis cluster mode (AWS ElastiCache) based on configuration.
    """

    def __init__(self) -> None:
        """Initialize Redis connection manager."""
        self._client: Redis | RedisCluster | None = None
        self._host: str = ""
        self._port: int = 0
        self._in_dhp: bool = EnhancedLoggingHandler.is_dhp_environment()

        if self._in_dhp:
            set_redis_secrets()

        endpoint = AppConfig.REDIS_CONFIGURATION_ENDPOINT
        if endpoint and ":" in endpoint:
            host, port = endpoint.split(":")
            self._host = host
            self._port = int(port)

    async def _create_standalone_cluster_client(self) -> RedisCluster | None:
        """Create an async Redis client (standalone or cluster) using a shared config dict."""
        try:
            logger.info("Redis: Detecting DHP env")
            client = RedisCluster(
                startup_nodes=[ClusterNode(host=self._host, port=self._port)],
                password=AppConfig.REDIS_AUTH_TOKEN,
                decode_responses=True,
                socket_timeout=30,
                socket_connect_timeout=10,
                max_connections=AppConfig.REDIS_MAX_CONNECTIONS,
                ssl=True,
            )
            is_successful = await client.ping()
            if is_successful:
                return client

            return None

        except Exception as e:
            logger.error(f"Redis connection error: {e}")
            return None

    async def _create_standalone_noncluster_client(self) -> Redis | None:
        """Create an async Redis client (standalone non cluster) using a shared config dict."""
        try:
            client = Redis(
                host=self._host,
                port=self._port,
                password=AppConfig.REDIS_AUTH_TOKEN,
                decode_responses=True,
                socket_timeout=30,
                socket_connect_timeout=10,
                max_connections=AppConfig.REDIS_MAX_CONNECTIONS,
                ssl=False,
            )

            is_successful = await client.ping()
            if is_successful:
                return client

            return None

        except Exception as e:
            logger.error(f"Redis connection error: {e}")
            return None

    async def _create_client(self) -> Redis | RedisCluster | None:
        """Create the appropriate Redis client based on configuration.

        Returns:
            Redis client or None if Redis is not configured.
        """
        if not AppConfig.REDIS_CONFIGURATION_ENDPOINT:
            logger.warning("Redis configuration endpoint not configured, skipping client creation")
            return None

        if not AppConfig.REDIS_AUTH_TOKEN:
            logger.warning("Redis auth token not configured, skipping client creation")
            return None

        try:
            logger.info("Creating async standalone Redis client")
            client: Redis | RedisCluster | None = None

            if self._in_dhp:
                client = await self._create_standalone_cluster_client()
            else:
                client = await self._create_standalone_noncluster_client()

            if client:
                logger.info("Async standalone Redis client created and verified successfully")
                return client
            raise RuntimeError("Failed to instantiate Redis client: ping unsuccessful or client is None")

        except Exception as exc:
            logger.exception(f"Failed to create Redis client: {exc}")
            return None

    async def get_redis_client(self) -> Redis | RedisCluster | None:
        """Get Redis client, creating it if necessary.

        Returns:
            Redis client or None if not available.
        """
        if self._client is None:
            self._client = await self._create_client()

        return self._client

    async def close(self) -> None:
        """Close the Redis client connection."""
        if self._client:
            logger.info("Closing Redis client connection")
            await self._client.close()
            self._client = None


_redis_manager = RedisConnectionManager()


async def get_redis_client() -> Redis | RedisCluster | None:
    """Get Redis client for use throughout the application.

    Returns:
        Redis client or None if Redis is not available.
    """
    return await _redis_manager.get_redis_client()


async def close_redis() -> None:
    """Close the global Redis connection."""
    await _redis_manager.close()
