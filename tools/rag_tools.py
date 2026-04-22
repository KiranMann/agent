"""Financial companion agent tools for Knowledge Base retrieval and generation."""

from typing import Any

from agents import RunContextWrapper, function_tool
from agents.exceptions import AgentsException
from pydantic import BaseModel

from common.configs.agent_config_settings import get_agent_config
from common.logging.core import logger
from common.metrics import record_rag_retrieval
from common.rag_knowledgebase_client import MetaDataResult, RagKnowledgeBaseClient
from common.tools import ToolContext
from common.tools.util_langfuse import update_tool_observation


class RAGError(AgentsException):
    """Exception raised when a RAG tool encounters an error.

    Raised when Knowledge Base retrieval fails or returns no relevant documents.
    """

    def __init__(self, message: str) -> None:
        """Initialize the RAGError with a human-readable message.

        Args:
            message: Error description from the underlying failure.
        """
        super().__init__(f"RAG tool encountered an error: {message}")


class KBToolContext(BaseModel):
    """Context for RAG/Knowledge Base tools."""

    langfuse_spans: dict[str, Any] = {}
    ui_components: list[Any] = []


# Get agent configuration
config = get_agent_config()

rag_kb: RagKnowledgeBaseClient = RagKnowledgeBaseClient(
    max_results=10,
    search_type="SEMANTIC",
    similarity_threshold=0.3,
    enable_reranking=config.ENABLE_RAG_RERANKING,
)


def _process_sources_from_metadata(
    retrieved_data: list[MetaDataResult],
) -> list[dict[str, Any]]:
    """Process sources from RAG metadata results.

    Args:
        retrieved_data: List of MetaDataResult objects from RAG retrieval

    Returns:
        List of source dictionaries with title, description, url, and channel
        Note: S3 URIs are filtered out as they are not accessible to users
    """
    sources = []
    seen_urls = set()

    # Process all URLs (handling both complete URLs and relative paths, filtering S3)
    for item in retrieved_data:
        if isinstance(item, MetaDataResult):
            url = item.metadata.get("url")

            if url and url not in seen_urls:
                source = {
                    "title": url,
                    "description": "",
                    "url": url,
                    "channel": "",
                }
                sources.append(source)
                seen_urls.add(url)

    return sources


def _extract_conversation_history(context: Any) -> list[str]:
    """Extract and process conversation history from context.

    Args:
        context: The context object containing conversation history

    Returns:
        List of conversation content strings, limited to last 5 interactions
    """
    history = getattr(context, "conversation_history", []) or []
    filtered_history = [convo for convo in history if isinstance(convo, dict)]

    if not filtered_history:
        return []

    return [
        item.get("content", str(item)) if isinstance(item, dict) else str(item)
        for item in filtered_history[-5:]  # Last 5 interactions, truncated
    ]


def _get_allowed_persona_keys() -> list[str]:
    """Get list of allowed persona preference keys.

    Returns:
        List of allowed persona keys
    """
    return [
        "financial_goals",
        "investment_experience",
        "risk_tolerance",
        "life_stage",
    ]


def _process_persona_dict(persona_data: dict[str, Any]) -> dict[str, bool]:
    """Process persona data dictionary into safe preferences.

    Args:
        persona_data: Raw persona data dictionary

    Returns:
        Dictionary of safe persona preferences
    """
    safe_persona: dict[str, bool] = {}
    allowed_keys = _get_allowed_persona_keys()

    for key, value in persona_data.items():
        if key in allowed_keys:
            safe_persona[key] = bool(value) if value else False

    return safe_persona


def _extract_customer_persona_data(context: Any) -> dict[str, Any]:
    """Extract customer persona data from context.

    Args:
        context: The context object containing persona data

    Returns:
        Dict containing persona preferences or has_persona flag
    """
    persona_data = getattr(context, "customer_persona", None)
    if not persona_data:
        return {}

    if isinstance(persona_data, dict):
        safe_persona = _process_persona_dict(persona_data)
        return {"preferences": safe_persona} if safe_persona else {}

    return {"has_persona": True}


def _extract_session_persona_data(context: Any, existing_result: dict[str, Any]) -> dict[str, Any]:
    """Extract persona data from session metadata.

    Args:
        context: The context object containing session metadata
        existing_result: Existing persona result to check for preferences

    Returns:
        Updated persona result dict
    """
    session_metadata = getattr(context, "session_metadata", {})
    if not isinstance(session_metadata, dict):
        return existing_result

    persona = session_metadata.get("customer_persona", "")
    if persona and not existing_result.get("preferences"):
        return {**existing_result, "has_persona": True}

    return existing_result


