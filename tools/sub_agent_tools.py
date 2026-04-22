"""Sub-agent tools for the financial companion agent."""

import copy
import json
from typing import Any

from agents import FunctionTool, RunContextWrapper, function_tool
from langfuse.decorators import langfuse_context
from psycopg_pool import AsyncConnectionPool

from apps.companion.all_agents.agent_availability import is_a2a_enabled, is_a2a_routing_enabled
from apps.companion.all_agents.task_agents.homeloans_agent.homeloans_agent import HomebuyingAgent
from apps.companion.all_agents.task_agents.payment_agent import PaymentAgent
from apps.companion.all_agents.task_agents.products_agent.products_agent import ProductsAgent
from apps.companion.all_agents.task_agents.savings_agent.savings_agent import SavingsAgent
from common.a2a.client.a2a_client import A2AClient, A2AClientError
from common.a2a.registry.card_definition import AgentCardDefinition
from common.a2a.registry.local_registry import LocalAgentRegistry
from common.configs.agent_config_settings import AgentConfig
from common.logging.core import logger
from common.models.domain_descriptions import (
    HOMEBUYING_ROLE_DESCRIPTION,
    PRODUCTS_ROLE_DESCRIPTION,
    SAVINGS_ROLE_DESCRIPTION,
)
from common.models.sub_agent_output import SubAgentOutput
from common.tools import ToolContext
from common.tools.conversation_tools import apply_freshness_filter
from common.tools.rag_tools import RAGError
from common.tools.util_langfuse import update_tool_observation, use_langfuse


def _sub_agent_tool_error_handler(
    ctx: RunContextWrapper[ToolContext],  # noqa: ARG001
    error: Exception,
) -> str:
    """Custom error handler for sub-agent tools that preserves RAGError exceptions.

    This allows RAGError to propagate to the principal agent for proper fallback handling,
    while converting other exceptions to user-friendly error messages.

    Args:
        ctx: The run context wrapper
        error: The exception that occurred

    Returns:
        Error message string for non-RAG errors

    Raises:
        RAGError: Re-raises RAGError to allow propagation to principal agent
    """
    if isinstance(error, RAGError):
        # Re-raise RAGError to allow it to propagate to principal agent
        raise error

    # For all other exceptions, return a generic error message
    return f"An error occurred while running the tool. Please try again. Error: {error!s}"


def extract_sub_agent_context(
    wrapper: RunContextWrapper[ToolContext],
    content: dict[str, str],
    agent_name: str,
    resume_point: str,
    tool_name: str,
) -> tuple[dict[str, Any], str, AsyncConnectionPool, str | None, str | None, str]:
    """Extract common context needed by all sub-agents.

    Args:
        wrapper: The RunContextWrapper containing tool context
        content: The formatted request content
        agent_name: Name of the target agent (e.g., "payment_agent")
        resume_point: Resume point for the session context
        tool_name: Name of the tool for langfuse spans

    Returns:
        Tuple of (task_dict, thread_id, connection_pool, parent_span_id, trace_id, agent_name)

    Raises:
        ValueError: If connection pool is None
    """
    # Get current trace context to pass to sub-agent
    trace_id = None
    parent_span_id = None
    if use_langfuse:
        trace_id = langfuse_context.get_current_trace_id()
        if hasattr(wrapper.context, "langfuse_spans") and tool_name in wrapper.context.langfuse_spans:
            try:
                # Currently, there is no way to disambiguate tools with the same name.
                # Known limitation, and we raise an issue for fix later.
                parent_span_id = wrapper.context.langfuse_spans[tool_name][0].id
            except (IndexError, KeyError) as e:
                raise ValueError(f"No spans available for tool '{tool_name}'") from e

    # Get conversation context from wrapper
    conversation_history = wrapper.context.conversation_history or []
    thread_id = wrapper.context.thread_id or "sub_session"
    connection_pool = wrapper.context.connection_pool
    cif_code = wrapper.context.cif_code
    netbank_id = wrapper.context.netbank_id
    dptoken = wrapper.context.dptoken

    # Handle case where connection_pool might be None
    if connection_pool is None:
        raise ValueError(f"Failed to extract sub-agent context for {agent_name}: No connection pool available")

    # Create a copy of conversation history for this sub-agent only
    sub_agent_conversation = copy.deepcopy(conversation_history)
    full_conversation = sub_agent_conversation

    # Extract cached account context from principal agent's ToolContext
    cached_agent_context: dict[str, Any] = {}
    if hasattr(wrapper.context, "customer_accounts") and wrapper.context.customer_accounts:
        cached_agent_context["customer_accounts"] = wrapper.context.customer_accounts
    if hasattr(wrapper.context, "account_context_loaded"):
        cached_agent_context["account_context_loaded"] = wrapper.context.account_context_loaded
    if hasattr(wrapper.context, "account_service_used") and wrapper.context.account_service_used:
        cached_agent_context["account_service_used"] = wrapper.context.account_service_used

    # Create task for sub-agent with complete conversation history and cached account context
    task = {
        "conversation_history": full_conversation,
        "context_request": content,
        "session_context": {
            "current_agent": agent_name,
            "resume_point": resume_point,
            "agent_context": cached_agent_context,  # Pass cached account context from principal agent
        },
        "cif_code": cif_code,
        "netbank_id": netbank_id,
        "dptoken": dptoken,
    }

    return task, thread_id, connection_pool, parent_span_id, trace_id, agent_name


