"""A2A client for sending JSON-RPC messages to remote agents."""

import logging
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import httpx
from a2a.types import AgentCard

logger = logging.getLogger(__name__)


class A2AClientError(Exception):
    """Exception raised by A2A client operations."""


class A2AClientResponse:
    """Parsed response from an A2A agent."""

    def __init__(
        self,
        message: str,
        ui_components: list[dict[str, Any]],
        raw_response: dict[str, Any],
        full_subagent_output: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the response.

        Args:
            message: Text message from response parts
            ui_components: Data parts parsed as dicts
            raw_response: Full JSON-RPC response
            full_subagent_output: Complete serialised SubAgentOutput dict, when available
        """
        self.message = message
        self.ui_components = ui_components
        self.raw_response = raw_response
        self.full_subagent_output = full_subagent_output


class A2AClient:
    """Client for sending A2A JSON-RPC messages to remote agents."""

    def __init__(self, agent_card: AgentCard, timeout_seconds: int = 30) -> None:
        """Initialize with a discovered agent card.

        Args:
            agent_card: The agent card from registry discovery
            timeout_seconds: HTTP timeout for requests
        """
        self.agent_card = agent_card
        self.timeout_seconds = timeout_seconds
        self.http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    def _build_jsonrpc_request(
        self,
        text: str,
        metadata: dict[str, str],
        extensions: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build JSON-RPC message/send request payload.

        Args:
            text: The user's query text
            metadata: Request metadata dict
            extensions: Optional extensions dict

        Returns:
            JSON-RPC request payload dict
        """
        request_payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": str(uuid4()),
                },
                "configuration": {
                    "acceptedOutputModes": ["text/plain", "application/json"],
                    "blocking": True,
                },
                "metadata": metadata,
            },
        }

        # Add extensions if provided (for context parity with in-process execution)
        if extensions:
            request_payload["params"]["extensions"] = extensions

        return request_payload

    def _build_headers(
        self,
        trace_id: str | None,
        parent_span_id: str | None,
    ) -> dict[str, str]:
        """Build HTTP headers for A2A request.

        Args:
            trace_id: Langfuse trace ID for distributed tracing
            parent_span_id: Langfuse parent span ID for distributed tracing

        Returns:
            HTTP headers dict
        """
        headers = {"Content-Type": "application/json"}
        if trace_id:
            headers["X-Langfuse-Trace-Id"] = trace_id
        if parent_span_id:
            headers["X-Langfuse-Parent-Span-Id"] = parent_span_id
        return headers

    async def _send_http_request(
        self,
        request_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Send HTTP POST request and return JSON response.

        Args:
            request_payload: JSON-RPC request payload
            headers: HTTP headers

        Returns:
            JSON response data

        Raises:
            A2AClientError: On HTTP errors
        """
        try:
            logger.debug(f"Sending A2A request to {self.agent_card.url}")

            response = await self.http_client.post(self.agent_card.url, json=request_payload, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            # Type assertion for mypy - response.json() returns dict[str, Any] for JSON objects
            assert isinstance(response_data, dict), "A2A response must be a JSON object"
            return response_data

        except httpx.TimeoutException as e:
            logger.warning(f"A2A request timeout to {self.agent_card.url}: {e}")
            raise A2AClientError(f"Request timeout after {self.timeout_seconds} seconds") from e

        except httpx.HTTPStatusError as e:
            logger.warning(f"A2A HTTP error {e.response.status_code} from {self.agent_card.url}")
            raise A2AClientError(f"HTTP {e.response.status_code} error from agent") from e

        except (httpx.RequestError, httpx.ConnectError) as e:
            logger.warning(f"A2A connection error to {self.agent_card.url}")
            raise A2AClientError(f"Connection error to agent: {e!s}") from e

        except Exception as e:
            logger.exception("A2A client error")
            raise A2AClientError(f"Unexpected error: {e!s}") from e

    @staticmethod
    def _parse_jsonrpc_result(response_data: dict[str, Any]) -> dict[str, Any]:
        """Parse and validate JSON-RPC response structure.

        Args:
            response_data: Raw JSON response from server

        Returns:
            The result dict from JSON-RPC response

        Raises:
            A2AClientError: On JSON-RPC errors or missing result
        """
        if "error" in response_data:
            error = response_data["error"]
            raise A2AClientError(f"A2A agent returned error {error.get('code')}: {error.get('message')}")

        result = response_data.get("result")
        if not result:
            raise A2AClientError("No result in A2A response")

        # Type assertion for mypy - result should be a dict for all A2A response formats
        assert isinstance(result, dict), "A2A result must be a JSON object"
        return result

    @staticmethod
    def _extract_parts_from_message_wrapper(result: dict[str, Any]) -> list[Any]:
        """Extract parts list from type='message' wrapper format.

        Args:
            result: Result dict with type="message"

        Returns:
            Parts list or empty list
        """
        message = result.get("message")
        if message and "parts" in message:
            parts = message["parts"]
            return list(parts) if isinstance(parts, list) else []
        return []

    @staticmethod
    def _extract_parts_from_message_object(result: dict[str, Any]) -> list[Any]:
        """Extract parts list from direct Message object format.

        Args:
            result: Result dict with "parts" key

        Returns:
            Parts list or empty list
        """
        if isinstance(result, dict) and "parts" in result:
            parts = result["parts"]
            return list(parts) if isinstance(parts, list) else []
        return []

    @staticmethod
    def _extract_text_from_task_response(result: dict[str, Any]) -> str:
        """Extract message text from type='task' completion response.

        Args:
            result: Result dict with type="task"

        Returns:
            Concatenated message text from artifacts
        """
        message_text = ""
        status = result.get("status", {})
        if status.get("state") == "completed":
            for artifact in result.get("artifacts", []):
                if artifact.get("type") == "message":
                    message_text += artifact.get("content", "")
        return message_text

    @staticmethod
    def _process_message_part(
        part: Any,
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        """Process a single message part to extract text, UI component, or SubAgentOutput.

        Args:
            part: A single part from the parts list

        Returns:
            Tuple of (text, ui_component, full_subagent_output)
        """
        if not isinstance(part, dict):
            return "", None, None

        # Extract text from text parts
        if part.get("kind") == "text" or part.get("text"):
            return part.get("text", ""), None, None

        # Extract data from data parts
        if part.get("kind") == "data" and part.get("data") is not None:
            data = part["data"]
            if isinstance(data, dict) and "__subagent_output__" in data:
                # Full SubAgentOutput serialised by base_executor
                return "", None, data["__subagent_output__"]
            return "", data, None

        return "", None, None

    @staticmethod
    def _extract_message_parts(
        result: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """Extract message text, UI components, and full output from A2A result.

        Handles three result formats:
        1. type="message" wrapper (legacy/alternate format)
        2. Message object directly (A2A standard servers)
        3. type="task" completion response

        Args:
            result: The result dict from JSON-RPC response

        Returns:
            Tuple of (message_text, ui_components, full_subagent_output)
        """
        message_text = ""
        ui_components: list[dict[str, Any]] = []
        full_subagent_output: dict[str, Any] | None = None

        # Determine result format and extract parts list
        if result.get("type") == "message":
            parts_list = A2AClient._extract_parts_from_message_wrapper(result)
        elif result.get("type") == "task":
            message_text = A2AClient._extract_text_from_task_response(result)
            parts_list = []
        else:
            parts_list = A2AClient._extract_parts_from_message_object(result)

        # Process each part in the parts list
        for part in parts_list:
            part_text, ui_component, subagent_output = A2AClient._process_message_part(part)
            message_text += part_text
            if ui_component is not None:
                ui_components.append(ui_component)
            if subagent_output is not None:
                full_subagent_output = subagent_output

        # Default message if none extracted
        if not message_text:
            message_text = "I processed your request but couldn't generate a response."

        return message_text, ui_components, full_subagent_output

    async def send_message(
        self,
        text: str,
        metadata: dict[str, str],
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> A2AClientResponse:
        """Send a message/send JSON-RPC request.

        Args:
            text: The user's query text
            metadata: Dict with conversationId, correlationId, sourceAgent, etc.
            trace_id: Langfuse trace ID for distributed tracing
            parent_span_id: Langfuse parent span ID for distributed tracing
            extensions: Optional extensions dict with conversationHistory, customerAccounts, etc.

        Returns:
            A2AClientResponse with message text, ui_components, and raw response

        Raises:
            A2AClientError: On network, timeout, or protocol errors
        """
        # Build JSON-RPC request payload
        request_payload = self._build_jsonrpc_request(text, metadata, extensions)

        # Build HTTP headers with trace info
        headers = self._build_headers(trace_id, parent_span_id)

        # Send HTTP request and get response
        response_data = await self._send_http_request(request_payload, headers)

        # Parse JSON-RPC response and validate
        result = self._parse_jsonrpc_result(response_data)

        # Extract message parts from result (handles 3 formats)
        message_text, ui_components, full_subagent_output = self._extract_message_parts(result)

        return A2AClientResponse(
            message=message_text,
            ui_components=ui_components,
            raw_response=response_data,
            full_subagent_output=full_subagent_output,
        )

    async def health_check(self) -> bool:
        """Check if the A2A agent server is healthy.

        Returns:
            True if the server responds with 200 OK, False otherwise
        """
        try:
            # agent_card.url is the JSON-RPC endpoint; derive health URL
            base_url = str(self.agent_card.url).rstrip("/")
            response = await self.http_client.get(f"{base_url}/health", timeout=5.0)
            return bool(response.status_code == HTTPStatus.OK)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http_client.aclose()
