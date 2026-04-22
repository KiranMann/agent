from typing import Any

from common.logging.core import log_error, logger
from common.redis_connection_manager import get_redis_client


class RedisService:
    """Service for interacting with Redis cache, enforcing a minimum TTL on all keys."""

    MIN_TTL_SECONDS = 30
    SUCCESS_ID = 1

    async def set_with_min_ttl(self, key: str, value: str, ttl: int = MIN_TTL_SECONDS) -> bool:
        """Set a key-value pair in Redis with a minimum enforced TTL.

        Args:
            key: The cache key.
            value: The value to store.
            ttl: Desired TTL in seconds (minimum enforced).

        Returns:
            True if the key was set successfully, False otherwise.
        """
        client = await get_redis_client()
        if client is None:
            logger.warning("Redis client unavailable, cannot set key", extra={"key": key})
            return False

        try:
            effective_ttl = max(ttl, self.MIN_TTL_SECONDS)
            result = await client.set(name=key, value=value, ex=effective_ttl)
            logger.debug(f"Set Redis key with TTL {effective_ttl}s", extra={"key": key, "ttl": effective_ttl})
            return bool(result)
        except Exception as e:
            log_error(e, context="redis_set_with_min_ttl", key=key, ttl=ttl)
            return False

    async def get_value(self, key: str) -> None | Any:
        """Retrieve a value from Redis by key.

        Args:
            key: The cache key.

        Returns:
            The value if present, else None.
        """
        client = await get_redis_client()
        if client is None:
            logger.warning("Redis client unavailable, cannot get key", extra={"key": key})
            return None

        try:
            value = await client.get(key)
            if value is not None:
                logger.debug("Retrieved Redis key", extra={"key": key})
            else:
                logger.debug("Redis key not found", extra={"key": key})
            return value
        except Exception as e:
            log_error(e, context="redis_get_value", key=key)
            return None

    async def key_exist(self, key: str) -> bool:
        """Return True if the key exists in Redis, False otherwise.

        Args:
            key: The cache key to check.

        Returns:
            True if the key exists, False if not or if Redis is unavailable.
        """
        client = await get_redis_client()
        if client is None:
            logger.warning("Redis client unavailable, cannot check key existence", extra={"key": key})
            return False

        try:
            result = await client.exists(key)
            exists = bool(result > 0)
            logger.debug(f"Redis key existence check: {exists}", extra={"key": key, "exists": exists})
            return exists
        except Exception as e:
            log_error(e, context="redis_key_exist", key=key)
            return False

    async def delete_key(self, key: str) -> bool:
        """Delete a key from Redis and return True if successful.

        Args:
            key: The cache key to delete.

        Returns:
            True if the key was deleted, False if not or if Redis is unavailable.
        """
        client = await get_redis_client()
        if client is None:
            logger.warning("Redis client unavailable, cannot delete key", extra={"key": key})
            return False

        try:
            result = await client.delete(key)
            deleted = bool(result == self.SUCCESS_ID)
            logger.debug(f"Deleted Redis key: {deleted}", extra={"key": key, "deleted": deleted})
            return deleted
        except Exception as e:
            log_error(e, context="redis_delete_key", key=key)
            return False


redis_service = RedisService()
