"""Langfuse Utility Module.

This module provides utility functions and classes for integrating with Langfuse server v2
for observability and telemetry in agent workflows. It includes:

- AgentRunHooks: A class that extends RunHooks to provide Langfuse integration for
  tracing agent execution, tool usage, and handoffs between agents.

- update_tool_observation: A function that updates the observation created in on_tool_start
  with input data

- link_lf_trace: A function that links a Langfuse trace to a dataset item

"""

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from agents import Agent, ModelSettings, RunContextWrapper, RunHooks, Tool
from langfuse import Langfuse
from langfuse.decorators import langfuse_context

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.tools import ToolContext

if TYPE_CHECKING:
    from langfuse.client import StatefulSpanClient

use_langfuse = AppConfig.LANGFUSE_FLAG

lf = None


def get_langfuse_client() -> Langfuse:
    """Singleton getter for Langfuse client to ensure that only one instance of the Langfuse client is created and reused throughout the application.

    Returns:
        Langfuse: A configured Langfuse client instance

    Raises:
        EnvironmentError: If required configuration values are missing
    """
    # Ensure required environment variables are set
    # pylint: disable=invalid-name
    langfuse_host = AppConfig.LANGFUSE_HOST
    langfuse_public_key = AppConfig.LANGFUSE_PUBLIC_KEY
    langfuse_secret_key = AppConfig.LANGFUSE_SECRET_KEY
    # pylint: enable=invalid-name

    if not langfuse_host or not langfuse_public_key or not langfuse_secret_key:
        raise OSError("Missing required environment variables: LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY")

    # Initialize Langfuse client
    client = Langfuse(
        host=langfuse_host,
        public_key=langfuse_public_key,
        secret_key=langfuse_secret_key,
    )
    return client


if use_langfuse:
    lf = get_langfuse_client()


