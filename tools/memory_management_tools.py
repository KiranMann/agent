"""Memory management utilities for the Financial Companion Agent.

This module provides conversation history truncation using configurable methods.
All truncation preserves database integrity by operating at the application layer.
"""

from typing import Any

from common.configs.agent_config_settings import AgentConfig
from common.logging.core import logger
from common.tools.conversation_messages import ConversationMessage


def _convert_to_conversation_messages(
    messages: list[dict[str, Any]],
) -> list[ConversationMessage]:
    """Convert dict messages to ConversationMessage objects.

    Filters out function call messages and keeps only user/assistant/system messages
    with role and content fields.

    Args:
        messages: List of message dictionaries (may include function calls)

    Returns:
        List of ConversationMessage objects with only role and content
    """
    result: list[ConversationMessage] = []
    for msg in messages:
        if "role" not in msg or "content" not in msg:
            continue
        conversation_message = ConversationMessage(role=msg["role"], content=msg["content"])
        if msg.get("metadata"):
            conversation_message["metadata"] = msg["metadata"]
        result.append(conversation_message)
    return result


async def apply_message_truncation(
    messages: list[dict[str, Any]],
) -> list[ConversationMessage]:
    """Apply message truncation using configured strategy.

    Reads MEMORY_TRUNCATION_STRATEGY from config and dispatches to
    the appropriate implementation function.

    Args:
        messages: Full conversation history

    Returns:
        Truncated message list based on config settings
    """
    method = AgentConfig.MEMORY_TRUNCATION_STRATEGY

    logger.info(f"Applying {method} truncation to {len(messages)} messages")

    if method == "sliding_window":
        truncated_messages = await sliding_window_truncate(messages)
        return _convert_to_conversation_messages(truncated_messages)
    elif method == "llm_summarisation":
        truncated_messages = await llm_summarisation_truncate(messages)
        return _convert_to_conversation_messages(truncated_messages)
    else:
        logger.error(
            f"Invalid MEMORY_TRUNCATION_STRATEGY: {method}. "
            f"Valid options: sliding_window, llm_summarisation. "
            f"Falling back to sliding_window."
        )
        truncated_messages = await sliding_window_truncate(messages)
        return _convert_to_conversation_messages(truncated_messages)


async def sliding_window_truncate(
    messages: list[dict[str, Any]],
    max_exchanges: int | None = None,
    should_preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """Apply sliding window truncation - keep last N exchanges plus system messages.

    Now handles tool calls and outputs as part of conversation exchanges,
    ensuring complete tool interaction sequences are preserved.

    Args:
        messages: Full conversation history
        max_exchanges: Number of recent exchanges to keep (uses config default if None)
        should_preserve_system: Whether to always include system messages

    Returns:
        Windowed message list with system messages + last N exchanges
    """
    if not messages:
        return messages

    # Use config default if not provided
    if max_exchanges is None:
        max_exchanges = AgentConfig.MAX_CONVERSATION_EXCHANGES

    # Separate system messages from conversation messages
    system_messages, conversation_messages = _separate_system_messages(messages, should_preserve_system)

    # Group messages into logical exchange sequences
    exchange_groups = _group_messages_into_exchanges(conversation_messages)

    # Keep the last N exchange groups
    recent_groups = exchange_groups[-max_exchanges:] if len(exchange_groups) > max_exchanges else exchange_groups

    # Flatten the selected groups back into a message list
    recent_conversation = _flatten_exchange_groups(recent_groups)

    logger.info(
        f"Sliding window applied: {len(system_messages)} system messages + "
        f"{len(recent_conversation)} recent messages from {len(exchange_groups)} exchange groups "
        f"(total {len(messages)} messages)"
    )

    # Return system messages first, then recent conversation
    return system_messages + recent_conversation


def _separate_system_messages(
    messages: list[dict[str, Any]], should_preserve_system: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate system messages from conversation messages.

    Args:
        messages: Full message list
        should_preserve_system: Whether to preserve system messages

    Returns:
        Tuple of (system_messages, conversation_messages)
    """
    system_messages = []
    conversation_messages = []

    for msg in messages:
        if should_preserve_system and msg.get("role") == "system":
            system_messages.append(msg)
        elif _is_conversation_message(msg):
            conversation_messages.append(msg)

    return system_messages, conversation_messages


def _is_conversation_message(msg: dict[str, Any]) -> bool:
    """Check if a message is part of the conversation (not system).

    Args:
        msg: Message to check

    Returns:
        True if message is part of conversation flow
    """
    # Regular user/assistant messages
    if msg.get("role") in ["user", "assistant"]:
        return True

    # Tool call messages
    return msg.get("item_type") in ["function_call", "function_call_output"]


def _group_messages_into_exchanges(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group conversation messages into logical exchange sequences.

    Each exchange typically consists of:
    1. User message
    2. Assistant message (possibly with tool calls)
    3. Zero or more function_call messages
    4. Zero or more function_call_output messages
    5. Final assistant response (if tools were used)

    Args:
        messages: Conversation messages (excluding system)

    Returns:
        List of exchange groups, each containing related messages
    """
    if not messages:
        return []

    exchanges = []
    current_exchange: list[dict[str, Any]] = []

    for msg in messages:
        msg_role = msg.get("role")
        msg_type = msg.get("item_type", "message")

        if msg_role == "user":
            # Start new exchange on user message
            if current_exchange:
                exchanges.append(current_exchange)
            current_exchange = [msg]

        elif msg_role == "assistant":
            # Assistant message belongs to current exchange
            current_exchange.append(msg)

        elif msg_type in ["function_call", "function_call_output"]:
            # Tool calls/outputs belong to current exchange
            current_exchange.append(msg)

        else:
            # Handle unexpected message types gracefully
            logger.warning(f"Unexpected message type in exchange grouping: role={msg_role}, type={msg_type}")
            current_exchange.append(msg)

    # Don't forget the last exchange
    if current_exchange:
        exchanges.append(current_exchange)

    return exchanges


def _flatten_exchange_groups(
    exchange_groups: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten exchange groups back into a single message list.

    Args:
        exchange_groups: List of exchange groups

    Returns:
        Flattened list of messages maintaining chronological order
    """
    flattened = []
    for group in exchange_groups:
        flattened.extend(group)
    return flattened


async def llm_summarisation_truncate(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply LLM summarisation truncation - summarise older messages, keep recent ones.

    This is a placeholder for future LLM-based summarisation implementation.
    Currently falls back to sliding window behaviour.

    Args:
        messages: Full conversation history

    Returns:
        Messages with older content summarised and recent messages preserved
    """
    logger.warning("LLM summarisation not yet implemented, falling back to sliding window")

    # Fallback to sliding window for now
    return await sliding_window_truncate(messages)
