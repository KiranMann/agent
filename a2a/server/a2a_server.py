"""Generic A2A JSON-RPC server for sub-agents (Products, Savings, Home Loans)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from a2a.types import MessageSendParams, SendMessageSuccessResponse
from fastapi import FastAPI, HTTPException, Request
from psycopg_pool import AsyncConnectionPool
from starlette.responses import JSONResponse
from uvicorn import Config as UvicornConfig
from uvicorn import Server

from common.a2a.registry.card_definition import AgentCardDefinition
from common.a2a.server.base_executor import BaseA2AExecutor
from common.configs.agent_config_settings import AgentConfig

logger = logging.getLogger(__name__)


@runtime_checkable
class A2AExecutorProtocol(Protocol):
    """Protocol for A2A executors — any executor passed to A2AServer must implement this."""

    async def execute_message(
        self,
        params: MessageSendParams,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> SendMessageSuccessResponse:
        """Execute an A2A message/send request and return a success response."""
        ...


class A2AServer:
    """Generic A2A JSON-RPC server for any sub-agent executor."""

    def __init__(
        self,
        agent_card_path: str,
        executor: A2AExecutorProtocol,
        agent_label: str = "Agent",
        host: str = "127.0.0.1",
        port: int = 8001,
    ) -> None:
        """Initialize the A2A server.

        Args:
            agent_card_path: Path to the agent card JSON file
            executor: Executor instance implementing A2AExecutorProtocol
            agent_label: Human-readable label for the agent (used in logs/app title)
            host: Server host (default: 127.0.0.1)
            port: Server port (default: 8001)
        """
        self.agent_card_path = Path(agent_card_path)
        self.executor = executor
        self.agent_label = agent_label
        self.host = host
        self.port = port
        self.server: Server | None = None
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        """Create the FastAPI application with A2A endpoints."""
        app = FastAPI(title=f"{self.agent_label} A2A Server", version="1.0.0")

        @app.get("/.well-known/agent.json")
        async def get_agent_card() -> JSONResponse:
            """Serve the agent card at the well-known path."""
            return self._serve_agent_card()

        @app.post("/")
        async def handle_jsonrpc(request: Request) -> JSONResponse:
            """Handle JSON-RPC requests."""
            return await self._handle_jsonrpc(request)

        @app.get("/health")
        async def health_check() -> JSONResponse:
            """Health check endpoint."""
            return JSONResponse(content={"status": "healthy"})

        return app

    def _serve_agent_card(self) -> JSONResponse:
        """Read and serve the agent card JSON.

        Returns:
            JSONResponse with agent card content

        Raises:
            HTTPException: If agent card is missing or malformed
        """
        try:
            if not self.agent_card_path.exists():
                logger.error(f"Agent card not found at: {self.agent_card_path}")
                raise HTTPException(status_code=404, detail="Agent card not found")
            with self.agent_card_path.open("r", encoding="utf-8") as f:
                card_data = json.load(f)
            return JSONResponse(content=card_data)
        except HTTPException:
            # Re-raise HTTPException to preserve correct status code (404)
            raise
        except json.JSONDecodeError as e:
            logger.exception("Failed to parse agent card JSON")
            raise HTTPException(status_code=500, detail="Invalid agent card format") from e
        except Exception as e:
            logger.exception("Failed to serve agent card")
            raise HTTPException(status_code=500, detail="Internal server error") from e

    async def _handle_jsonrpc(self, request: Request) -> JSONResponse:
        """Parse, validate, and dispatch a JSON-RPC message/send request.

        Args:
            request: The incoming FastAPI request

        Returns:
            JSONResponse with JSON-RPC result or error
        """
        body: dict[str, Any] | None = None
        try:
            body = await request.json()
            trace_id = request.headers.get("x-langfuse-trace-id")
            parent_span_id = request.headers.get("x-langfuse-parent-span-id")
            self._validate_jsonrpc_body(body)
            request_id = body.get("id")
            params_dict = body.get("params", {})
            message_params = MessageSendParams(**params_dict)
            # Extract extensions for context parity with in-process execution
            extensions = params_dict.get("extensions")
            response = await self.executor.execute_message(
                params=message_params,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                extensions=extensions,
            )
            return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": response.result.model_dump()})
        except ValueError as e:
            logger.warning(f"Invalid JSON-RPC request: {e}")
            request_id = body.get("id") if isinstance(body, dict) else None
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32600, "message": f"Invalid Request: {e!s}"},
                },
            )
        except Exception:
            logger.exception("JSON-RPC handler error")
            request_id = body.get("id") if isinstance(body, dict) else None
            return JSONResponse(
                status_code=500,
                content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal error"}},
            )

    @staticmethod
    def _validate_jsonrpc_body(body: Any) -> None:
        """Validate that the request body conforms to JSON-RPC 2.0 message/send format.

        Args:
            body: Parsed request body

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        if body.get("jsonrpc") != "2.0":
            raise ValueError("JSON-RPC version must be '2.0'")
        method = body.get("method")
        if method != "message/send":
            raise ValueError(f"Unsupported method: {method}")

    async def start(self) -> None:
        """Start the A2A server."""
        try:
            config = UvicornConfig(
                app=self.app,
                host=self.host,
                port=self.port,
                log_config=None,  # Use existing logging configuration
            )
            self.server = Server(config)

            logger.info(f"Starting A2A server on {self.host}:{self.port}")
            await self.server.serve()

        except Exception:
            logger.exception("Failed to start A2A server")
            raise

    async def stop(self) -> None:
        """Stop the A2A server gracefully."""
        if self.server:
            logger.info("Stopping A2A server gracefully")
            self.server.should_exit = True
            # Give server time to finish ongoing requests
            await asyncio.sleep(0.1)