def _extract_persona_preferences(context: Any) -> dict[str, Any]:
    """Extract customer persona preferences from context.

    Args:
        context: The context object containing persona data

    Returns:
        Dict containing persona preferences or has_persona flag
    """
    # Extract customer persona data
    persona_result = _extract_customer_persona_data(context)

    # Check for persona in session metadata
    persona_result = _extract_session_persona_data(context, persona_result)

    return persona_result


def _extract_agent_information(context: Any) -> dict[str, str]:
    """Extract agent type information from context.

    Args:
        context: The context object containing agent information

    Returns:
        Dict containing agent_type if found
    """
    # Extract agent type from context
    agent_type = getattr(context, "agent_type", None)
    if agent_type:
        return {"agent_type": str(agent_type)}

    # Extract current agent if agent_type not found
    current_agent = getattr(context, "current_agent", None)
    if current_agent:
        return {"agent_type": str(current_agent)}

    return {}


def _extract_session_information(context: Any) -> dict[str, str]:
    """Extract session and conversation ID information from context.

    Args:
        context: The context object containing session information

    Returns:
        Dict containing session_id if found
    """
    # Extract session ID
    session_id = getattr(context, "session_id", None)
    if session_id:
        return {"session_id": str(session_id)}

    # Extract conversation ID as fallback for session
    conversation_id = getattr(context, "conversation_id", None)
    if conversation_id:
        return {"session_id": str(conversation_id)}

    return {}


def _extract_topic_information(context: Any) -> dict[str, str]:
    """Extract current topic information from context.

    Args:
        context: The context object containing topic information

    Returns:
        Dict containing current_topic if found
    """
    current_topic = getattr(context, "current_topic", None)
    if current_topic:
        return {"current_topic": str(current_topic)}
    return {}


def _extract_user_context_from_wrapper(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any]:
    """Extract user context from RunContextWrapper for reranking personalization.

    Args:
        wrapper: The context wrapper containing user and agent information

    Returns:
        Dict containing extracted user context for reranking
    """
    try:
        # Check if wrapper has context attribute
        if not hasattr(wrapper, "context"):
            logger.debug("No context attribute found in wrapper")
            return {}

        context = wrapper.context
        user_context: dict[str, Any] = {}

        # Extract conversation history
        history = _extract_conversation_history(context)
        if history:
            user_context["interaction_history"] = history

        # Extract persona preferences
        persona_info = _extract_persona_preferences(context)
        user_context.update(persona_info)

        # Extract agent information
        agent_info = _extract_agent_information(context)
        user_context.update(agent_info)

        # Extract session information
        session_info = _extract_session_information(context)
        user_context.update(session_info)

        # Extract topic information
        topic_info = _extract_topic_information(context)
        user_context.update(topic_info)

        logger.debug(
            f"Extracted user context for reranking: agent_type={user_context.get('agent_type')}, "
            f"has_persona={user_context.get('has_persona', False)}, "
            f"history_items={len(user_context.get('interaction_history', []))}"
        )

        return user_context

    except Exception as e:
        logger.warning(f"Failed to extract user context from wrapper: {e}")
        return {}


