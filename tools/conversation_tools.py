"""Utilities for processing conversation items and extracting structured data.

This module provides tools for processing RunItem objects and extracting
tool usage information for conversation history persistence.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from common.configs.agent_config_settings import AgentConfig
from common.logging.core import logger

# Constants
ITEM_DETAILS_MAX_LENGTH = 200
DEFAULT_CONVERSATION_LIMIT = 100

ITEM_TYPE_FUNCTION_CALL = "function_call"
ITEM_TYPE_FUNCTION_OUTPUT = "function_call_output"

# Sub-agent tool names that should have their full outputs persisted in conversation history
# These tools represent calls to specialized sub-agents whose outputs are valuable for context
SUB_AGENT_TOOL_NAMES = {
    "handle_savings_request",
    "handle_products_request",
    "handle_homebuying_request",
    "classify_advice_type",
}


def apply_freshness_filter(
    conversation_history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    """Filter stale messages and build a freshness system message in a single pass.

    Iterates the conversation history once, simultaneously:
    - Partitioning messages into fresh (kept) and stale (removed) buckets based on
      the ``metadata.timestamp`` field (ISO 8601 string from DB ``created_at``).
    - Collecting descriptions of stale messages to populate a system message that
      instructs the sub-agent to re-confirm time-sensitive information.

    Messages without a parseable timestamp are always kept — they cannot be
    evaluated and are assumed to be recent (e.g. the current user turn or messages
    written before timestamp tracking was introduced).

    Args:
        conversation_history: Raw conversation messages, each optionally carrying
            ``metadata={"timestamp": "<ISO 8601>"}`` set by the DB retrieval layer.

    Returns:
        Tuple of:
        - ``filtered_history``: messages within the freshness threshold or without a timestamp.
        - ``freshness_message``: a ``{"role": "system", ...}`` dict if any stale messages
          were found, otherwise ``None``.
    """
    threshold_days = AgentConfig.MESSAGE_FRESHNESS_THRESHOLD_DAYS
    now = datetime.now(UTC)
    threshold = timedelta(days=threshold_days)

    filtered: list[dict[str, Any]] = []
    stale_descriptions: list[str] = []

    for turn_index, msg in enumerate(conversation_history, start=1):
        timestamp_str = (msg.get("metadata") or {}).get("timestamp")
        if not timestamp_str:
            filtered.append(msg)
            continue
        try:
            msg_time = datetime.fromisoformat(timestamp_str)
            age = now - msg_time
            if age > threshold:
                stale_descriptions.append(
                    f"- Turn {turn_index} ({msg.get('role', 'unknown')}, {age.days} days ago) - {msg.get('content', '')}"
                )
            else:
                filtered.append(msg)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse message timestamp for freshness check: {timestamp_str!r}")
            filtered.append(msg)

    if not stale_descriptions:
        return filtered, None

    stale_list = "\n".join(stale_descriptions)
    freshness_message: dict[str, str] = {
        "role": "system",
        "content": (
            f"INFORMATION FRESHNESS NOTICE\n"
            f"The following messages are more than {threshold_days} days old. "
            f"Any information stated in those messages — such as income figures, financial goals, "
            f"employment details, or account balances — may no longer be current. "
            f"It is up to you whether you use this information but if you do, it is critical that you re-confirm it with the customer. "
            f"Please ensure that you verify all details before taking any action. Failure to do so will result in a compliance breach.\n\n"
            f"Stale messages (older than {threshold_days} days):\n{stale_list}"
        ),
    }
    return filtered, freshness_message


def _validate_tool_call_item(item: Any, item_index: int) -> dict[str, Any] | None:
    """Validate a ToolCallItem and extract its raw_item as dict.

    Args:
        item: The item to validate
        item_index: Index of the item for logging

    Returns:
        Raw item dict if valid, None otherwise
    """
    if item.__class__.__name__ != "ToolCallItem":
        logger.warning(f"Item {item_index} is not a ToolCallItem: expected ToolCallItem, got {item.__class__.__name__}")
        return None

    raw_item = getattr(item, "raw_item", None)

    if isinstance(raw_item, dict):
        return raw_item

    logger.warning(
        f"ToolCallItem {item_index} has non-dict raw_item: expected dict, got {type(raw_item).__name__}, value: {str(raw_item)[:100]}"
    )
    return None


def _create_tool_call_data(raw_item: dict[str, Any], item_index: int) -> dict[str, Any] | None:
    """Create tool call data dict from raw_item dict.

    Args:
        raw_item: The raw_item dict from ToolCallItem
        item_index: Index of the item for logging

    Returns:
        Tool call data dict if valid, None otherwise
    """
    call_id = raw_item.get("call_id")
    name = raw_item.get("name")
    arguments = raw_item.get("arguments")

    if call_id and name and arguments:
        return {
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        }

    logger.warning(
        f"ToolCallItem {item_index} missing required fields",
        extra={
            "has_call_id": call_id is not None,
            "has_name": name is not None,
            "has_arguments": arguments is not None,
        },
    )
    return None


def _extract_tool_calls_from_items(
    new_items: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Extract tool call information from ToolCallItem objects.

    Args:
        new_items: List of RunItem objects from Runner.run() response

    Returns:
        Tuple of (tool_call_messages, tool_calls_dict)
        - tool_call_messages: List of formatted messages for conversation history persistence
        - tool_calls_dict: Dict mapping call_id to tool call data for output matching and
          selective persistence logic (needed to determine tool names for sub-agent filtering)
    """
    tool_call_messages = []
    tool_calls_dict = {}

    for i, item in enumerate(new_items):
        raw_item = _validate_tool_call_item(item, i)
        if raw_item is None:
            continue

        tool_call_data = _create_tool_call_data(raw_item, i)
        if tool_call_data is None:
            continue

        call_id = tool_call_data["call_id"]
        tool_calls_dict[call_id] = tool_call_data

        tool_call_message = {
            "type": ITEM_TYPE_FUNCTION_CALL,
            "call_id": tool_call_data["call_id"],
            "name": tool_call_data["name"],
            "arguments": tool_call_data["arguments"],
            "message_id": str(uuid.uuid4()),
        }
        tool_call_messages.append(tool_call_message)

    return tool_call_messages, tool_calls_dict


