"""Base class for calling remote REST API services using custom group IDP configurations.

Key design choice is a ServiceAPIBase class that allow custom IDP client id and scope.
This is due to the fact that our agent may need to talk to disparate service APIs reside
in different service domains, which will incur different client_id and scope.

This module also supports Basic, Standard Bearer and No Authentication, with IDP by default.

For example:

To call a service for example Customer Product and Service Directory, we can have
a new class

class CustomerProuductSerivce(ServiceAPIBase):
    def __init__(self):
        super(CustomerProuductSerivce, self).__init__(
            name="customer_product",
            base_url="https://test02.partydataservices.test.aws.groupapi.cba",
            client_id="assigned_client_id",
            scope="write read",
        )

    async def retrieve_product_from_party_id(self, party_id: str) -> dict | None:
        path=f"relationship-management/customer-product-and-service-directory/products/v2/parties/{party_id}" # pylint: disable=line-too-long
        status, result = await self.get_call(
            path=path,
            headers={"x-request-id": str(uuid.uuid4())},
        )

        if status == 200:
            return result # result a raw result from the api call
"""

import base64
import time
import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import httpx
from asgi_correlation_id import correlation_id as request_id_getter
from httpx import Response
from opentelemetry import metrics

from common.configs.app_config_settings import AppConfig
from common.group_idp_client import GroupIdpClient
from common.logging.core import log_request, logger
from common.utils.runtime_utils import SSL_VERIFY

# OpenTelemetry metrics for downstream HTTP client calls
# These metrics will use the MeterProvider configured by observability.init()
_meter = metrics.get_meter("financial_companion.http_client")

_http_client_duration = _meter.create_histogram(
    name="financial_companion.http.client.request.duration",
    description="Duration of outbound HTTP requests to downstream services",
    unit="s",
)

_http_client_requests = _meter.create_counter(
    name="financial_companion.http.client.request.count",
    description="Count of outbound HTTP requests to downstream services",
)


class AuthType(StrEnum):
    BEARER = "Bearer"
    BASIC = "Basic"
    NONE = "None"
    IDP = "IDP"


def _record_http_client_metrics(
    method: str,
    service_name: str,
    server_address: str,
    duration: float,
    status_code: int | None = None,
    error_type: str | None = None,
) -> None:
    """Record OpenTelemetry metrics for an HTTP client request.

    Metrics are only recorded when OTLP_METRICS_ENABLED is True.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        service_name: Logical name of the downstream service
        server_address: Base URL/host of the downstream service
        duration: Request duration in seconds
        status_code: HTTP response status code (None if request failed)
        error_type: Type of error if request failed (e.g., "TimeoutException")
    """
    if not AppConfig.OTLP_METRICS_ENABLED:
        return

    attributes: dict[str, Any] = {
        "http.request.method": method,
        "service.name": service_name,
        "server.address": server_address,
    }

    if status_code is not None:
        attributes["http.response.status_code"] = status_code
    if error_type is not None:
        attributes["error.type"] = error_type

    _http_client_duration.record(duration, attributes)
    _http_client_requests.add(1, attributes)