@function_tool(failure_error_function=None)
async def get_relevant_knowledge(
    wrapper: RunContextWrapper[ToolContext],
    question: str,
    get_metadata: bool = True,
) -> dict[str, Any]:
    """Retrieve data from knowledge base using semantic search.

    This tool uses semantic search and works best with specific keywords, entities, and concepts
    rather than full questions. Extract key terms from user queries to optimize retrieval.

    **Semantic Search Optimization Guidelines:**

    Extract key entities and concepts from user queries to build targeted search terms:
    - **Entity Extraction**: Identify specific products, account types, financial concepts, processes
    - **Progressive Refinement**: Start broad, then narrow to specific features or requirements
    - **Multi-Concept Combinations**: Combine related financial terms for comprehensive coverage
    - **Account-Specific Patterns**: Include account names, product categories, and feature keywords

    **Effective Search Term Construction:**
    - Extract specific entities (product names, account types, financial terms, processes)
    - Include synonyms (e.g., "home loan mortgage", "credit card charge card")
    - Add context keywords (fees, rates, eligibility, features, benefits)
    - Combine related concepts for comprehensive results
    - Use progressive refinement: start broader, then search more specifically if needed

    **Examples of Effective vs Ineffective Search Terms:**

    *Effective - Entity + Feature Combination:*
    - Customer: "What are the fees on my Complete Access account?"
    - Search: "Complete Access account fees monthly charges transaction costs"

    *Effective - Multi-Concept Search:*
    - Customer: "How do I apply for a home loan and what documents do I need?"
    - Search: "home loan application process documents requirements eligibility"

    *Effective - Progressive Refinement:*
    - Customer: "Which Yello benefits should I activate based on my spending?"
    - First: "Yello benefits activation spending categories cashback rewards"
    - Follow-up: "Yello benefit types grocery fuel dining entertainment"

    *Ineffective - Full Questions:*
    - "What are the fees on my Complete Access account?" (too conversational)
    - "How much can I borrow for a home loan?" (lacks specific keywords)

    *Ineffective - Vague Terms:*
    - "account information" (too broad)
    - "loan details" (lacks specificity)

    **Best Practices:**
    - Focus on nouns and specific financial terminology
    - Include product names and feature descriptors
    - Combine 3-6 relevant keywords per search
    - Use financial domain vocabulary over conversational language
    - Consider synonyms and related terms for comprehensive coverage

    Args:
        wrapper: The context wrapper for maintaining state
        question: Optimized search terms extracted from customer query (not the full question)
        get_metadata: If True, return full metadata for each chunk. If False, return only text
    Returns:
        JSON dictionary containing:
            - chunks_retrieved: List of text chunks or MetaDataResult objects
            - question: The original search terms used
            - filters_applied: Information about any metadata filters used
            - sources: List of source dictionaries with title, description, url, and channel
            - reranking_applied: Boolean indicating if reranking was used (when reranking is enabled)
    """
    # Determine if reranking should be enabled
    should_enable_reranking = config.ENABLE_RAG_RERANKING

    # Extract user context for reranking if enabled
    user_context = None
    if should_enable_reranking:
        user_context = _extract_user_context_from_wrapper(wrapper)
        logger.info(f"RAG reranking enabled for query: {question[:50]}...")
    else:
        logger.debug("RAG reranking disabled by configuration")

    # Update tool observation with reranking info
    update_tool_observation(
        wrapper,
        "get_relevant_knowledge",
        {
            "question": question,
            "get_metadata": get_metadata,
            "enable_reranking": should_enable_reranking,
        },
    )

    try:
        # Retrieve data with optional user context for reranking
        retrieved_data = await rag_kb.retrieve(
            question,
            get_metadata=get_metadata,
            user_context=user_context,
            enable_reranking=should_enable_reranking,
        )

        # Process sources from metadata if get_metadata is True and we have MetaDataResult objects
        sources = []
        if (
            get_metadata
            and retrieved_data
            and len(retrieved_data) > 0
            and isinstance(retrieved_data[0], MetaDataResult)
        ):
            # Type check: ensure all items are MetaDataResult objects
            metadata_results = [item for item in retrieved_data if isinstance(item, MetaDataResult)]

            sources = _process_sources_from_metadata(metadata_results)

        # Add sources to the shared context for aggregation across tool calls
        if sources and wrapper.context is not None:
            wrapper.context.add_sources(sources)

        # Check if reranking was actually applied by examining metadata
        reranking_applied = False
        if should_enable_reranking and retrieved_data and isinstance(retrieved_data[0], MetaDataResult):
            # Check if any result has reranking metadata
            reranking_applied = any(
                result.metadata.get("reranked", False)
                for result in retrieved_data
                if isinstance(result, MetaDataResult)
            )

        # Log retrieval results with reranking information
        logger.info(
            f"RAG retrieval completed: {len(retrieved_data)} chunks retrieved, "
            f"reranking_enabled={should_enable_reranking}, "
            f"reranking_applied={reranking_applied}, "
            f"sources_found={len(sources)}"
        )

        # Record RAG retrieval metric
        record_rag_retrieval(
            success=True,
            chunks_retrieved=len(retrieved_data),
            reranking_applied=reranking_applied,
        )

        # Structure the response with all relevant metadata
        result = {
            "chunks_retrieved": retrieved_data,
            "question": question,
            "filters_applied": None,
            "sources": sources,
            "reranking_applied": reranking_applied,
        }

        return result
    except Exception as e:
        logger.error(
            f"RAG retrieval failed for query: - Error: {e}",
            extra={
                "question": question,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "get_metadata": get_metadata,
                "enable_reranking": should_enable_reranking,
            },
        )
        record_rag_retrieval(success=False)
        # Return an error dict instead of raising RAGError so that parallel tool calls
        # (e.g. get_commbank_products) are not cancelled by asyncio.gather, allowing the
        # agent to still answer using other available data sources when RAG is unavailable.
        return {
            "chunks_retrieved": [],
            "question": question,
            "filters_applied": None,
            "sources": [],
            "reranking_applied": False,
            "error": f"Knowledge base unavailable: {e}",
        }