def _extract_ui_flags(
    result: SubAgentOutput,
    wrapper: RunContextWrapper[ToolContext],
    ui_component_queue: Any = None,
) -> None:
    """Extracts UI components from the sub-agent response and adds it to the principal agent's context,
    and also pushes them to the shared UI component queue if provided.
    Note that this function modifies the wrapper context in place.

    Args:
        result (SubAgentOutput): The sub-agent response data.
        wrapper (RunContextWrapper[ToolContext]): The wrapper context to update.
        ui_component_queue: Shared queue for UI component aggregation (optional).
    """  # noqa: D205
    if not result.ui_components:
        return

    if not hasattr(wrapper.context, "ui_components"):
        wrapper.context.ui_components = []

    # Filter to only include dictionaries,
    # exclude strings since this means they were not correctly formed
    dict_ui_flags = [flag for flag in result.ui_components if isinstance(flag, dict)]

    # Add to wrapper context for backward compatibility
    wrapper.context.ui_components.extend(dict_ui_flags)

    # Push to shared queue if provided
    if ui_component_queue is not None:
        try:
            for ui_flag in dict_ui_flags:
                ui_component_queue.put_nowait(ui_flag)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Fallback: if ui_component_queue is not a proper asyncio.Queue,
            # treat it as a list and extend it
            if hasattr(ui_component_queue, "extend"):
                ui_component_queue.extend(dict_ui_flags)
            else:
                # Log the error but don't fail the operation
                logger.warning(f"Failed to add UI components to queue: {e}")


def _validate_ui_flag(ui_flag: Any, agent_name: str) -> tuple[str | None, str | None]:
    """Validate and extract widget information from UI flag.

    Args:
        ui_flag: The UI flag to validate
        agent_name: Name of the agent for error logging

    Returns:
        Tuple of (widget_type, widget_id) or (None, None) if invalid
    """
    if not isinstance(ui_flag, dict):
        logger.warning(f"Invalid UI flag from {agent_name}: {ui_flag}. Expected dict, got {type(ui_flag)}. Skipping.")
        return None, None

    widget_id = ui_flag.get("widget_id", None)
    widget_type = ui_flag.get("widget_type", None)

    if widget_id is None or widget_type is None:
        logger.warning(f"Invalid UI flag from {agent_name}: {ui_flag}. Missing widget_id or widget_type. Skipping.")
        return None, None

    return widget_type, widget_id


def append_ui_components_to_response(
    response: str,
    ui_flags: list[Any],
    agent_name: str,
) -> str:
    """Append UI components to the response text.

    Args:
        response: The base response text
        ui_flags: List of UI flags to append
        agent_name: Name of the agent for error logging

    Returns:
        Response text with UI components appended
    """
    if not ui_flags:
        return response

    response += "\n\nThe following UI components were also generated:"

    for ui_flag in ui_flags:
        widget_type, widget_id = _validate_ui_flag(ui_flag, agent_name)
        if widget_type is None or widget_id is None:
            continue

        response += f"""\n\n<ui_component type="{widget_type}" id="{widget_id}">
{json.dumps(ui_flag, indent=4)}
</ui_component>"""

    return response


def _handle_context_extraction_error(e: ValueError, agent_name: str) -> str:
    """Handle errors during context extraction.

    Args:
        e: The ValueError that occurred
        agent_name: Name of the agent for error messages

    Returns:
        Error message for the user
    """
    logger.warning(str(e))
    service_name = agent_name.replace("_agent", "").capitalize()
    return f"{service_name} service temporarily unavailable - no database connection"


