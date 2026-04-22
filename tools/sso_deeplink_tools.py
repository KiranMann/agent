"""SSO Deeplinks tool for in-app navigation and actions."""

from typing import Any

from agents import RunContextWrapper, function_tool
from agents.exceptions import AgentsException

from apps.companion.agent_services.financial_companion_agent_utils import (
    get_app_details,
)
from common.logging.core import logger
from common.services.elastic_search_service import (
    ElasticSearchRequest,
    ElasticSearchResponse,
    elastic_search_service,
)
from common.tools.tool_context import ToolContext
from common.tools.util_langfuse import update_tool_observation


class SSODeeplinksError(AgentsException):
    """Exception raised when SSO deeplinks tool encounters an error.

    Raised when deeplinks knowledge base retrieval fails or returns no relevant navigation links.
    """

    def __init__(self, message: str) -> None:
        """Initialize the SSODeeplinksError with a human-readable message.

        Args:
            message: Error description from the underlying failure.
        """
        super().__init__(f"SSO deeplinks tool encountered an error: {message}")


# Helper function to get the appropriate URL field based on device type
def _get_url_field(device_type: str) -> str | None:
    """Get the appropriate URL field name based on device type."""
    device_mapping = {"IOS": "iosUrl", "ANDROID": "androidUrl"}
    return device_mapping.get(device_type)


@function_tool(failure_error_function=None)
async def get_sso_deeplinks(
    wrapper: RunContextWrapper[ToolContext],
    query: str,
) -> list[dict[str, Any]]:
    """Retrieve SSO deeplinks for in-app navigation and self-service actions.

    This tool provides deeplinks for direct navigation to specific self-service features within
    the banking app. It searches over action-oriented descriptions to help users complete tasks
    independently. Returns label, URL, and description from the deeplinks knowledge base.

    **WHEN TO USE THIS TOOL:**

    **Action-Oriented Queries (PRIMARY USE CASES):**
    - "I want to..." statements: "I want to set up PayID", "I want to change my card limits"
    - "How do I..." questions: "How do I download statements?", "How do I pay a bill?"
    - Self-service tasks: Account management, bill payments, transfers, card settings
    - Navigation requests: "Take me to...", "Show me where to...", "Navigate to..."

    **Specific Self-Service Actions:**
    - Account customization (nicknames, reordering, hiding/unhiding accounts)
    - Bill management (add, modify, delete bills via Bill Sense, BPAY setup)
    - Card management (locks, limits, contactless settings, report stolen cards)
    - Payment setup (BPAY, PayID, transfers, direct debits, scheduled payments)
    - Account opening (Term Deposits, SMSF accounts)
    - Home loan actions (refinancing, payout figures, discharge, switching repayment types)
    - PayTo agreements (setup, manage, pause, cancel)
    - Transfer limits management
    - Tap & Pay setup and management
    - Branch/ATM location finding
    - Balance confirmations and certificates
    - Overdraw feature activation

    **USAGE GUIDELINES:**

    **Use this tool frequently for:**
    - Any mention of wanting to "do", "set up", "change", "manage", "access" something
    - Questions about "how to" perform specific tasks
    - Requests for help with account management, payments, or self-service tasks
    - When users seem to need guidance on available actions
    - Follow-up questions where offering actionable options would be helpful

    **Examples of Good Usage:**
    - "I need help with my account" → Search: "account management"
    - "What can I do in the app?" → Search: "self service"
    - "How do I manage my bills?" → Search: "bill management"
    - "I want to transfer money" → Search: "transfer"
    - "Help me with payments" → Search: "payments"
    - "I need to update my details" → Search: "account details"

    **Avoid for pure informational requests that don't lead to actions:**
    - "What is a term deposit?"
    - "Explain how interest rates work"
    - "What's the difference between accounts?"

    Args:
        wrapper: RunContextWrapper containing the tool context for Langfuse tracing
        query: Search terms targeting self-service banking actions and navigation

    Returns:
        List of deeplink objects, each containing:
            - label: Display text for the deeplink
            - url: Navigation URL for the action
            - description: Detailed explanation of what the deeplink does

        Maximum of 5 deeplinks returned per query.
    """
    try:
        # Get app details from thread-local context
        app_details = get_app_details()
        # Log app_details before fast fail check
        logger.info(f"App details retrieved: {app_details}")

        # Fail fast: Return empty list if device_type or app_version is None/null
        if not app_details["device_type"] or not app_details["app_version"] or app_details["app_version"] == "unknown":
            logger.warning("Missing or invalid app details.")
            return []

        # Create Elasticsearch request with dynamic app details
        request = ElasticSearchRequest(
            index_name="appsearch",
            template_id="appsearch-semantic",
            query=query,
            page_size=5,  # Match current 5-result limit
            from_index=0,
            app_version=app_details["app_version"],
            device=app_details["device_type"],
            domain_names=["Actions", "Features", "Products & services", "Help"],
        )

        # Update tool observation with the complete request dump for Langfuse tracing
        update_tool_observation(
            wrapper,
            "get_sso_deeplinks",
            {
                "index_name": request.index_name,
                "template_id": request.template_id,
                "query": request.query,
                "page_size": request.page_size,
                "from_index": request.from_index,
                "app_version": request.app_version,
                "device": request.device,
                "domain_names": request.domain_names,
            },
        )

        # Execute search
        response = await elastic_search_service.search(request)

        # Get the appropriate URL field for the current device
        url_field = _get_url_field(app_details["device_type"])

        # Process successful results - map Elasticsearch document fields to expected format
        deeplinks = []
        if isinstance(response, ElasticSearchResponse):
            for document in response.results:
                # Map fields: title -> label, device-specific URL -> url, shortDescription -> description
                deeplink = {
                    "label": getattr(document, "title", ""),
                    "url": getattr(document, url_field, "") if url_field else "",
                    "description": getattr(document, "shortDescription", ""),
                }
                deeplinks.append(deeplink)
        logger.info(f"SSO deeplinks retrieval completed: {len(deeplinks)} deeplinks found.")
        return deeplinks

    except Exception as e:
        logger.error(f"SSO deeplinks retrieval failed - Error: {e}")
        raise SSODeeplinksError(str(e)) from e