# -------------------- Custom Agent Hooks --------------------
class AgentRunHooks(RunHooks):
    """Custom hooks for agent runs that integrate with Langfuse for telemetry.

    This class extends RunHooks to provide Langfuse integration for tracing agent
    execution, tool usage, and handoffs between agents. It captures metrics and
    contextual information at various stages of the agent's execution lifecycle.

    Attributes:
        conversation_id: Unique identifier for the conversation
        agent_span: Reference to the current agent span in Langfuse
        function_span: Reference to the current function span in Langfuse
        trace: Reference to the Langfuse trace
        parent_span_id: Optional ID of a parent span for hierarchical tracing
    """

    def __init__(
        self,
        conversation_id: str,
        parent_span_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
    ):
        """Initialize AgentRunHooks with conversation tracking and Langfuse integration.

        Args:
            conversation_id: Unique identifier for the conversation
            parent_span_id: Optional ID of a parent span for hierarchical tracing
            user_id: Optional user identifier for the conversation
            model_name: Optional model name override, defaults to Config.AGENT_LLM
        """
        self.conversation_id = conversation_id
        self.agent_span = None
        self.function_span: list[StatefulSpanClient] = []
        self.trace_id = None
        self.user_id = user_id
        self.trace = None
        self.parent_span_id = parent_span_id
        self.model_name = model_name or AppConfig.AGENT_LLM  # Use provided model name or fallback to config
        if use_langfuse and lf is not None:
            self.trace_id = langfuse_context.get_current_trace_id()
            self.trace = lf.trace(id=self.trace_id, user_id=self.user_id)
            self._span_locks: dict[str, asyncio.Lock] = {}
            self._lock_creation_lock = asyncio.Lock()  # Protect lock creation

    async def _get_lock(self, tool_name: str) -> asyncio.Lock:
        """Safely get or create a lock for the given tool name."""
        if tool_name not in self._span_locks:
            async with self._lock_creation_lock:
                # Double-check pattern to avoid race condition
                if tool_name not in self._span_locks:
                    self._span_locks[tool_name] = asyncio.Lock()
        return self._span_locks[tool_name]

    async def on_agent_start(
        self,
        context: RunContextWrapper,  # noqa: ARG002
        agent: Agent,
    ) -> None:
        if use_langfuse:
            span_args = {
                "name": f"Agent run: {agent.name}",
                "input": "Empty span, fix this in `util_langfuse.py`",
                "output": "Empty span, fix this in `util_langfuse.py`",
                "metadata": {"attributes": {"name": agent.name, "agent_name": agent.name}},
            }

            # Use parent_span_id if provided
            if self.parent_span_id:
                span_args["parent_observation_id"] = self.parent_span_id

            if self.trace is not None:
                span = self.trace.span(**span_args)
                self.agent_span = span
            llm_model_settings = ModelSettings(
                metadata={
                    "generation_name": f"Chat completion with {self.model_name}",
                    "trace_name": AppConfig.AGENT,
                    "session_id": self.conversation_id,
                    "agent_name": agent.name,
                    "trace_id": self.trace_id if self.trace_id else "",
                    "existing_trace_id": self.trace_id if self.trace_id else "",
                    "parent_observation_id": (self.agent_span.id if self.agent_span is not None else ""),
                }
            )
            agent.model_settings = agent.model_settings.resolve(llm_model_settings)

    async def on_agent_end(
        self,
        context: RunContextWrapper,
        agent: Agent,  # noqa: ARG002
        output: Any,  # noqa: ARG002
    ) -> None:
        if use_langfuse and self.agent_span is not None:
            self.agent_span.end()  # type: ignore[unreachable]
            self.agent_span = None

        # Clear langfuse spans in context as it is not required after the agent run
        if hasattr(context, "context") and hasattr(context.context, "langfuse_spans"):
            context.context.langfuse_spans = {}

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Tool,
    ) -> None:
        if use_langfuse and self.trace is not None:
            # Create a span for the tool run
            span = self.trace.span(
                parent_observation_id=(self.agent_span.id if self.agent_span is not None else ""),
                name=f"Function: {tool.name}",
                metadata={"attributes": {"name": tool.name, "agent_name": agent.name}},
            )
            self.function_span.append(span)
            if tool.name not in context.context.langfuse_spans:
                context.context.langfuse_spans[tool.name] = []
            context.context.langfuse_spans[tool.name].append(span)

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Agent,  # noqa: ARG002
        tool: Tool,
        result: str,
    ) -> None:
        if use_langfuse and self.function_span:
            lock = await self._get_lock(tool.name)
            async with lock:
                # TODO: We need to have a way to get the correct span
                # Currently, there is no way to disambiguate tools with the same name.
                # Known limitation, and we raise an issue for fix later.
                span_to_update: StatefulSpanClient = context.context.langfuse_spans[tool.name][0]
                existing_metadata = getattr(span_to_update, "metadata", {}) or {}
                attributes = existing_metadata.get("attributes", {})
                attributes["output"] = result
                existing_metadata["attributes"] = attributes
                span_to_update.update(
                    output=result,
                    metadata=existing_metadata,
                )
                try:
                    self.function_span.remove(span_to_update)
                    context.context.langfuse_spans[tool.name].remove(span_to_update)
                except Exception as e:
                    raise RuntimeError(f"Problem in here {e}") from e
                span_to_update.end()

    async def on_handoff(
        self,
        context: RunContextWrapper,  # noqa: ARG002
        from_agent: Agent,
        to_agent: Agent,
    ) -> None:
        if use_langfuse and self.trace is not None:
            span = self.trace.span(
                parent_observation_id=(self.agent_span.id if self.agent_span is not None else ""),
                name=f"Handoff: {from_agent.name} to {to_agent.name}",
                metadata={
                    "attributes": {
                        "from_agent": from_agent.name,
                        "to_agent": to_agent.name,
                        "agent_name": from_agent.name,
                    }
                },
            )
            span.end()