class ServiceAPIBase:
    """Base class for calling to APIs sitting in various service domains.

    It captures the necessary authentication and http calling functions
    that are common for all service calls.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        client_id: str = AppConfig.GROUP_IDP_CLIENT_ID,
        scope: str = AppConfig.GROUP_IDP_SCOPE,
        proxy: str | None = None,
    ):
        """Initialize the ServiceAPIBase instance.

        Args:
            name: Identifier for the service instance.
            base_url: Base URL for the API endpoints.
            client_id: Client ID for Group IDP authentication.
            scope: OAuth scope for Group IDP authentication.
            proxy: Optional proxy URL for HTTP requests.
        """
        self._name = name
        self._base_url = (
            f"{AppConfig.MOCK_API_SERVER_HOST}:{AppConfig.MOCK_API_SERVER_PORT}"
            if AppConfig.USING_MOCK_API
            else base_url
        )
        self._group_idp_client = None if AppConfig.USING_MOCK_API else GroupIdpClient(client_id=client_id, scope=scope)

        if proxy:
            self._session = httpx.AsyncClient(verify=SSL_VERIFY, proxy=proxy)
        else:
            self._session = httpx.AsyncClient(verify=SSL_VERIFY)

    def update_scope(self, scope: str) -> None:
        """Update the scope for the group IDP client.

        This is useful if the service requires a different scope than the one initially set.
        """
        if self._group_idp_client:
            self._group_idp_client.update_scope(scope)

    async def _update_authorisation_headers(
        self,
        headers: dict[str, str],
        auth_type: AuthType | None,
        username: str | None,
        password: str | None,
        bearer_token: str | None,
    ) -> dict[str, str]:
        match auth_type:
            case AuthType.IDP:
                if self._group_idp_client:
                    access_token = await self._group_idp_client.get_access_token()
                    if access_token:
                        logger.info("Updating authorisation headers")
                        headers["authorization"] = f"Bearer {access_token}"
                    else:
                        logger.error("Unable to get access token for {}", self._name)

            case AuthType.BEARER:
                if bearer_token:
                    headers["authorization"] = f"Bearer {bearer_token}"
                else:
                    logger.error("Bearer token is required for Bearer auth")
                    raise OSError("Bearer token is required but not provided")

            case AuthType.BASIC:
                if username and password:
                    auth_string = f"{username}:{password}".encode()
                    headers["authorization"] = f"Basic {base64.b64encode(auth_string).decode()}"
                else:
                    logger.error("Username and password are required for Basic auth")
                    raise OSError("Username and password are required but not provided")

            case AuthType.NONE:
                logger.debug("Using no auth for request, leaving headers unmodified")

            case _:
                logger.warning("Unknown auth type, skipping auth header update")

        return headers

    async def post_call(
        self,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        headers: dict[str, str] | None = None,
        auth_type: AuthType | None = AuthType.IDP,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
        params: Mapping[str, str | list[str]] | None = None,
    ) -> Response:
        """Perform an async REST API POST call with bearer token authentication."""
        # Start timing
        start_time = time.time()

        if headers is None:
            headers = {}
        if params is None:
            params = {}

        url = f"{self._base_url}{path}"

        headers = await self._update_authorisation_headers(
            headers=headers,
            auth_type=auth_type,
            username=username,
            password=password,
            bearer_token=bearer_token,
        )

        # Log downstream service call
        logger.info(f"Service call using {auth_type}: POST - {url}")

        headers["x-request-id"] = request_id_getter.get() or uuid.uuid4().hex

        response: Response | None = None
        error_type: str | None = None
        try:
            response = await self._session.post(
                url,
                headers=headers,
                json=payload,
                timeout=AppConfig.HTTP_TIMEOUT,
                params=params,
            )
            return response
        except Exception as e:
            error_type = type(e).__name__
            raise
        finally:
            # Calculate duration
            duration = time.time() - start_time

            # Log completed request
            log_request(
                method="POST",
                request_id=headers.get("x-request-id", ""),
                path=url,
                status_code=response.status_code if response else 0,
                duration=duration,
            )

            # Record metrics for downstream service call
            _record_http_client_metrics(
                method="POST",
                service_name=self._name,
                server_address=self._base_url,
                duration=duration,
                status_code=response.status_code if response else None,
                error_type=error_type,
            )

    async def get_call(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: Mapping[str, str | list[str]] | None = None,
        auth_type: AuthType | None = AuthType.IDP,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
    ) -> Response:
        """Perform an async REST API GET call with bearer token authentication."""
        # Start timing
        start_time = time.time()

        if headers is None:
            headers = {}
        if params is None:
            params = {}

        url = f"{self._base_url}{path}"

        headers = await self._update_authorisation_headers(
            headers=headers,
            auth_type=auth_type,
            username=username,
            password=password,
            bearer_token=bearer_token,
        )

        # Log downstream service call
        logger.info(f"Service call using {auth_type}: GET - {url}")

        headers["x-request-id"] = request_id_getter.get() or uuid.uuid4().hex

        response: Response | None = None
        error_type: str | None = None
        try:
            response = await self._session.get(url, headers=headers, timeout=AppConfig.HTTP_TIMEOUT, params=params)
            return response
        except Exception as e:
            error_type = type(e).__name__
            raise
        finally:
            # Calculate duration
            duration = time.time() - start_time

            # Log completed request
            log_request(
                method="GET",
                request_id=headers.get("x-request-id", ""),
                path=url,
                status_code=response.status_code if response else 0,
                duration=duration,
            )

            # Record metrics for downstream service call
            _record_http_client_metrics(
                method="GET",
                service_name=self._name,
                server_address=self._base_url,
                duration=duration,
                status_code=response.status_code if response else None,
                error_type=error_type,
            )

    async def put_call(
        self,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        headers: dict[str, str] | None = None,
        params: Mapping[str, str | list[str]] | None = None,
        auth_type: AuthType | None = AuthType.IDP,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
    ) -> Response:
        """Perform an async REST API PUT call with bearer token authentication."""
        # Start timing
        start_time = time.time()

        if headers is None:
            headers = {}
        if params is None:
            params = {}

        url = f"{self._base_url}{path}"

        headers = await self._update_authorisation_headers(
            headers=headers,
            auth_type=auth_type,
            username=username,
            password=password,
            bearer_token=bearer_token,
        )

        # Log downstream service call
        logger.info(f"Service call using {auth_type}: PUT - {url}")

        headers["x-request-id"] = request_id_getter.get() or uuid.uuid4().hex

        response: Response | None = None
        error_type: str | None = None
        try:
            response = await self._session.put(
                url,
                headers=headers,
                json=payload,
                timeout=AppConfig.HTTP_TIMEOUT,
                params=params,
            )
            return response
        except Exception as e:
            error_type = type(e).__name__
            raise
        finally:
            # Calculate duration
            duration = time.time() - start_time

            # Log completed request
            log_request(
                method="PUT",
                request_id=headers.get("x-request-id", ""),
                path=url,
                status_code=response.status_code if response else 0,
                duration=duration,
            )

            # Record metrics for downstream service call
            _record_http_client_metrics(
                method="PUT",
                service_name=self._name,
                server_address=self._base_url,
                duration=duration,
                status_code=response.status_code if response else None,
                error_type=error_type,
            )

    async def delete_call(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: Mapping[str, str | list[str]] | None = None,
        auth_type: AuthType | None = AuthType.IDP,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
    ) -> Response:
        """Perform an async REST API DELETE call with authentication."""
        # Start timing
        start_time = time.time()

        if headers is None:
            headers = {}
        if params is None:
            params = {}

        url = f"{self._base_url}{path}"

        headers = await self._update_authorisation_headers(
            headers=headers,
            auth_type=auth_type,
            username=username,
            password=password,
            bearer_token=bearer_token,
        )

        # Log downstream service call
        logger.info(f"Service call using {auth_type}: DELETE - {url}")

        headers["x-request-id"] = request_id_getter.get() or uuid.uuid4().hex

        response: Response | None = None
        error_type: str | None = None
        try:
            response = await self._session.delete(url, headers=headers, timeout=AppConfig.HTTP_TIMEOUT, params=params)
            return response
        except Exception as e:
            error_type = type(e).__name__
            raise
        finally:
            # Calculate duration
            duration = time.time() - start_time

            # Log completed request
            log_request(
                method="DELETE",
                request_id=headers.get("x-request-id", ""),
                path=url,
                status_code=response.status_code if response else 0,
                duration=duration,
            )

            # Record metrics for downstream service call
            _record_http_client_metrics(
                method="DELETE",
                service_name=self._name,
                server_address=self._base_url,
                duration=duration,
                status_code=response.status_code if response else None,
                error_type=error_type,
            )

    async def fini(self) -> None:
        """Clean up resources and close connections."""
        await self._session.aclose()
        if self._group_idp_client:
            await self._group_idp_client.fini()
