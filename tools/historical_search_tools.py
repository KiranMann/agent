# pylint: disable=inconsistent-quotes
"""Historical search tools for analyzing past customer conversations.

This module provides tools to search through conversation history stored in PostgreSQL
to help agents provide better context-aware service and learn from past interactions.

Uses SQLAlchemy ORM for type-safe database operations with full async support.
"""

from datetime import datetime, timedelta
from typing import Any

from agents import RunContextWrapper, function_tool
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from common.database import Conversation, ConversationMessage, get_db_session, is_database_configured
from common.logging.core import logger
from common.tools import ToolContext
from common.tools.util_langfuse import update_tool_observation


def _check_search_preconditions(
    wrapper: RunContextWrapper[ToolContext],
) -> str | None:
    """Check essential preconditions for the search_customer_history function.

    Args:
        wrapper: The run context containing customer information

    Returns:
        str: Error message if preconditions fail, None if all preconditions pass
    """
    # Extract customer context - required for security
    if not wrapper.context.cif_code:
        return "Unable to search conversation history: Customer identification required."

    if not is_database_configured():
        return "Unable to search conversation history: Database connection unavailable."

    return None


def _apply_content_filters(query: Select[Any], search_terms: list[str] | None) -> Select[Any]:
    """Apply content filtering to a SQLAlchemy query based on search terms.

    Args:
        query: SQLAlchemy query to apply filters to
        search_terms: Optional list of search terms to filter by

    Returns:
        Updated query with content filters applied
    """
    cleaned_terms = [term.strip().lower() for term in (search_terms or []) if term.strip()]
    if cleaned_terms:
        term_conditions = [ConversationMessage.content.ilike(f"%{term}%") for term in cleaned_terms[:5]]
        query = query.where(or_(*term_conditions))
    return query


async def _build_and_execute_search_query(
    session: AsyncSession,
    customer_id: str,
    position: int | None = None,
    days_back: int | None = None,
    search_terms: list[str] | None = None,
    limit: int = 10,
) -> list[ConversationMessage]:
    """Build and execute unified search query with filtering for closed conversations."""
    # Handle position queries with subquery approach for better type safety
    if position:
        # Create subquery to rank sessions by most recent message timestamp
        session_ranks_subquery = (
            select(
                ConversationMessage.session_id,
                func.dense_rank().over(order_by=desc(func.max(ConversationMessage.created_at))).label("session_rank"),
            )
            .join(Conversation, ConversationMessage.session_id == Conversation.session_id)
            .where(ConversationMessage.customer_id == customer_id)
            .where(Conversation.conversation_state != "closed")
            .group_by(ConversationMessage.session_id)
        ).subquery()

        # Main query joining with the ranked sessions
        query = (
            select(ConversationMessage)
            .join(Conversation, ConversationMessage.session_id == Conversation.session_id)
            .join(session_ranks_subquery, ConversationMessage.session_id == session_ranks_subquery.c.session_id)
            .where(ConversationMessage.customer_id == customer_id)
            .where(Conversation.conversation_state != "closed")
            .where(session_ranks_subquery.c.session_rank == position)
        )

        # Apply temporal filter if specified
        if days_back:
            start_date = datetime.now() - timedelta(days=days_back)
            query = query.where(ConversationMessage.created_at >= start_date)

        # Apply content filtering if search terms provided
        query = _apply_content_filters(query, search_terms)

        # Apply ordering and limit
        query = query.order_by(desc(ConversationMessage.created_at)).limit(limit)

        # Execute and return results with proper ORM mapping
        result = await session.execute(query)
        return list(result.scalars().all())

    # Handle non-position queries (existing logic, single JOIN)
    query = (
        select(ConversationMessage)
        .join(Conversation, ConversationMessage.session_id == Conversation.session_id)
        .where(ConversationMessage.customer_id == customer_id)
        .where(Conversation.conversation_state != "closed")
    )

    # Apply temporal filter if specified
    if days_back:
        start_date = datetime.now() - timedelta(days=days_back)
        query = query.where(ConversationMessage.created_at >= start_date)

    # Apply content filtering if search terms provided
    query = _apply_content_filters(query, search_terms)

    # Apply ordering and limit
    query = query.order_by(desc(ConversationMessage.created_at)).limit(limit)

    # Execute and return results
    result = await session.execute(query)
    return list(result.scalars().all())