def update_tool_observation(
    wrapper: RunContextWrapper[ToolContext],
    tool_name: str,
    input_data: dict[str, Any] | None = None,
) -> None:
    """Updates the observation created in on_tool_start instead of creating a new one.

    Args:
        wrapper: The context wrapper containing model context with function spans
        tool_name: The name of the tool whose span should be updated
        input_data: Optional input data to include in the observation
    """
    if input_data is None:
        input_data = {}
    # Check if we have a span ID from on_tool_start
    if (
        use_langfuse
        and hasattr(wrapper.context, "langfuse_spans")
        and isinstance(wrapper.context.langfuse_spans, dict)
        and bool(wrapper.context.langfuse_spans)
    ):
        try:
            # Currently, there is no way to disambiguate tools with the same name.
            # Known limitation, and we raise an issue for fix later.
            # We add input to the first tool call that has no input set
            spans = [
                span
                for span in wrapper.context.langfuse_spans[tool_name]
                if (getattr(span, "metadata", {}).get("attributes", {}).get("input", {}) == {})
            ]
            # We use FIFO logic to update the least recent span with tool observation
            # This assumes we pretty much only call update_tool_observation at the start
            span = spans[-1]
        except (IndexError, KeyError) as e:
            raise ValueError(f"No spans available for tool '{tool_name}'") from e
        if span:
            existing_metadata = getattr(span, "metadata", {}) or {}
            attributes = existing_metadata.get("attributes", {})
            attributes["input"] = input_data
            existing_metadata["attributes"] = attributes
            span.update(input=input_data, metadata=existing_metadata)


def update_tool_observation_metadata(
    wrapper: RunContextWrapper,
    tool_name: str,
    metadata_data: dict[str, Any] | None = None,
) -> None:
    """Updates the observation created in on_tool_start by adding data to metadata instead of input.

    This function is useful when you want to add contextual information to the span's metadata
    rather than treating it as input data.

    Args:
        wrapper: The context wrapper containing model context with function spans
        tool_name: The name of the tool whose span should be updated
        metadata_data: Optional metadata data to include in the observation attributes
    """
    if metadata_data is None:
        metadata_data = {}
    # Check if we have a span ID from on_tool_start
    if (
        use_langfuse
        and hasattr(wrapper.context, "langfuse_spans")
        and isinstance(wrapper.context.langfuse_spans, dict)
        and bool(wrapper.context.langfuse_spans)
    ):
        try:
            # Currently, there is no way to disambiguate tools with the same name.
            # Known limitation, and we raise an issue for fix later.
            # We add metadata to the first tool call that has no custom metadata set
            spans = [
                span
                for span in wrapper.context.langfuse_spans[tool_name]
                if not (getattr(span, "metadata", {}).get("attributes", {}).get("custom_metadata", {}))
            ]
            # We use FIFO logic to update the least recent span with tool observation
            # This assumes we pretty much only call update_tool_observation_metadata at the start
            span = spans[-1] if spans else wrapper.context.langfuse_spans[tool_name][-1]
        except (IndexError, KeyError) as e:
            raise ValueError(f"No spans available for tool '{tool_name}'") from e
        if span:
            existing_metadata = getattr(span, "metadata", {}) or {}
            attributes = existing_metadata.get("attributes", {})
            # Add the metadata_data to a custom_metadata field in attributes
            attributes["custom_metadata"] = metadata_data
            existing_metadata["attributes"] = attributes
            span.update(metadata=existing_metadata)


