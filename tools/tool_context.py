from typing import Any

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from apps.companion.all_agents.guardrails.utils.advice_types import AdviceType
from common.logging.core import logger
from common.tools.conversation_messages import ConversationMessage


def process_context_request(
    tool_context: "ToolContext",
    context_request: dict[str, Any],
    conversation_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Process context_request and add to conversation history.

    Args:
        tool_context: The tool context to store request/context in
        context_request: Dictionary containing Request and Context
        conversation_history: List of conversation messages to append to

    Returns:
        Updated conversation history with request/context appended as system messages
    """
    # Store request/context in tool context for tools to access
    if context_request and isinstance(context_request, dict):
        tool_context.current_request = context_request.get("Request", "")
        tool_context.request_context = context_request.get("Context", "")

        # Add request and context as new message types to conversation history
        if tool_context.current_request:
            conversation_history.append(
                {
                    "role": "system",
                    "content": f"CURRENT REQUEST: {tool_context.current_request}",
                }
            )

        if tool_context.request_context:
            conversation_history.append(
                {
                    "role": "system",
                    "content": f"ADDITIONAL CONTEXT: {tool_context.request_context}",
                }
            )

    return conversation_history


class ToolContext(BaseModel):
    """Context for financial tools with shared account access methods.

    This class provides the core context structure used across all agents
    and includes pre-loaded account context for optimal performance.
    """

    model_config = {"arbitrary_types_allowed": True}

    # Core context fields
    user_account: str | None = None
    ui_components: list[dict[str, Any]] = []
    langfuse_spans: dict[str, Any] = {}
    conversation_history: list[ConversationMessage] = []
    thread_id: str | None = None
    connection_pool: AsyncConnectionPool | None = None
    cif_code: str | None = None
    netbank_id: str | None = None
    dptoken: str | None = None  # DP token for AccountsEdge API authentication
    user_preferences: str | None = None
    last_action: str | None = None
    conversation_stage: str | None = None
    pending_confirmations: list[Any] | None = None
    ui_component_queue: Any | None = None
    correlation_id: str | None = None
    session_id: str | None = None
    referer: str | None = None
    advice_type: AdviceType = AdviceType.FACTUAL
    principal_agent: Any | None = None  # Reference to the FinancialCompanionAgent instance
    a2a_registry: Any | None = None  # LocalAgentRegistry instance when A2A is enabled

    # Request/Context fields for sub-agent communication
    current_request: str = ""
    request_context: str = ""

    # Pre-loaded account context fields
    customer_accounts: list[dict[str, Any]] | None = None
    account_context_loaded: bool = False
    account_service_used: str | None = None  # "account_services" or "client_services"

    # Tool execution data for guardrails
    tool_execution_data: list[dict[str, Any]] = []

    # Sources aggregation from RAG tools
    sources: list[dict[str, Any]] = []
    # Guardrail results for tool decorator
    guardrail_results: dict[str, dict[str, Any]] = {}

    def get_customer_accounts(self) -> list[dict[str, Any]]:
        """Get pre-loaded customer accounts (no API call required).

        Returns:
            list[dict[str, Any]]: List of customer account dictionaries, empty list if no accounts
        """
        if not self.customer_accounts:
            logger.debug("No customer accounts available in context")
        return self.customer_accounts or []

    def has_account_context(self) -> bool:
        """Check if account context is available and loaded.

        Returns:
            bool: True if account context is loaded and available
        """
        return self.account_context_loaded and bool(self.customer_accounts)

    def get_accounts_count(self) -> int:
        """Get the number of loaded customer accounts.

        Returns:
            int: Number of customer accounts
        """
        return len(self.customer_accounts) if self.customer_accounts else 0

    def resolve_customer_identifiers(self) -> tuple[str, str]:
        """Resolve customer identifiers from context.

        Returns:
            tuple: (cif_code, netbank_id)

        Raises:
            ValueError: If identifiers are not available
        """
        if not self.cif_code:
            raise ValueError("CIF code not available in context")
        if not self.netbank_id:
            raise ValueError("NBID not available in context")
        return self.cif_code, self.netbank_id

    def get_dptoken(self) -> str | None:
        """Get dptoken.

        Returns:
            str | None: The dptoken if available, None otherwise
        """
        if not self.dptoken:
            logger.debug("DP token not available in context")
        return getattr(self, "dptoken", None)

    def add_sources(self, new_sources: list[dict[str, Any]]) -> None:
        """Add sources to the context with deduplication based on URL.

        Args:
            new_sources: List of source dictionaries to add
        """
        if not new_sources:
            return

        # Create a set of existing URLs for fast lookup
        existing_urls = {source.get("url") for source in self.sources if source.get("url")}

        # Add only new sources that don't already exist
        for source in new_sources:
            url = source.get("url")
            if url and url not in existing_urls:
                self.sources.append(source)
                existing_urls.add(url)