def _set_trace_context_if_available(
    agent: HomebuyingAgent | ProductsAgent | SavingsAgent | PaymentAgent,
    trace_id: str | None,
    parent_span_id: str | None,
) -> None:
    """Set trace context on agent if available.

    Args:
        agent: The sub-agent instance
        trace_id: The trace ID to set
        parent_span_id: The parent span ID to set
    """
    if trace_id and hasattr(agent, "set_trace_context"):
        agent.set_trace_context(trace_id, parent_span_id)


async def _handle_sub_agent_request(
    wrapper: RunContextWrapper[ToolContext],
    request: str,
    context: str,
    agent: HomebuyingAgent | ProductsAgent | SavingsAgent | PaymentAgent,
    agent_name: str,
    tool_name: str,
    *,
    ui_component_queue: Any = None,
) -> str:
    """Generic handler for sub-agent requests to eliminate code duplication.

    Args:
        wrapper: The RunContextWrapper containing tool context
        request: The original user request
        context: Additional context for the sub-agent
        agent: The sub-agent instance to use
        agent_name: Name of the agent for error messages and context
        tool_name: Name of the tool for langfuse spans
        ui_component_queue: Shared queue for UI component aggregation (optional)

    Returns:
        The response content from the sub-agent

    Raises:
        Exception: If sub-agent execution fails
    """
    update_tool_observation(
        wrapper,
        tool_name,
        {"Request": request, "Context": context},
    )

    content = {"Request": request, "Context": context}
    try:
        # Extract common sub-agent context
        try:
            task, thread_id, connection_pool, parent_span_id, trace_id, _ = extract_sub_agent_context(
                wrapper,
                content,
                agent_name,
                f"Start of {agent_name} session",
                tool_name,
            )
        except ValueError as e:
            return _handle_context_extraction_error(e, agent_name)

        # Pass trace context to sub-agent if available
        _set_trace_context_if_available(agent, trace_id, parent_span_id)

        result = await agent.aexecute(task, thread_id, connection_pool, parent_span_id)

        # Process result and format response
        return _process_sub_agent_result(result, agent_name, wrapper, ui_component_queue)

    except (ValueError, RuntimeError) as e:
        return f"{agent_name} service error: {e!s}"


def _process_sub_agent_result(
    result: SubAgentOutput | Any,
    agent_name: str,
    wrapper: RunContextWrapper[ToolContext],
    ui_component_queue: Any,
) -> str:
    """Process and format sub-agent execution result.

    Args:
        result: The result from agent execution
        agent_name: Name of the agent for error messages
        wrapper: The RunContextWrapper containing tool context
        ui_component_queue: Shared queue for UI component aggregation

    Returns:
        Formatted response text with UI components
    """
    # Type assertion to help mypy understand the return type
    if not isinstance(result, SubAgentOutput):
        logger.error(f"Unexpected result type from {agent_name}: {type(result)}")
        return f"{agent_name} returned invalid response type"

    _extract_ui_flags(result, wrapper, ui_component_queue)

    if not result.message or len(result.message.strip()) == 0:
        return f"{agent_name} service returned no response"

    # Get just the text response
    response = result.message

    # Add UI components to the response
    response = append_ui_components_to_response(response, result.ui_components or [], agent_name)

    return response


def _get_a2a_parent_span_id(wrapper: RunContextWrapper[ToolContext], tool_name: str) -> str | None:
    """Extract the Langfuse parent span ID for the given tool from wrapper context.

    Args:
        wrapper: The RunContextWrapper containing tool context
        tool_name: The tool name to look up in langfuse_spans

    Returns:
        Span ID string or None if unavailable
    """
    if not hasattr(wrapper.context, "langfuse_spans"):
        return None
    spans = wrapper.context.langfuse_spans
    if tool_name not in spans:
        return None
    try:
        return str(spans[tool_name][0].id)
    except (IndexError, KeyError):
        logger.warning(f"Could not retrieve parent span for A2A request via tool '{tool_name}'")
        return None


