"""Base classes and utilities for agents."""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, NotRequired, TypedDict

from agents import RunResult
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from common.logging.core import logger
from common.models.conversation_manager_types import ActionsEnum, MessageMetadata, RoleType


class AgentSessionContext(TypedDict):
    """Sample session context for a generic agent."""

    current_agent: str
    resume_point: str
    agent_context: dict[str, Any]
    # Conversation status: default "Open", set to "Closed" when a high-risk guardrail triggers
    conversation_status: NotRequired[str]
    # List of guardrail names that have failed during the conversation
    risk_dimensions: NotRequired[list[str]]
    # Per-guardrail risk scores (e.g. {"jailbreak": 0.02, "vulnerability": 0.01})
    risk_scores: NotRequired[dict[str, float]]


class AgentResponseMessage(TypedDict):
    """Standard response message structure."""

    recipient: RoleType
    content: str
    metadata: MessageMetadata | None


class ResponseOrigin(Enum):
    """Enumeration of possible response origins."""

    INPUT_TRIGGER_PRE_CANNED = "input_trigger_pre_canned"
    INPUT_TRIGGER_ERRORED_PRE_CANNED = "input_trigger_errored_pre_canned"
    OUTPUT_REWRITTEN = "output_rewritten"
    OUTPUT_GUARDRAIL_EXECUTION_ERRORED = "output_guardrail_execution_errored"
    OUTPUT_REWRITE_ERRORED = "output_rewrite_errored"
    OUTPUT_REWRITE_ATTEMPTS_EXHAUSTED = "output_rewrite_attempts_exhausted"
    AGENT_EXECUTION = "agent_execution"


class AgentResponseData(BaseModel):
    """Generic agent output response format."""

    response_message: list[AgentResponseMessage]
    metadata: dict[str, Any]
    session_context: AgentSessionContext | None
    action: ActionsEnum | None
    ui_flags: list[dict[str, Any] | str]
    errors: list[str]
    sources: list[dict[str, Any]] = []
    origin: ResponseOrigin = ResponseOrigin.AGENT_EXECUTION

    @staticmethod
    def message_from_content(content: str, recipient: RoleType = "Customer") -> AgentResponseMessage:
        """Helper function to create an AgentResponseMessage from plain text string."""
        return {
            "recipient": recipient,
            "content": content,
            "metadata": {"for": None, "type": None},
        }

    @staticmethod
    def plain_text_ui_element_from_content(content: str) -> dict[str, Any]:
        """Helper function to create a plain text UI element from string."""
        return {
            "widget_type": "plain_text",
            "fallback_content": content,
            "raw_content": content,
        }


class AgentInputMessageFormat(Enum):
    """Represents the possible message input format for agents.

    Attributes:
        OPENAI (str): Format for OpenAI SDK-based agents.
        LANGCHAIN (str): Format for LangChain-based agents.
    """

    OPENAI = "OPENAI"
    LANGCHAIN = "LANGCHAIN"


class AgentBase(ABC):
    """Abstract base class for defining agents.

    All agents must inherit from this class and implement the required abstract methods.

    Methods:
        setup_workflow: Define the workflow for the agent.
        execute: Execute a task synchronously.
        aexecute: Execute a task asynchronously.
        fini: Optional cleanup hook.
    """

    # No explicit initializer required for abstract base class

    @abstractmethod
    def setup_workflow(self) -> None:
        """Set up the workflow for the agent."""

    @abstractmethod
    def execute(
        self,
        task: str | dict[str, Any],
        thread_id: str,
        connection_pool: AsyncConnectionPool,
    ) -> AgentResponseData:
        """Execute a task synchronously."""

    async def aexecute_in_background(
        self,
        task: str | dict[str, Any],
        thread_id: str,
        connection_pool: AsyncConnectionPool,
    ) -> asyncio.Task[Any]:
        """Execute `aexecute` in a background task without blocking."""

        async def _background_execute() -> None:
            try:
                await self.aexecute(task, thread_id, connection_pool)
            except Exception as e:
                logger.error(f"Background execution failed: {e}")
                raise

        return asyncio.create_task(_background_execute())

    @abstractmethod
    async def aexecute(
        self,
        task: str | dict[str, Any],
        thread_id: str,
        connection_pool: AsyncConnectionPool | None,
        parent_span_id: str | None = None,
    ) -> AgentResponseData | Any:
        """Execute a task asynchronously."""

    @staticmethod
    def fini() -> None:
        """Finalize the agent and perform cleanup."""
        # Default no-op implementation to satisfy abstract base class lint rule
        logger.debug("AgentBase.fini called")

    @staticmethod
    def extract_tool_data(
        response: RunResult,
        tools: list[Any],
        tool_calls_with_inputs: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
        """Extract simplified type schemas and execution data for each called tool.

        Args:
            response: The RunResult containing the context with tool execution data.
            tools: List of tool instances available to the agent.
            tool_calls_with_inputs: List of tool call records with input parameters.

        Returns:
            Dict mapping tool name to {param_name: type_string}.
        """
        raw_tool_exec = getattr(response.context_wrapper.context, "tool_execution_data", [])
        tool_execution_data: list[dict[str, Any]] = raw_tool_exec if isinstance(raw_tool_exec, list) else []
        # Build tool input schemas for each called tool
        tool_name_to_schema = {tool.name: tool.params_json_schema for tool in tools}

        tool_input_schemas: dict[str, dict[str, str]] = {}

        for tool_call in tool_calls_with_inputs:
            tool_name = tool_call.get("name", "unknown")
            if tool_name in tool_name_to_schema:
                schema = tool_name_to_schema[tool_name]
                properties = schema.get("properties", {})
                type_map: dict[str, str] = {}
                for param_name, param_info in properties.items():
                    # Extract type, handling anyOf for optional types
                    if "type" in param_info:
                        type_map[param_name] = param_info["type"]
                    elif "anyOf" in param_info:
                        types = [t.get("type", "unknown") for t in param_info["anyOf"]]
                        type_map[param_name] = " | ".join(t for t in types if t)
                    else:
                        type_map[param_name] = "unknown"
                tool_input_schemas[tool_name] = type_map

        return tool_input_schemas, tool_execution_data
