# pylint: skip-file

"""Group IDP client.

This module implements a GroupIdpClient to communicate with a third
party IDP service to get access token for access service domain apis.

"""

import datetime
import time

import httpx
import jwt
from pydantic import BaseModel

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.utils.runtime_utils import SSL_VERIFY


class GroupIdpResponse(BaseModel):
    """Group IDP response structure."""

    access_token: str
    token_type: str
    expires_in: int


class GroupIdpClient:
    """A client for interacting with the Group IDP (Identity Provider).

    This client is used to obtain and manage access tokens.
    """

    def __init__(
        self,
        client_id: str = AppConfig.GROUP_IDP_CLIENT_ID,
        scope: str | list[str] = AppConfig.GROUP_IDP_SCOPE,
    ) -> None:
        """Initialize the Group IDP client.

        Args:
            client_id: The client ID for authentication.
            scope: The scope(s) for the access token. Can be a single string or list of strings.
        """
        self._client_id = client_id
        self._refresh_time: float = -1.0
        self._access_token: str = ""
        self._expire_time: int = -1
        self._scope = scope
        self._httpx_client = httpx.AsyncClient(verify=SSL_VERIFY)
        self._invalidate = True

    def update_scope(self, scope: str | list[str]) -> None:
        """Update the scope for the Group IDP client.

        This is useful if the service requires a different scope than the one initially set.
        Accepts either a single scope string or a list of scope strings.

        Args:
            scope: The new scope(s) for the access token.
        """
        if self._scope != scope:
            logger.debug(f"Updating Group IDP client scope from {self._scope} to {scope}")
            self._scope = scope
            self._invalidate = True

    def get_client_assertion(self) -> str:
        """Construct client assertion payload tokens.

        Returns:
            The encoded JWT client assertion.
        """
        payload = {
            "iss": self._client_id,
            "sub": self._client_id,
            "aud": AppConfig.GROUP_IDP_URL,
            "exp": (datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)),
        }
        client_assertion: str = jwt.encode(
            payload,
            AppConfig.GROUP_IDP_PRIVATE_KEY,
            algorithm="ES256",
        )

        return client_assertion

    async def get_access_token(self) -> str:
        """Get current valid access token or refresh the token.

        This method retrieves a new token from the IDP service if needed.

        Returns:
            The access token string, or empty string if retrieval fails.
        """
        if self._refresh_time > 0 and time.time() - self._refresh_time < self._expire_time and not self._invalidate:
            return self._access_token

        logger.info("Getting IDP access token")

        # Convert scope to space-separated string if it's a list
        scope_str = " ".join(self._scope) if isinstance(self._scope, list) else self._scope

        client_assertion = self.get_client_assertion()
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_assertion_type": ("urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
            "client_assertion": client_assertion,
            "scope": scope_str,
        }

        response = await self._httpx_client.post(
            f"{AppConfig.GROUP_IDP_URL}/tls/as/token.oauth2",
            data=data,
        )
        http_ok = 200
        status = response.status_code
        if status == http_ok:
            logger.info("Successfully retrieved IDP access token")
            group_idp_response = GroupIdpResponse(**response.json())
            self._refresh_time = time.time()
            self._expire_time = group_idp_response.expires_in - 5  # add some buffer seconds.
            self._access_token = group_idp_response.access_token
            self._invalidate = False
            return self._access_token
        logger.error(f"IDP returns {response.text}")

        return ""

    async def fini(self) -> None:
        """Clean up and close the HTTP client."""
        await self._httpx_client.aclose()
