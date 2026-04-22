"""Base A2A executor for all sub-agents."""

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from a2a.types import (
    DataPart,
    Message,
    MessageSendParams,
    Role,
    SendMessageSuccessResponse,
    TextPart,
)
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from common.a2a.registry.card_definition import AgentCardDefinition
    from common.models.sub_agent_output import SubAgentOutput

logger = logging.getLogger(__name__)


class BaseA2AExecutor:
    """Generic A2A executor that wraps any sub-agent for JSON-RPC protocol communication."""

    def __init__(
        self,
        agent: Any,
        connection_pool: AsyncConnectionPool[Any],
        agent_name: str | None = None,
        resume_point: str | None = None,
        card: "AgentCardDefinition | None" = None,
    ) -> None:
        """Initialize the executor with an agent instance and pool.

        Args:
            agent: The agent instance to wrap (ProductsAgent, SavingsAgent, HomebuyingAgent, etc.)
            connection_pool: PostgreSQL connection pool for database operations
            agent_name: Name for the agent in task dict (e.g., "products_agent", "savings_agent").
                Optional if card is provided.
            resume_point: Resume point string (e.g., "Start of products_agent session").
                Optional if card is provided.
            card: Agent card definition from which agent_name and resume_point can be derived.
                Takes precedence over explicit agent_name/resume_point parameters.
        """
        self.agent = agent
        self.connection_pool = connection_pool

        # Derive agent_name and resume_point from card if provided
        if card:
            # Convert card name to agent attribute name
            # Strip "-agent" suffix if present, replace hyphens with underscores, ensure "_agent" suffix
            # Examples: "products-agent" -> "products_agent", "credit-card-agent" -> "credit_card_agent"
            base_name = card.name.removesuffix("-agent").replace("-", "_")
            self.agent_name = f"{base_name}_agent"
            self.resume_point = f"Start of {self.agent_name} session"
        else:
            # Use explicit parameters or fallback to defaults
            if agent_name is None:
                logger.warning(
                    "BaseA2AExecutor initialized without card or agent_name, falling back to 'unknown_agent'"
                )
            self.agent_name = agent_name or "unknown_agent"
            self.resume_point = resume_point or f"Start of {self.agent_name} session"

    async def execute_message(
        self,
        params: MessageSendParams,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> SendMessageSuccessResponse:
        """Execute a message/send request by delegating to the wrapped agent.

        Args:
            params: The A2A message send parameters
            trace_id: Langfuse trace ID for distributed tracing
            parent_span_id: Langfuse parent span ID for distributed tracing
            extensions: Optional extensions dict with conversationHistory, customerAccounts, etc.

        Returns:
            A2A message send success response with the agent's output

        Raises:
            Exception: If the agent execution fails
        """
        try:
            # Extract user text from message parts.
            # NOTE: a2a.types.Message wraps each entry in a Part(root=...) union, so
            # `isinstance(part, TextPart)` is always False — must check `part.root`.
            user_text = ""
            for part in params.message.parts:
                if isinstance(part.root, TextPart):
                    user_text = part.root.text
                    break

            if not user_text:
                raise ValueError("No text content found in message parts")

            # Extract metadata for context
            metadata = params.metadata or {}
            thread_id = metadata.get("session_id", "a2a-session")
            cif_code = metadata.get("customer_id", "")

            # Extract extensions for context parity with in-process execution
            ext = extensions or {}
            conversation_history = ext.get("conversation_history", [])

            # Replace last user message with current request (matching in-process behaviour)
            if conversation_history:
                conversation_history[-1] = {"role": "user", "content": user_text}
            else:
                conversation_history = [{"role": "user", "content": user_text}]

            # Parse request and reasoning from user_text
            # Agent pool combines them as: "request\n\nReasoning: reasoning"
            request_text = user_text
            reasoning_text = ""
            if "\n\nReasoning: " in user_text:
                parts = user_text.split("\n\nReasoning: ", 1)
                request_text = parts[0]
                reasoning_text = parts[1]

            # Build task dictionary for the agent with full context (matching construct_sub_task)
            task = {
                "conversation_history": conversation_history,
                "session_context": {
                    "current_agent": self.agent_name,
                    "resume_point": self.resume_point,
                    "agent_context": {
                        "customer_accounts": ext.get("customer_accounts"),
                        "account_context_loaded": ext.get("account_context_loaded"),
                        "account_service_used": ext.get("account_service_used"),
                    },
                },
                "cif_code": cif_code,
                "netbank_id": ext.get("netbank_id", ""),
                "dptoken": ext.get("dptoken"),
                # Layer 1 routing output (rewritten request) - CRITICAL for homeloans_agent
                "request": request_text,
                "reasoning": reasoning_text,
                # Layer 0/real user message (literal last customer utterance)
                "original_user_query": ext.get("original_user_query", ""),
            }

            # Call the agent
            logger.debug(
                f"Executing {self.agent_name} for A2A request: {user_text[:100]}...",
                extra={"trace_id": trace_id, "thread_id": thread_id},
            )
            subagent_output: SubAgentOutput = await self.agent.aexecute(
                task=task,
                thread_id=thread_id,
                connection_pool=self.connection_pool,
                parent_span_id=parent_span_id,
            )

            # Encode the full SubAgentOutput so the orchestrator receives every field
            # (message, ui_components, sources, tool_execution_data, tool_calls_with_inputs,
            # tool_input_schemas, synthesis_instructions) — matching what the in-process path
            # returns without any field omissions.
            # Use model_dump with mode="json" to recursively convert ALL nested Pydantic models
            # (including LiteLLM Message/Choices objects in tool_execution_data) to plain dicts.
            # This prevents Pydantic serialization warnings when a2a.types.Message is serialized,
            # as it won't encounter mismatched LiteLLM model types (6 fields vs 10 expected).
            subagent_output_dict = subagent_output.model_dump(mode="json")

            response_parts = [
                TextPart(text=subagent_output.message),
                DataPart(data={"__subagent_output__": subagent_output_dict}),
            ]

            # NOTE: The A2A protocol uses Role.agent (not "assistant") for AI responses.
            # LLM providers (OpenAI, Claude, Bedrock) use "assistant", but a2a.types.Message
            # only accepts Role.agent or Role.user — passing "assistant" raises a Pydantic
            # ValidationError that becomes an HTTP 400. See docs/a2a/role-mapping.md.
            response_message = Message(
                role=Role.agent,
                parts=response_parts,
                message_id=str(uuid4()),
            )

            return SendMessageSuccessResponse(
                jsonrpc="2.0",
                id=None,
                result=response_message,
            )

        except Exception:
            logger.exception(f"{self.agent_name} A2A executor failed")
            # Re-raise to allow proper JSON-RPC error propagation and A2A client fallback.
            # The FastAPI handler in a2a_server.py will catch this and return an HTTP 500
            # JSON-RPC error response, which triggers A2AClientError in the client,
            # enabling the orchestrator to fall back to in-process execution.
            raise
