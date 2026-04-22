"""Elastic Search API Client Module.

This module provides a client for interacting with the Elastic Search API,
which enables searching across indexed data stored in Elastic Cloud using
single-line or typedown search queries.
"""

import json
import uuid
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.services.service_api_base import AuthType, ServiceAPIBase


class ElasticSearchRequest(BaseModel):
    """Input parameters for an Elastic Search query.

    Encapsulates all parameters required to call the Elastic Cloud search API,
    including built-in validation for mandatory fields and query length constraints.

    Attributes:
        index_name: The Elastic Cloud index to search.
        query: Search query string (must be between 3 and 100 characters).
        template_id: Template ID that controls the search behaviour.
        page_size: Number of results to return per page (must be >= 1).
        from_index: Zero-based offset for paginating through results.
        app_version: App version making the search request.
        device: Device type making the search request.
        domain_names: Domain names used to filter search results.
        x_request_id: Request correlation UUID (auto-generated if not provided).
    """

    index_name: str = Field(..., min_length=1, description="The Elastic Cloud index to search")
    query: str = Field(..., min_length=3, max_length=100, description="Search query string (3-100 characters)")
    template_id: str = Field(..., min_length=1, description="Template ID that controls the search behaviour")
    page_size: int | None = Field(None, ge=1, description="Number of results per page")
    from_index: int | None = Field(None, ge=0, description="Zero-based pagination offset")
    app_version: str | None = Field(None, description="App version making the search request")
    device: str | None = Field(None, description="Device type making the search request")
    domain_names: list[str] | None = Field(None, description="Domain names used to filter search results")
    x_request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Request correlation UUID (auto-generated if not provided)",
    )

    model_config = ConfigDict(populate_by_name=True)