def _generate_no_results_message(position: int | None, cleaned_terms: list[str]) -> str:
    """Generate appropriate message when no results are found."""
    if position:
        return f"No conversation found at position {position}. This may be beyond your conversation history."
    elif cleaned_terms:
        return f"No historical conversations found for terms: [{', '.join(cleaned_terms)}]. Try using different keywords or check if this is a new topic."
    else:
        return "No conversations found matching your criteria."


def _generate_results_header(position: int | None, cleaned_terms: list[str], result_count: int) -> str:
    """Generate header for search results."""
    if position:
        return f"Found conversation at position {position} (conversation #{position} from most recent)"
    elif cleaned_terms:
        return f"Found {result_count} relevant conversation(s) for terms: [{', '.join(cleaned_terms)}]"
    else:
        return f"Found {result_count} recent conversation(s)"


def _format_search_results(messages: list[ConversationMessage], header: str) -> list[str]:
    """Format SQLAlchemy model instances into readable search results."""
    results = [f"{header}\n"]
    for i, message in enumerate(messages, 1):
        content = message.content_preview
        results.extend(
            [
                f"{i}. **Session {message.session_id}** ({message.created_at.isoformat() if message.created_at else 'Unknown'})",
                f"   Role: {message.role}",
                f"   Content: {content}",
                "",
            ]
        )
    return results


async def _execute_history_search(
    customer_id: str,
    search_terms: list[str] | None = None,
    days_back: int | None = None,
    position: int | None = None,
    limit: int | None = 10,
) -> str:
    """Execute database search using SQLAlchemy ORM with full async support.

    Args:
        customer_id: Customer ID for scoped search
        search_terms: Optional list of search terms
        days_back: Number of days to search back
        position: Conversation position (1=most recent, 2=second most recent, etc.)
        limit: Maximum number of results to return

    Returns:
        str: Formatted search results
    """
    # Apply default fallback when no criteria provided
    if not any([search_terms, position, days_back]):
        days_back = 7
        logger.info("Using fallback search for recent conversations (7 days)")

    # Prepare search terms
    cleaned_terms = [term.strip().lower() for term in (search_terms or []) if term.strip()]

    try:
        async with get_db_session() as session:
            # Execute unified search query
            messages = await _build_and_execute_search_query(
                session, customer_id, position, days_back, search_terms, limit or 10
            )

            # Handle empty results
            if not messages:
                return _generate_no_results_message(position, cleaned_terms)

            # Format and return results
            header = _generate_results_header(position, cleaned_terms, len(messages))
            results = _format_search_results(messages, header)

            # Log completion with safe criteria indicators (no PII)
            criteria = []
            if cleaned_terms:
                criteria.append("term_search")
            if days_back:
                criteria.append("temporal_search")
            if position:
                criteria.append("positional_search")

            # Add fallback indicator if no original criteria were provided
            if not any([search_terms, position, days_back]):
                criteria.append("fallback_search")

            logger.info(
                f"Historical search completed for customer using {', '.join(criteria)}, results={len(messages)}"
            )
            return "\n".join(results)

    except Exception as e:
        logger.error(f"Error during historical search: {e}")
        raise


