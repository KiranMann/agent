from enum import StrEnum

from pydantic import BaseModel, Field

from common.models.domain_descriptions import get_all_domains, get_domain_description

SUB_AGENT_REQUEST_DESCRIPTION: str = (
    "A clear, concise summary of what the customer wants from this sub-agent, distilled from the full conversation. "
    "Summarise the customer's intent in plain language — do not copy the query verbatim, and do not add solution steps, "
    "instructions, or implementation details the customer did not express. "
    "If the message is long or contains irrelevant content, extract only what is relevant to this agent. "
    "Include context from conversation history only if it directly clarifies the intent."
)


class AgentName(StrEnum):
    """Agent domain names for routing.

    These values must match the domain names in DOMAIN_DESCRIPTIONS.
    """

    HOMEBUYING = "homebuying"
    PRODUCTS = "products"
    SAVINGS = "savings"
    GENERAL_QUERIES = "general_queries"
    WEATHER = "weather"


class SubAgentRequest(BaseModel):
    name: AgentName = Field(
        ...,
        description=(
            "Allowed Values:\n"
            + "\n".join(f"{domain}: {get_domain_description(domain)}" for domain in get_all_domains())
        ),
    )
    request: str = Field(
        ...,
        min_length=1,
        description=SUB_AGENT_REQUEST_DESCRIPTION,
    )
    reasoning: str = Field(..., min_length=1, description="Why did you make this request to this agent")
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence level (0.0 to 1.0) for routing to this agent based on domain indicators and query clarity",
    )


class SubAgentRequests(BaseModel):
    sub_agent_requests: list[SubAgentRequest]