def _validate_tool_output_item(item: Any, item_index: int) -> dict[str, Any] | None:
    """Validate a ToolCallOutputItem and extract its raw_item as dict.

    Args:
        item: The item to validate
        item_index: Index of the item for logging

    Returns:
        Raw item dict if valid, None otherwise
    """
    if item.__class__.__name__ != "ToolCallOutputItem":
        logger.warning(
            f"Item {item_index} is not a ToolCallOutputItem: expected ToolCallOutputItem, got {item.__class__.__name__}"
        )
        return None

    raw_item = getattr(item, "raw_item", None)

    if isinstance(raw_item, dict):
        return raw_item

    logger.warning(
        f"ToolCallOutputItem {item_index} has non-dict raw_item: expected dict, got {type(raw_item).__name__}, value: {str(raw_item)[:100]}"
    )
    return None


def _create_tool_output_data(raw_item: dict[str, Any], item_index: int) -> dict[str, Any] | None:
    """Create tool output data dict from raw_item dict.

    Args:
        raw_item: The raw_item dict from ToolCallOutputItem
        item_index: Index of the item for logging

    Returns:
        Tool output data dict if valid, None otherwise
    """
    call_id = raw_item.get("call_id")
    output = raw_item.get("output")

    if call_id and output is not None:
        return {
            "call_id": call_id,
            "output": output,
        }

    logger.warning(
        f"ToolCallOutputItem {item_index} missing required fields",
        extra={
            "has_call_id": call_id is not None,
            "has_output": output is not None,
        },
    )
    return None