def _collect_a2a_ui_components(
    ui_components: list[Any],
    wrapper: RunContextWrapper[ToolContext],
    ui_component_queue: Any,
) -> None:
    """Push A2A response UI components to the queue and wrapper context.

    Args:
        ui_components: List of UI component dicts from A2A response
        wrapper: The RunContextWrapper to update
        ui_component_queue: Optional asyncio queue for UI components
    """
    if not ui_components:
        return
    dict_components = [c for c in ui_components if isinstance(c, dict)]
    if ui_component_queue is not None:
        for comp in dict_components:
            ui_component_queue.put_nowait(comp)
    if not hasattr(wrapper.context, "ui_components"):
        wrapper.context.ui_components = []
    wrapper.context.ui_components.extend(dict_components)


def _prepare_a2a_conversation_history(
    conversation_history: list[Any],
    request: str,
) -> tuple[list[dict[str, Any]], str]:
    """Prepare conversation history for A2A request.

    Applies freshness filter to remove stale messages, then replaces last user
    message with the specific sub-agent request, matching the in-process
    construct_sub_task behavior.

    Args:
        conversation_history: Original conversation history
        request: The domain-specific rewritten request

    Returns:
        Tuple of (modified_history_dicts, original_user_query)
    """
    # Apply freshness filter using shared utility function
    filtered_history, freshness_message = apply_freshness_filter(
        [dict(msg) if not isinstance(msg, dict) else msg for msg in conversation_history]
    )

    # Project to SDK-compatible dicts — only `role` and `content` are included
    conversation_history_dicts: list[dict[str, Any]] = [
        {"role": msg["role"], "content": msg["content"]} for msg in filtered_history
    ]

    # Prepend the freshness notice as the first system message if stale messages were removed
    if freshness_message:
        conversation_history_dicts.insert(0, freshness_message)

    # Replace last user message with the specific sub-agent request
    original_user_query = ""
    if conversation_history_dicts:
        last_message = conversation_history_dicts[-1]
        original_user_query = str(last_message.get("content", ""))
        conversation_history_dicts[-1] = {
            "role": last_message.get("role", "user"),
            "content": request,
        }
    else:
        conversation_history_dicts = [{"role": "user", "content": request}]

    return conversation_history_dicts, original_user_query