async def _start_server_background(
    agent_card_path: str,
    executor: A2AExecutorProtocol,
    agent_label: str,
    host: str,
    port: int,
) -> A2AServer:
    """Internal helper to start any A2A server as a background task.

    Args:
        agent_card_path: Path to the agent card JSON file
        executor: Executor implementing A2AExecutorProtocol
        agent_label: Human-readable label for the agent
        host: Server host
        port: Server port

    Returns:
        The A2A server instance with background task started

    Raises:
        Exception: If server initialization fails
    """
    server = A2AServer(agent_card_path, executor, agent_label, host, port)

    # Start the server in a background task and store the reference
    task = asyncio.create_task(server.start())

    # Add task name for easier debugging
    task.set_name(f"a2a_server_{host}_{port}")

    # Add error callback to log unhandled exceptions
    def _log_task_exception(task: asyncio.Task[Any]) -> None:
        """Log any unhandled exceptions from the background task."""
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("A2A server task cancelled")
        except Exception:
            logger.exception("A2A server task failed with unhandled exception")

    task.add_done_callback(_log_task_exception)

    # Store task reference in server instance for later cleanup
    server._background_task = task  # type: ignore[attr-defined]

    # Give the server a moment to start up and check if it failed immediately
    await asyncio.sleep(0.1)
    if task.done():
        # Server failed to start - re-raise the exception
        task.result()

    return server


async def start_agent_server_background(
    card: AgentCardDefinition,
    agent: Any,
    connection_pool: AsyncConnectionPool[Any],
    host: str = "127.0.0.1",
    port: int | None = None,
    agent_card_path: str | None = None,
) -> A2AServer:
    """Start any agent's A2A server from its card definition.

    Generic factory that replaces per-agent server startup functions. Uses
    AgentCardDefinition to derive agent metadata and BaseA2AExecutor to wrap
    the agent instance.

    Args:
        card: Agent card definition containing deployment metadata
        agent: The agent instance to wrap (ProductsAgent, SavingsAgent, HomebuyingAgent, etc.)
        connection_pool: PostgreSQL connection pool for database operations
        host: Server host (default: 127.0.0.1)
        port: Port to bind. Takes precedence over card.port. Falls back to card.port,
            then 8001. Pass explicitly when auto-assigning ports (e.g., from A2AServerManager).
        agent_card_path: Optional explicit path to agent card JSON file. If not provided,
            derives from card.name: "{A2A_CARDS_DIR}/{card.name}.json"

    Returns:
        The A2A server instance with background task started

    Raises:
        Exception: If server initialization fails

    Example:
        >>> from common.a2a.registry.local_registry import LocalAgentRegistry
        >>> registry = LocalAgentRegistry()
        >>> registry.load("common/a2a/agent_cards")
        >>> card = registry.get_agent_card_definition("products-agent")
        >>> server = await start_agent_server_background(
        ...     card=card,
        ...     agent=products_agent_instance,
        ...     connection_pool=connection_pool,
        ...     host="127.0.0.1",
        ... )
    """
    # Use BaseA2AExecutor with card to derive agent_name and resume_point
    executor = BaseA2AExecutor(agent=agent, connection_pool=connection_pool, card=card)

    # Use explicitly provided port, then card.port, then fallback to 8001
    if port is None:
        port = card.port if card.port else 8001

    # Derive agent card path if not explicitly provided
    if agent_card_path is None:
        agent_card_path = f"{AgentConfig.A2A_CARDS_DIR}/{card.name}.json"

    # Derive human-readable label from card name: "products-agent" -> "Products"
    agent_label = card.name.removesuffix("-agent").replace("-", " ").title()

    return await _start_server_background(agent_card_path, executor, agent_label, host, port)