class ElasticSearchDocument(BaseModel):
    """A single document returned in an Elastic Search result set.

    The schema of each document varies by index, so additional fields
    beyond any declared ones are preserved transparently.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ElasticSearchResponse(BaseModel):
    """Successful response from the Elastic Search API.

    Attributes:
        total_records: Total number of documents matching the query.
        results: List of matching documents.
        error_messages: Any error messages returned alongside results.
    """

    total_records: int = Field(0, alias="totalRecords", ge=0, description="Total number of matching records")
    results: list[ElasticSearchDocument] = Field(default_factory=list, description="List of matching documents")
    error_messages: list[Any] = Field(
        default_factory=list,
        alias="errorMessages",
        description="Error messages returned alongside results, if any",
    )

    @field_validator("error_messages", mode="before")
    @classmethod
    def coerce_empty_string_to_list(cls, v: Any) -> Any:
        """Coerce an empty string to an empty list.

        The API returns errorMessages as an empty string "" when there are no
        errors, rather than an empty list [].
        """
        if v == "":
            return []
        return v

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ElasticSearchErrorResponse(BaseModel):
    """Error response from the Elastic Search API.

    Returned when the API responds with a non-200 status code.

    Attributes:
        error: Always ``True`` to distinguish this from a success response.
        status_code: HTTP status code returned by the API.
        message: Human-readable error detail from the API response.
        x_request_id: Correlation ID to help trace the request in logs.
    """

    error: bool = Field(True, description="Always True for error responses")
    status_code: int = Field(..., description="HTTP status code returned by the API")
    message: str = Field(..., description="Human-readable error detail from the API response")
    x_request_id: str | None = Field(None, description="Correlation ID to help trace the request in logs")

    model_config = ConfigDict(populate_by_name=True)


_ERROR_MESSAGE_FIELDS: tuple[str, ...] = ("message", "error", "detail", "errorMessage", "error_description")
_MAX_ERROR_MESSAGE_LENGTH: int = 200


class ElasticSearchService(ServiceAPIBase):
    """Elastic Search API client implementation.

    This class provides methods for interacting with the CommBank Elastic Search API
    to perform searches across various indexed document types including app search,
    netbank, netbank next, commbroker, and web crawler documents.

    The API is authenticated using OAuth2 client credentials.
    """

    def __init__(
        self,
        name: str = "ElasticSearch-Service",
        base_url: str = AppConfig.ELASTIC_SEARCH_SERVICE_BASE_URL,
        scope: str = AppConfig.ELASTIC_SEARCH_SERVICE_SCOPE,
    ):
        """Initialize the ElasticSearchService API client.

        Args:
            name: Client identifier name. Defaults to "ElasticSearch-Service".
            base_url: Base URL for the Elastic Search API.
            scope: OAuth2 scope for authentication. Defaults to "elastic-search.read".
        """
        super().__init__(
            name=name,
            base_url=base_url,
            scope=scope,
        )

    def _build_search_payload(self, request: ElasticSearchRequest) -> dict[str, Any]:
        """Build the search request payload from the provided request model.

        Args:
            request: Validated search request model.

        Returns:
            dict[str, Any]: The constructed request body.
        """
        payload: dict[str, Any] = {"query": request.query, "templateId": request.template_id}
        if request.page_size is not None:
            payload["pageSize"] = request.page_size
        if request.from_index is not None:
            payload["from"] = request.from_index
        if request.app_version is not None:
            payload["appVersion"] = request.app_version
        if request.device is not None:
            payload["device"] = request.device
        if request.domain_names is not None:
            payload["domainNames"] = request.domain_names
        return payload

    def _extract_error_message(self, raw_body: str) -> str:
        """Extract a concise, safe error message from a raw response body.

        Tries to parse the body as JSON and pull a well-known error message field.
        Falls back to a plain-text truncation when JSON is unavailable or lacks a
        recognised field.  The returned string is always bounded to
        ``_MAX_ERROR_MESSAGE_LENGTH`` characters.

        Args:
            raw_body: Raw text of the HTTP error response.

        Returns:
            str: A concise, bounded error message safe for downstream callers.
        """
        try:
            data = json.loads(raw_body)
            if isinstance(data, dict):
                for field in _ERROR_MESSAGE_FIELDS:
                    value = data.get(field)
                    if isinstance(value, str) and value:
                        return value[:_MAX_ERROR_MESSAGE_LENGTH]
        except (ValueError, TypeError):
            pass

        return raw_body[:_MAX_ERROR_MESSAGE_LENGTH] if raw_body else "Unknown error"

    def _handle_error_response(
        self, status_code: int, raw_body: str, x_request_id: str | None = None
    ) -> ElasticSearchErrorResponse:
        """Log and return a structured error response model.

        Args:
            index_name: The index that was searched.
            status_code: HTTP status code from the response.
            raw_body: Raw response body text from the API.
            x_request_id: Optional correlation ID to include in the error model.

        Returns:
            ElasticSearchErrorResponse: Structured error information with a concise,
                bounded message and the correlation ID.
        """
        logger.error(f"Elastic Search API error: {status_code} (x_request_id={x_request_id})")
        message = self._extract_error_message(raw_body)
        return ElasticSearchErrorResponse(status_code=status_code, message=message, x_request_id=x_request_id)

    async def search(
        self,
        request: ElasticSearchRequest,
    ) -> ElasticSearchResponse | ElasticSearchErrorResponse:
        """Search an Elastic Cloud index using single line or typedown search.

        Args:
            request: Validated search request model containing all query parameters.
                Validation is enforced by the ``ElasticSearchRequest`` model - query
                must be between 3 and 100 characters, and index_name / template_id
                must be non-empty.

        Returns:
            ElasticSearchResponse: Parsed API response containing matching documents
                and the total record count on success.
            ElasticSearchErrorResponse: Structured error information when the API
                returns a non-200 status code.

        Raises:
            Exception: If the underlying HTTP request fails unexpectedly.
        """
        logger.debug(
            f"Searching Elastic Cloud index '{request.index_name}'",
            extra={
                "index_name": request.index_name,
                "template_id": request.template_id,
                "query_length": len(request.query),
                "page_size": request.page_size,
                "from_index": request.from_index,
                "x_request_id": request.x_request_id,
            },
        )

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-request-id": request.x_request_id,
        }

        payload = self._build_search_payload(request)

        path = f"/search/{request.index_name}"
        try:
            response = await self.post_call(
                path=path,
                payload=payload,
                headers=headers,
                auth_type=AuthType.IDP,
            )

            if response.status_code != HTTPStatus.OK:
                return self._handle_error_response(
                    response.status_code,
                    response.text or "",
                    x_request_id=request.x_request_id,
                )

            parsed = ElasticSearchResponse.model_validate(response.json())
            logger.debug(
                f"Elastic Cloud search returned {parsed.total_records} results for index '{request.index_name}'",
                extra={"index_name": request.index_name, "total_records": parsed.total_records},
            )
            return parsed

        except Exception:
            logger.exception(
                f"Error searching Elastic Cloud index '{request.index_name}'",
                extra={"index_name": request.index_name},
            )
            raise


# Create a singleton instance
elastic_search_service = ElasticSearchService()