# -------------------- LangGraph Tracing Utilities --------------------
def create_traced_node(node_name: str, node_func: Any) -> Any:
    """Creates a traced wrapper for LangGraph nodes.

    Args:
        node_name: Name for the span (e.g., "chatbot_node", "tool_node")
        node_func: The original node function to wrap

    Returns:
        Wrapped function with Langfuse tracing
    """

    def traced_node(state: dict[str, Any]) -> Any:
        span = None
        if use_langfuse and lf:
            trace_id = langfuse_context.get_current_trace_id()
            lf_trace = lf.trace(id=trace_id)
            span = lf_trace.span(
                name=node_name,
                input={
                    "state_keys": list(state.keys()),
                    "messages_count": len(state.get("messages", [])),
                },
                metadata={"attributes": {"node_type": node_name}},
            )

        result = node_func(state)

        if span:
            span.update(
                output={"result_keys": (list(result.keys()) if isinstance(result, dict) else str(type(result)))}
            )
            span.end()

        return result

    return traced_node


def create_traced_tool_node(tools: list[Any]) -> Any:
    """Creates a traced tool node for LangGraph workflows.

    Args:
        tools: List of tools to include in the ToolNode

    Returns:
        Traced tool node function
    """
    from langgraph.prebuilt import (  # noqa: PLC0415
        ToolNode,  # lazy import to avoid startup crash from langgraph version mismatch
    )

    tool_node = ToolNode(tools=tools)

    def traced_tool_node(state: dict[str, Any]) -> Any:
        tool_span = None
        if use_langfuse and lf:
            trace_id = langfuse_context.get_current_trace_id()
            lf_trace = lf.trace(id=trace_id)
            tool_span = lf_trace.span(
                name="tool_node",
                input={
                    "messages_count": len(state.get("messages", [])),
                    "tool_calls": (
                        str(state["messages"][-1].tool_calls)
                        if state.get("messages") and hasattr(state["messages"][-1], "tool_calls")
                        else "none"
                    ),
                },
                metadata={"attributes": {"node_type": "tools"}},
            )

        result = tool_node.invoke(state)

        if tool_span:
            tool_span.update(
                output={
                    "tool_results": (str(result["messages"][-1].content) if result.get("messages") else "no_result")
                }
            )
            tool_span.end()

        return result

    return traced_tool_node


def link_lf_trace(
    conversation_id: str,
    trace_id_hex: str,
    beginning_of_convo_flag: bool,
    run_name: str = "default_run",
) -> None:
    """Link a Langfuse trace to a dataset item for conversation tracking and analysis.

    This function establishes a connection between a Langfuse trace and a dataset item,
    enabling conversation-level analytics and evaluation. It handles the complete workflow
    of dataset management and trace linking with proper error handling.

    Workflow:
    1. Ensures the target dataset exists (creates if missing)
    2. Conditionally creates or retrieves a dataset item based on conversation state:
       - If beginning_of_convo_flag=True: Creates a new dataset item with conversation_id
       - If beginning_of_convo_flag=False: Retrieves existing dataset item by conversation_id
    3. Links the dataset item to the specified trace for tracking and evaluation

    Args:
        conversation_id (str): Unique identifier for the conversation. Used as the dataset
            item ID to group all traces from the same conversation together.
        trace_id_hex (str): Langfuse trace ID in hexadecimal format that will be linked
            to the dataset item.
        beginning_of_convo_flag (bool): Controls dataset item creation behavior:
            - True: Creates a new dataset item (use for first trace in conversation)
            - False: Retrieves existing dataset item (use for subsequent traces)
        run_name (str, optional): Name identifier for the run when linking the trace.
            Defaults to "default_run". Used for organizing multiple runs within the same
            dataset item.

    Returns:
        None: Function performs side effects (dataset operations) but returns nothing.
            Early returns None if Langfuse is disabled or client is unavailable.

    Raises:
        No exceptions are raised directly. All exceptions during dataset operations
        are caught and logged at debug level to prevent disruption of main workflow.

    Note:
        - Requires Langfuse to be enabled (use_langfuse=True) and client initialized
        - Uses the dataset name from Config.LANGFUSE_DATASET_NAME
        - Silently handles cases where dataset or dataset items already exist
        - All errors are logged but do not interrupt execution
    """
    if use_langfuse is None or lf is None:
        return None
    # Check if dataset exists, create if it doesn't
    with contextlib.suppress(Exception):
        lf.create_dataset(
            name=AppConfig.LANGFUSE_DATASET_NAME,
            description="Dataset for cards agents conversation",
        )

    # If beginning of conversation, create a new dataset it
    if beginning_of_convo_flag:
        try:
            # Create a new dataset item with the conversation_id
            lf.create_dataset_item(
                dataset_name=AppConfig.LANGFUSE_DATASET_NAME,
                id=conversation_id,
            )
            dataset_item = lf.get_dataset_item(conversation_id)
            # Link the newly created dataset item
            dataset_item.link(
                trace_or_observation=None,
                trace_id=trace_id_hex,
                run_name=run_name,
            )
        except Exception as create_error:
            logger.debug(f"Error creating dataset item: {create_error}")

    # If not beginning of conversation, get dataset item
    else:
        try:
            # Get dataset item corresponding to conversation_id
            dataset_item = lf.get_dataset_item(conversation_id)
            if dataset_item is not None:
                dataset_item.link(
                    trace_or_observation=None,
                    trace_id=trace_id_hex,
                    run_name=run_name,
                )
        except Exception as dataset_error:
            logger.debug(f"Error with getting or linking dataset item: {dataset_error}")