def _extract_tool_outputs_from_items(new_items: list[Any]) -> list[dict[str, Any]]:
    """Extract tool output information from ToolCallOutputItem objects.

    Args:
        new_items: List of RunItem objects from Runner.run() response

    Returns:
        List of output data dicts with call_id, output, and item_index
    """
    tool_outputs = []

    for i, item in enumerate(new_items):
        raw_item = _validate_tool_output_item(item, i)
        if raw_item is None:
            continue

        tool_output_data = _create_tool_output_data(raw_item, i)
        if tool_output_data is None:
            continue

        # Add item_index for compatibility with existing code
        tool_output_data["item_index"] = i
        tool_outputs.append(tool_output_data)

    return tool_outputs


def _create_tool_output_messages(
    tool_outputs: list[dict[str, Any]],
    tool_calls: dict[str, dict[str, Any]],
    sub_agent_tools: set[str],
) -> list[dict[str, Any]]:
    """Create tool output messages with selective persistence logic.

    Args:
        tool_outputs: List of output data dicts from _extract_tool_outputs_from_items
        tool_calls: Dict mapping call_id to tool call data from _extract_tool_calls_from_items
        sub_agent_tools: Set of tool names that should have full outputs persisted

    Returns:
        List of tool output messages
    """
    output_messages = []

    for output_data in tool_outputs:
        call_id = output_data["call_id"]
        output = output_data["output"]

        # Find matching tool call
        matching_tool_call: dict[str, Any] | None = tool_calls.get(call_id)

        if matching_tool_call:
            tool_name = matching_tool_call.get("name")
            output_message_id = str(uuid.uuid4())
            is_sub_agent_tool = tool_name in sub_agent_tools

            # Store actual output for sub-agent tools, placeholder for others
            if is_sub_agent_tool:
                # Store actual output for sub-agent tools
                tool_output_message = {
                    "type": ITEM_TYPE_FUNCTION_OUTPUT,
                    "call_id": call_id,
                    "output": output,
                    "message_id": output_message_id,
                }
            else:
                # Store placeholder message for non-sub-agent tools
                tool_output_message = {
                    "type": ITEM_TYPE_FUNCTION_OUTPUT,
                    "call_id": call_id,
                    "output": "Tool output too verbose to keep in conversation history",
                    "message_id": output_message_id,
                }

            output_messages.append(tool_output_message)
        else:
            logger.warning(f"No matching tool call found for output {call_id}")

    return output_messages


def extract_tool_usage_from_new_items(new_items: list[Any]) -> list[dict[str, Any]]:
    """Extract tool usage information from new_items for conversation history persistence.

    Implements selective persistence:
    - Sub-agent tools: Store both calls AND outputs
    - Other tools: Store calls only, NO outputs

    Args:
        new_items: List of RunItem objects from Runner.run() response

    Returns:
        List of tool usage messages with roles 'function_call' and 'function_call_output'
    """
    # Handle None or empty inputs
    if not new_items:
        return []

    # Use module-level constant for sub-agent tools that should have outputs persisted
    sub_agent_tools = SUB_AGENT_TOOL_NAMES

    # Extract tool calls and outputs using helper functions
    tool_call_messages, tool_calls = _extract_tool_calls_from_items(new_items)
    tool_outputs = _extract_tool_outputs_from_items(new_items)

    # Create tool output messages with selective persistence
    tool_output_messages = _create_tool_output_messages(tool_outputs, tool_calls, sub_agent_tools)

    # Combine all messages
    tool_messages = tool_call_messages + tool_output_messages

    logger.debug(
        "extract_tool_usage_from_new_items completed",
        extra={
            "total_new_items": len(new_items) if new_items else 0,
            "extracted_tool_messages": len(tool_messages),
            "tool_call_count": len(tool_calls),
            "message_types": [msg.get("type") for msg in tool_messages],
            "tool_names": [
                tool_calls.get(msg.get("call_id") or "", {}).get("name")
                for msg in tool_messages
                if msg.get("type") == "function_call"
            ],
        },
    )

    return tool_messages