def _build_a2a_request_context(
    wrapper: RunContextWrapper[ToolContext],
    conversation_history_dicts: list[dict[str, Any]],
    original_user_query: str,
    thread_id: str,
    cif_code: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build extensions and metadata for A2A request.

    Args:
        wrapper: The RunContextWrapper containing tool context
        conversation_history_dicts: Prepared conversation history
        original_user_query: Original user message content
        thread_id: Thread identifier
        cif_code: Customer identification code

    Returns:
        Tuple of (extensions, metadata) dicts
    """
    extensions: dict[str, Any] = {
        "conversation_history": conversation_history_dicts,
        "customer_accounts": getattr(wrapper.context, "customer_accounts", None),
        "account_context_loaded": getattr(wrapper.context, "account_context_loaded", False),
        "account_service_used": getattr(wrapper.context, "account_service_used", None),
        "netbank_id": wrapper.context.netbank_id or "",
        "dptoken": wrapper.context.dptoken,
        "original_user_query": original_user_query,
    }

    metadata: dict[str, str] = {
        "conversation_id": thread_id,
        "correlation_id": thread_id,
        "source_agent": "financial-companion",
        "customer_id": cif_code,
        "session_id": thread_id,
    }

    return extensions, metadata


async def _send_and_process_a2a_response(
    client: A2AClient,
    full_request: str,
    metadata: dict[str, str],
    extensions: dict[str, Any],
    trace_id: str | None,
    parent_span_id: str | None,
    domain_name: str,
) -> SubAgentOutput:
    """Send A2A message and process response.

    Args:
        client: A2AClient instance
        full_request: Complete request text
        metadata: Request metadata
        extensions: Request extensions
        trace_id: Langfuse trace ID
        parent_span_id: Langfuse parent span ID
        domain_name: Domain name for logging

    Returns:
        SubAgentOutput reconstructed from A2A response

    Raises:
        A2AClientError: If the remote A2A call fails
    """
    logger.info(
        f"Routing {domain_name} request via A2A: {full_request[:100]}...",
        extra={"domain": domain_name, "transport": "a2a"},
    )

    response = await client.send_message(
        text=full_request,
        metadata=metadata,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        extensions=extensions,
    )

    if response.full_subagent_output:
        result = SubAgentOutput(**response.full_subagent_output)
    else:
        result = SubAgentOutput(
            message=response.message,
            ui_components=response.ui_components or [],
            sources=[],
        )

    logger.info(
        f"Successfully executed {domain_name} agent via A2A",
        extra={"domain": domain_name, "transport": "a2a"},
    )

    return result


def build_tool_description_from_card(card_definition: AgentCardDefinition) -> str:
    """Build a tool description for LLM routing from an agent card definition.

    Constructs a structured description from the card's routing metadata
    (short description, boundaries, query examples, handoff notes, and trigger
    keywords) so the LLM has consistent routing guidance driven by the agent card.

    Args:
        card_definition: The enriched agent card definition containing routing metadata.

    Returns:
        Formatted tool description string derived from the card's routing metadata.
        Falls back to the card's top-level description when routing metadata is absent.
    """
    routing = card_definition.routing
    if not routing:
        return card_definition.description

    parts: list[str] = [routing.short_description]

    if routing.boundaries:
        parts.append("\nHandles:")
        parts.extend(f"- {item}" for item in routing.boundaries.handles)
        parts.append("\nDoes NOT handle:")
        parts.extend(f"- {item}" for item in routing.boundaries.does_not_handle)

    if routing.query_examples:
        parts.append("\nRoute here for queries like:")
        parts.extend(f"- {ex}" for ex in routing.query_examples.should_route)
        parts.append("\nDo NOT route here for:")
        parts.extend(f"- {ex}" for ex in routing.query_examples.should_not_route)

    if routing.handoff_notes:
        parts.append(f"\n{routing.handoff_notes}")

    if routing.trigger_keywords:
        parts.append(f"\nTrigger keywords: {', '.join(routing.trigger_keywords)}")

    return "\n".join(parts)


async def _handle_sub_agent_request_via_a2a(
    wrapper: RunContextWrapper[ToolContext],
    request: str,
    context: str,
    domain_name: str,
    card_name: str,
    tool_name: str,
    *,
    ui_component_queue: Any = None,
) -> str:
    """Handle a sub-agent request via A2A JSON-RPC protocol.

    Mirrors the in-process execution path: replaces the last conversation message
    with the specific sub-agent request, forwards account context via extensions,
    and reconstructs a SubAgentOutput from the response.

    On A2AClientError the exception propagates so the caller can fall back to
    the in-process path.

    Args:
        wrapper: The RunContextWrapper containing tool context.
        request: The domain-specific rewritten request for this sub-agent.
        context: Additional context string to append to the request.
        domain_name: Human-readable domain name for logging (e.g. "savings").
        card_name: Agent card registry key (e.g. "savings-agent").
        tool_name: Tool name used for Langfuse span lookup.
        ui_component_queue: Optional asyncio queue for UI component aggregation.

    Returns:
        Response text from the remote sub-agent, with any UI component markers appended.

    Raises:
        A2AClientError: If the remote A2A call fails (allows caller fallback).
        ValueError: If the registry is unavailable or the card is not found.
    """
    a2a_registry = wrapper.context.a2a_registry
    if not a2a_registry:
        raise ValueError(f"A2A registry not available for {domain_name}")

    card = a2a_registry.get_agent_card(card_name)
    if card is None:
        raise ValueError(f"Agent card '{card_name}' not found in A2A registry")

    client = A2AClient(agent_card=card, timeout_seconds=AgentConfig.A2A_CLIENT_TIMEOUT_SECONDS)
    try:
        # Get trace context for distributed tracing
        trace_id: str | None = None
        parent_span_id = _get_a2a_parent_span_id(wrapper, tool_name)
        if use_langfuse:
            trace_id = langfuse_context.get_current_trace_id()

        # Extract context from wrapper
        thread_id = wrapper.context.thread_id or "sub_session"
        cif_code = wrapper.context.cif_code or ""
        conversation_history = wrapper.context.conversation_history or []

        # Prepare conversation history for A2A request
        conversation_history_dicts, original_user_query = _prepare_a2a_conversation_history(
            conversation_history, request
        )

        # Build request context (extensions and metadata)
        extensions, metadata = _build_a2a_request_context(
            wrapper, conversation_history_dicts, original_user_query, thread_id, cif_code
        )

        # Build full request with context
        full_request = f"{request}\n\nContext: {context}" if context else request

        # Update tool observation for tracing
        update_tool_observation(wrapper, tool_name, {"Request": request, "Context": context})

        # Send A2A message and process response
        result = await _send_and_process_a2a_response(
            client, full_request, metadata, extensions, trace_id, parent_span_id, domain_name
        )

        # Collect UI components
        _collect_a2a_ui_components(result.ui_components, wrapper, ui_component_queue)

        # Build response text
        if not result.message or not result.message.strip():
            return f"{domain_name} service returned no response"

        response_text = result.message
        response_text = append_ui_components_to_response(response_text, result.ui_components or [], domain_name)

        return response_text

    finally:
        await client.close()


def _build_external_agent_tools(
    a2a_registry: LocalAgentRegistry | None,
) -> list[FunctionTool]:
    """Dynamically create LLM tools for all registered external A2A agents.

    Iterates over agent card definitions in the registry and generates a
    ``handle_{domain}_request`` :class:`FunctionTool` for every card whose
    ``deployment`` is ``"external"``.  The tool description is derived from
    the agent card's routing metadata so the LLM knows when to invoke it.

    External agents are A2A-only — if the remote call fails a graceful
    fallback message is returned (no in-process execution).

    Args:
        a2a_registry: The local agent registry containing discovered cards.
            Returns an empty list when ``None`` or when A2A is disabled.

    Returns:
        List of dynamically created :class:`FunctionTool` instances.
    """
    if not a2a_registry or not is_a2a_enabled():
        return []

    tools: list[FunctionTool] = []
    internal_domains = {"savings", "products", "homebuying"}

    for card_def in a2a_registry.list_all_agent_definitions():
        if card_def.deployment != "external":
            continue
        domain = card_def.inferred_agent_domain()
        if domain in internal_domains:
            continue
        card_name = card_def.name
        description = build_tool_description_from_card(card_def)
        tool_name = f"handle_{domain}_request"

        # Build the async handler closed over this card's domain/name
        async def _handler(
            wrapper: RunContextWrapper[ToolContext],
            request: str,
            context: str,
            *,
            _domain: str = domain,
            _card_name: str = card_name,
            _tool_name: str = tool_name,
        ) -> str:
            if not is_a2a_enabled() or not wrapper.context.a2a_registry:
                raise ValueError(f"{_domain} A2A service is not enabled or registry unavailable")
            return await _handle_sub_agent_request_via_a2a(
                wrapper,
                request,
                context,
                domain_name=_domain,
                card_name=_card_name,
                tool_name=_tool_name,
            )

        tool = function_tool(
            _handler,
            name_override=tool_name,
            description_override=description,
            failure_error_function=_sub_agent_tool_error_handler,
        )
        tools.append(tool)
        logger.info(
            f"Registered dynamic tool '{tool_name}' for external agent '{card_name}'",
            extra={"domain": domain, "card_name": card_name},
        )

    return tools


def _get_card_description(
    a2a_registry: LocalAgentRegistry | None,
    card_name: str,
    fallback: str,
) -> str:
    """Return a card-derived description or fall back to the supplied string.

    When A2A_ROUTING_ENABLED is True, uses agent card descriptions for LLM routing.
    When False, uses hardcoded domain descriptions regardless of card availability.

    Args:
        a2a_registry: Optional A2A registry containing agent cards
        card_name: Name of the agent card to look up
        fallback: Fallback description if card not found or routing disabled

    Returns:
        Agent description from card (if routing enabled) or fallback string
    """
    if is_a2a_routing_enabled() and a2a_registry:
        card_definition = a2a_registry.get_agent_card_definition(card_name)
        if card_definition:
            return build_tool_description_from_card(card_definition)
    return fallback


async def _route_to_agent_with_fallback(
    wrapper: RunContextWrapper[ToolContext],
    request: str,
    context: str,
    domain_name: str,
    card_name: str,
    tool_name: str,
    agent: HomebuyingAgent | ProductsAgent | SavingsAgent,
    agent_name: str,
) -> str:
    """Route request to agent via A2A with in-process fallback.

    Args:
        wrapper: The RunContextWrapper containing tool context
        request: The user request to route
        context: Additional context for processing
        domain_name: Domain name for logging (e.g., "savings")
        card_name: Agent card name (e.g., "savings-agent")
        tool_name: Tool name for tracing
        agent: Agent instance for in-process execution
        agent_name: Agent name for logging

    Returns:
        Response text from agent
    """
    ui_component_queue = getattr(wrapper.context, "ui_component_queue", None)

    if is_a2a_routing_enabled() and wrapper.context.a2a_registry:
        try:
            return await _handle_sub_agent_request_via_a2a(
                wrapper,
                request,
                context,
                domain_name=domain_name,
                card_name=card_name,
                tool_name=tool_name,
                ui_component_queue=ui_component_queue,
            )
        except (A2AClientError, ValueError) as e:
            logger.warning(
                f"A2A execution failed for {domain_name}, falling back to in-process: {e}",
                extra={"a2a_status": "fallback", "domain": domain_name},
            )

    return await _handle_sub_agent_request(
        wrapper,
        request,
        context,
        agent=agent,
        agent_name=agent_name,
        tool_name=tool_name,
        ui_component_queue=ui_component_queue,
    )


def get_sub_agent_tools(
    homebuying_agent: HomebuyingAgent,
    savings_agent: SavingsAgent,
    products_agent: ProductsAgent,
    payment_agent: PaymentAgent | None = None,
    a2a_registry: LocalAgentRegistry | None = None,
) -> tuple[FunctionTool, ...]:
    """Returns a list of sub-agent tool functions.

    Internal agents (savings, products, homebuying, payment) use hardcoded
    tools with optional A2A routing and in-process fallback.

    External agents are discovered dynamically from the A2A registry and
    get auto-generated tools — no code changes required to onboard them.
    """
    savings_description = _get_card_description(a2a_registry, "savings-agent", SAVINGS_ROLE_DESCRIPTION)
    products_description = _get_card_description(a2a_registry, "products-agent", PRODUCTS_ROLE_DESCRIPTION)
    homebuying_description = _get_card_description(a2a_registry, "homebuying-agent", HOMEBUYING_ROLE_DESCRIPTION)

    @function_tool(
        failure_error_function=_sub_agent_tool_error_handler,
        description_override=savings_description,
    )
    async def handle_savings_request(
        wrapper: RunContextWrapper[ToolContext],
        request: str,
        context: str,
    ) -> str:
        """Handle savings-related requests.

        Args:
            wrapper: The RunContextWrapper containing tool context
            request: The specific portion of the user's request that this sub-agent should handle. For multi-intent queries, this should contain only the relevant intent for this particular sub-agent, not the full original request.
            context: Additional context the sub-agent needs to know in order to process the request.
        """
        return await _route_to_agent_with_fallback(
            wrapper,
            request,
            context,
            domain_name="savings",
            card_name="savings-agent",
            tool_name="handle_savings_request",
            agent=savings_agent,
            agent_name="savings_agent",
        )

    @function_tool(
        failure_error_function=_sub_agent_tool_error_handler,
        description_override=products_description,
    )
    async def handle_products_request(
        wrapper: RunContextWrapper[ToolContext],
        request: str,
        context: str,
    ) -> str:
        """Handle products-related requests.

        Args:
            wrapper: RunContextWrapper containing the tool context.
            request: The specific product-related intent extracted from the user's query.
            context: Additional context required for processing.
        """
        return await _route_to_agent_with_fallback(
            wrapper,
            request,
            context,
            domain_name="products",
            card_name="products-agent",
            tool_name="handle_products_request",
            agent=products_agent,
            agent_name="products_agent",
        )

    @function_tool(
        failure_error_function=_sub_agent_tool_error_handler,
        description_override=homebuying_description,
    )
    async def handle_homebuying_request(
        wrapper: RunContextWrapper[ToolContext],
        request: str,
        context: str,
    ) -> str:
        """Handle homebuying-related requests.

        Args:
            wrapper: The RunContextWrapper containing tool context
            request: The specific portion of the user's request that relates to homebuying. Include all information provided by the customer without stripping any details, only making the request specific to the home-buying domain.
            context: Additional context the sub-agent needs to know in order to process the request. This must include all information provided by the customer without stripping any details.
        """
        return await _route_to_agent_with_fallback(
            wrapper,
            request,
            context,
            domain_name="homebuying",
            card_name="homebuying-agent",
            tool_name="handle_homebuying_request",
            agent=homebuying_agent,
            agent_name="homebuying_agent",
        )

    @function_tool(failure_error_function=_sub_agent_tool_error_handler)
    async def payment_process_assistant(
        wrapper: RunContextWrapper[ToolContext],
        request: str,
        context: str,
    ) -> str:
        """During the payments process, this agent will handle the generation of UI components and execute payment validation tasks to assist the customer in making payments.

        Core Functions:
        - **Generate UI List Payment Options**: Display available payment options for the customer to choose from.
        - **Generate UI List of Billers**: Display a list of saved billers from the customer's address book for selection.
        - **Validate BPay Biller Details**: Verify the validity of BPay biller code and CRN, and handle invalid details.
        - **Generate UI Select Account**: Display a list of available accounts for the customer to select from for payments.
        - **Generate UI Confirm Payment Summary**: Display payment summary for customer confirmation before execution.
        - **Execute Payment**: Process the payment and provide a receipt or handle errors.
        - **Generate UI Payment Receipt**: Generate and display a receipt for a successful payment.

        **IMPORTANT**
        - When the payment_process_assistant returns payment process UI components, you must ALWAYS place them at the END of your response, regardless of relevance to the text content.

        **Payments Process Overview**

        When a customer indicates they want to make a payment, use the following flow to guide them through the process. Only proceed to the next phase once the current phase is successfully completed.

        **Payment Process Flow**
        **CRITICAL INSTRUCTION: Whenever you see the <CALL_PAYMENT_PROCESS_ASSISTANT> tag in the process below, you MUST call the payment_process_assistant tool at that step. The tag indicates a mandatory tool call is required to proceed.**

        **Phase 1: Determine Customer Intent**

        1. <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to generate a UI element showing the list of available payment options</CALL_PAYMENT_PROCESS_ASSISTANT>

        2. Based on their response:
        - **BPay**: Proceed to Phase 2 for BPay validation
        - **Credit Card or other methods**: Inform the customer that only BPay is currently supported

        **Phase 2: Validate Payment Method (BPay)**

        1. Ask the customer how they want to add BPay details:
        - Add a new biller
        - Use an existing biller
        - Upload a file
        - Show previous bill payments

        2. Based on their response:

        **Add a new biller**:
        - Collect the following biller details one message at a time (skip any already provided in prior context):
            - Biller code
            - Customer Reference Number (CRN)

        **Use an existing biller**:
        <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to generate a UI element showing the list of saved billers</CALL_PAYMENT_PROCESS_ASSISTANT>

        **Upload a file**: Inform the customer this functionality is not yet implemented

        **Show previous bill payments**: Inform the customer this functionality is not yet implemented

        3. Once biller details are provided:
        - <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to validate the BPay biller details</CALL_PAYMENT_PROCESS_ASSISTANT>
        - If it is valid, the agent will generate a UI element to confirm the details with the customer
        - If invalid: Inform the customer which details need correction, then repeat this step once corrected details are provided

        4. Once BPay biller details are validated, proceed to Phase 3

        **Phase 3: Execute Payment**

        1. Collect payment details from the customer:
        - Inform the customer you will now collect payment details
        - <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to generate a UI element to select the account to pay from</CALL_PAYMENT_PROCESS_ASSISTANT>
        - Once account is selected, ask the customer for each of the following one at a time:
            - Amount to pay

        2. <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to generate a UI element for confirming the payment summary</CALL_PAYMENT_PROCESS_ASSISTANT>

        3. After confirmation, execute the payment:
        - <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to execute the payment</CALL_PAYMENT_PROCESS_ASSISTANT>
        - **If successful**: <CALL_PAYMENT_PROCESS_ASSISTANT>Task the payment process assistant to generate a UI element for the payment receipt</CALL_PAYMENT_PROCESS_ASSISTANT>
        - **If unsuccessful**: Inform the customer and allow them to retry the process

        </payments>

        Args:
            wrapper: The RunContextWrapper containing tool context.
            request: The specific portion of the user's request that this sub-agent should handle. For multi-intent queries, this should contain only the relevant intent for this particular sub-agent, not the full original request.
            context: Additional context the sub-agent needs to know in order to process the request.
        """
        if payment_agent is None:
            return "Payment agent is not available."

        # Get UI component queue from context if available
        ui_component_queue = getattr(wrapper.context, "ui_component_queue", None)

        return await _handle_sub_agent_request(
            wrapper,
            request,
            context,
            agent=payment_agent,
            agent_name="payment_agent",
            tool_name="payment_process_assistant",
            ui_component_queue=ui_component_queue,
        )

    # Collect hardcoded internal agent tools
    internal_tools: list[FunctionTool] = [
        handle_homebuying_request,
        handle_savings_request,
        handle_products_request,
    ]
    if payment_agent is not None:
        internal_tools.append(payment_process_assistant)

    # Dynamically generate tools for external A2A agents from the registry.
    # This means adding a new external agent only requires a YAML config
    # entry in a2a_agents.yaml — no code changes needed.
    external_tools = _build_external_agent_tools(a2a_registry)

    return tuple(internal_tools + external_tools)