@function_tool()
async def search_customer_history(
    wrapper: RunContextWrapper[ToolContext],
    search_terms: list[str] | None = None,
    days_back: int | None = 30,
    position: int | None = None,
    limit: int | None = 10,
) -> str:
    """Search through the current customer's conversation history with flexible criteria.

    **ALWAYS VERIFY CONVERSATION HISTORY FIRST:**
    - NEVER assume this is a "first message" or "new conversation"
    - ALWAYS call this tool when users ask about past conversations
    - Let the tool determine if history exists - don't make assumptions

    **WHEN TO USE THIS TOOL:**
    Use this tool for ANY query about past conversations, previous discussions, or historical context.

    **Example Queries Include:**
    - "what did we discuss/talk about/speak about today"
    - "tell me about what we have spoken about"
    - "what happened in our conversation"
    - "remind me what we discussed"
    - "our previous conversation"
    - "what did we cover earlier"
    - "last time we talked"
    - "yesterday we discussed"
    - "earlier today"

    **IMPORTANT: Call this tool BEFORE making assumptions about conversation status!**

    **PARAMETER MAPPING GUIDE:**

    **TIME-BASED QUERIES - Map to `days_back` parameter:**
    - "yesterday" → days_back=1
    - "last week" / "past week" → days_back=7
    - "last month" / "past month" → days_back=30
    - "few days ago" / "couple days ago" → days_back=3
    - "last 2 weeks" / "past 2 weeks" → days_back=14
    - "recently" / "lately" → days_back=7
    - "last 5 days" → days_back=5
    - "today" → days_back=1
    - Specific dates (e.g., "October 1st", "first of October") → days_back=30-60 (use judgment)

    **POSITION-BASED QUERIES - Map to `position` parameter:**
    - "last conversation" / "previous conversation" / "most recent chat" → position=1
    - "conversation before last" / "second to last conversation" → position=2
    - "two conversations ago" / "third most recent" → position=3
    - "few conversations ago" → position=2 or 3 (use judgment)

    **CONTENT QUERIES - Map to `search_terms` parameter:**
    - Extract key topics, issues, or subjects mentioned
    - Examples: "credit card error" → search_terms=["credit card", "error"]
    - Examples: "savings goal" → search_terms=["savings", "goal"]
    - Examples: "loan application" → search_terms=["loan", "application"]

    **COMBINATION QUERIES:**
    - "credit card error from last week" → search_terms=["credit card", "error"], days_back=7
    - "savings discussion from our last conversation" → search_terms=["savings"], position=1
    - "loan problem from yesterday" → search_terms=["loan", "problem"], days_back=1

    **TRIGGER PHRASES TO WATCH FOR:**
    - "What did we discuss/talk about/speak about..."
    - "Tell me about our conversation..."
    - "Remind me what we..."
    - "What happened in our chat..."
    - "The issue/problem/topic we discussed..."
    - "Our previous conversation about..."

    **IMPORTANT NOTES:**
    - Closed conversations are automatically excluded from all search results
    - Always prioritize position over days_back when both could apply
    - If unsure about timeframe, default to days_back=7 for recent searches
    - Extract 2-4 key terms for search_terms, avoid overly generic words
    - The search is automatically scoped to the current customer for privacy

    Args:
        wrapper: The run context containing customer information
        search_terms: List of keywords to search for in conversations
        days_back: Number of days to search back from today
        position: Conversation position (1=most recent, 2=second most recent, etc.)
        limit: Maximum number of search results to return (default: 10)

    Returns:
        str: Formatted search results with conversation excerpts and metadata,
             or empty results message if no matches found
    """
    # Capture inputs for Langfuse tracing
    update_tool_observation(
        wrapper,
        "search_customer_history",
        {
            "search_terms": search_terms,
            "days_back": days_back,
            "position": position,
            "limit": limit,
        },
    )

    # Step 1: Check all preconditions
    validation_error = _check_search_preconditions(wrapper)
    if validation_error:
        return validation_error

    # Step 2: Execute search and return formatted results
    try:
        # After validation passes, we know cif_code is not None
        assert wrapper.context.cif_code is not None
        return await _execute_history_search(
            wrapper.context.cif_code,
            search_terms,
            days_back,
            position,
            limit,
        )
    except Exception as e:
        logger.error(f"Error during historical search: {e}")
        if "database" in str(e).lower() or "connection" in str(e).lower():
            return "Unable to search conversation history due to database error."
        elif "validation" in str(e).lower() or "invalid" in str(e).lower():
            return "Invalid search parameters: Please check your search criteria."
        else:
            return "Unable to search conversation history due to technical error."
