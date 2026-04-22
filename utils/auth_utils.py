"""Authentication and Authorization Utilities for Financial Companion Agent.

This module provides helper functions for JWT validation, JWK initialization,
and scope-based authorization for FastAPI endpoints. It supports extracting
and validating JWTs from HTTP requests, checking user scopes, and providing
FastAPI dependencies for secure route protection.

Functions:
    refresh_jwks_cache_if_needed(): Loads and caches JWKs from the configured IdP.
    has_required_scopes(user_scopes, required_scopes): Checks if user has any required scopes.
    extract_and_validate_jwt(request): Extracts and validates a JWT from the request.
    require_scopes(required_scopes): FastAPI dependency to enforce required scopes.
"""

import time
from enum import StrEnum
from functools import lru_cache
from http import HTTPStatus
from typing import Any

import jwt
import requests
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger


class Scopes(StrEnum):
    """Valid scopes for Financial Companion authentication."""

    AGENT_WRITE = "financial-companion.agent.write"
    CONVERSATION_WRITE = "financial-companion.conversations.write"
    MESSAGE_WRITE = "financial-companion.message.write"
    VOICE_WRITE = "financial-companion.voice.write"

    @classmethod
    def all_scopes(cls) -> list[str]:
        """Return all valid scopes as a list."""
        return [scope.value for scope in cls]


VALID_SCOPES: list[str] = Scopes.all_scopes()

FC_EXPERIENCE_API_SUBJECT: str = AppConfig.CONSUMER_IDP_CLIENT


class CachedJWKSClient:
    """Wrapper around PyJWKClient with configurable cache TTL.

    PyJWKClient doesn't expose cache TTL configuration, so this wrapper
    provides a fresh PyJWKClient instance when the cache expires.
    """

    def __init__(self, jwks_url: str, cache_ttl_seconds: int = 120) -> None:
        """Initialize the cached JWKS client.

        Args:
            jwks_url: The URL to fetch JSON Web Key Sets from.
            cache_ttl_seconds: Cache time-to-live in seconds. Defaults to 120.
        """
        self.jwks_url = jwks_url
        self.cache_ttl_seconds = cache_ttl_seconds
        self._client: PyJWKClient | None = None
        self._last_refresh: float = 0.0

    def _get_client(self) -> PyJWKClient:
        """Get PyJWKClient, refreshing if cache has expired."""
        now: float = time.time()
        if self._client is None or (now - self._last_refresh) > self.cache_ttl_seconds:
            logger.info(f"Loading JWKS from {self.jwks_url} (TTL: {self.cache_ttl_seconds}s)")
            self._client = PyJWKClient(self.jwks_url)
            self._last_refresh = now

            # Log available keys for debugging
            try:
                # Get JWKS data to log available keys
                response: requests.Response = requests.get(self.jwks_url, timeout=10)
                if response.status_code == HTTPStatus.OK:
                    if not response.headers.get("content-type", "").startswith("application/json"):
                        raise ValueError("Expected JSON response from JWKS endpoint")
                    jwks_data = response.json()
                    if "keys" not in jwks_data or not isinstance(jwks_data["keys"], list):
                        raise ValueError("Invalid JWKS format: missing or invalid 'keys' field")
                    keys = jwks_data.get("keys", [])
                    key_ids: list[Any] = [key.get("kid", "unknown") for key in keys]
                    logger.info(f"JWKS loaded successfully. Found {len(keys)} keys with IDs: {key_ids}")
                else:
                    logger.error(f"JWKS endpoint returned status {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Could not log JWKS key details: {e}")

        return self._client

    def get_signing_key_from_jwt(self, token: str) -> Any:
        """Get signing key from JWT, with automatic cache refresh."""
        kid = "unknown"
        try:
            # Extract kid from token header for logging (never log the actual token)
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid", "unknown")
            logger.info(f"Looking for signing key with ID: {kid}")

            return self._get_client().get_signing_key_from_jwt(token)

        except Exception as e:
            # Log error without token details - only log the kid for context
            logger.error(f"Failed to get signing key for kid '{kid}': {type(e).__name__}")
            raise


@lru_cache(maxsize=1)
def get_jwks_client() -> CachedJWKSClient:
    """Get or create the cached CachedJWKSClient instance."""
    logger.info(f"Initializing JWKS client for URL: {AppConfig.JWKS_URL}")
    client = CachedJWKSClient(AppConfig.JWKS_URL, AppConfig.JWKS_CACHE_TTL_SECONDS)
    logger.info(f"JWKS client initialized with {AppConfig.JWKS_CACHE_TTL_SECONDS}s cache TTL")
    return client


def has_required_scopes(user_scopes: list[str], required_scopes: list[str]) -> bool:
    """Checks if the user has at least one of the required scopes.

    Args:
        user_scopes (list or set): The scopes assigned to the user.
        required_scopes (list or set): The scopes required for access.

    Returns:
        bool: True if the user has any of the required scopes, False otherwise.
    """
    return bool(set(user_scopes) & set(required_scopes))


def extract_and_validate_jwt(request: Request) -> dict[str, Any]:
    """Extracts and validates a JWT from the Authorization header of the request.

    Uses PyJWKClient for automatic JWKS fetching and key rotation handling.
    Validates the token's signature, issuer, and expiration.
    Raises HTTPException if validation fails.

    Args:
        request (Request): The FastAPI request object.

    Returns:
        dict: The decoded JWT payload.
    """
    auth_header: str | None = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        logger.warning("Missing or invalid authorization header")
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    try:
        token: str = auth_header.split(" ")[1]
    except IndexError as exc:
        logger.warning("Malformed authorization header")
        raise HTTPException(status_code=401, detail="Malformed authorization header") from exc

    try:
        # PyJWKClient automatically handles key fetching and rotation
        client: CachedJWKSClient = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)

        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=AppConfig.GROUP_IDP_URL,
        )
    except jwt.ExpiredSignatureError as exc:
        logger.warning("JWT token has expired")
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidIssuerError as exc:
        logger.warning("JWT token has invalid issuer")
        raise HTTPException(status_code=401, detail="Invalid issuer") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT token is invalid")
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    except Exception as exc:
        # Log error without token details for security
        logger.error("JWT validation failed", exc_info=exc)
        raise HTTPException(status_code=401, detail="Token validation failed") from exc

    if payload.get("sub") != FC_EXPERIENCE_API_SUBJECT:
        logger.warning("JWT token has invalid subject")
        raise HTTPException(status_code=401, detail="Invalid subject")

    return payload


def require_scopes(required_scopes: list[str]) -> Any:
    """FastAPI dependency to enforce required scopes on a route.

    Respects SKIP_IDP_AUTH_CHECK for development/testing environments.

    Args:
        required_scopes (list): The scopes required to access the route.

    Returns:
        function: A dependency function that validates the JWT and required scopes,
                  returning the JWT payload if authorized, or raising HTTPException.
    """

    def dependency(request: Request) -> dict[str, Any]:
        # Skip authentication if configured (dev/test environments)
        if AppConfig.SKIP_IDP_AUTH_CHECK:
            logger.info("Skipping JWT authentication due to SKIP_IDP_AUTH_CHECK=True")
            return {"sub": FC_EXPERIENCE_API_SUBJECT, "scope": " ".join(VALID_SCOPES)}

        payload = extract_and_validate_jwt(request)
        user_scopes = payload.get("scope", "").split()
        if not has_required_scopes(user_scopes, required_scopes):
            logger.warning("JWT token has insufficient scopes")
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return payload

    return dependency