def update_trace_feedback(
    trace_id: str,
    session_id: str,
    customer_id: str,
    rating: int,
    comments: str | None = None,
) -> None:
    """Update feedback score for a Langfuse trace with security validation.

    This function updates the feedback score for a specific Langfuse trace after
    validating that the requesting customer has permission to modify the trace.
    It ensures that only the original customer who created the trace can provide
    feedback, maintaining data security and integrity.

    Security Features:
    - Validates trace ownership by checking session_id and customer_id match
    - Only updates feedback if the trace belongs to the requesting customer
    - Gracefully handles cases where Langfuse is disabled or unavailable

    Args:
        trace_id (str): The unique identifier of the Langfuse trace to update
        session_id (str): The conversation session ID for validation
        customer_id (str): The customer ID for ownership validation
        rating (int): The feedback rating value (-1, 0, or 1)
        comments (Optional[str], optional): Additional feedback comments. Defaults to None.

    Returns:
        None: This function performs side effects only and does not return values.
              Returns early if Langfuse is disabled or client is unavailable.

    Raises:
        No exceptions are raised. All errors are caught and logged for observability
        while preventing disruption of the main feedback workflow.

    Note:
        - Requires Langfuse to be enabled and properly configured
        - Only updates traces where session_id and user_id match the provided values
        - Failed updates are logged at debug level but do not interrupt execution
    """
    if use_langfuse is None or lf is None:
        logger.debug("Langfuse not available, skipping trace feedback update")
        return None

    logger.debug(f"Attempting to update Langfuse trace feedback - Trace: {trace_id}")

    try:
        # Fetch the trace to validate ownership
        trace = lf.fetch_trace(trace_id)
        logger.debug(f"Retrieved trace for validation - Session: {trace.data.session_id}, User: {trace.data.user_id}")

        # Validate that the requesting customer owns this trace
        if trace.data.session_id == session_id and trace.data.user_id == customer_id:
            logger.debug(f"Trace ownership validated, updating feedback score: {rating}")
            lf.score(name="feedback", trace_id=trace_id, value=rating, comment=comments)
            logger.info(f"Successfully updated Langfuse trace feedback - Trace: {trace_id}, Rating: {rating}")
        else:
            logger.warning(
                f"Trace ownership validation failed - Expected session: {session_id}, "
                f"customer: {customer_id}, but trace has session: {trace.data.session_id}, "
                f"user: {trace.data.user_id}"
            )
    except Exception as e:
        logger.warning(f"Error updating Langfuse trace feedback for trace {trace_id}: {e}")
        return None
