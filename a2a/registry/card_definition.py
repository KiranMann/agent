"""Typed definitions for enriched local A2A agent cards.

These models preserve Financial Companion-specific routing and operational
metadata while still allowing the upstream A2A SDK to consume the transport
subset of the card.
"""

from typing import Any, Literal

from a2a.types import AgentCard
from pydantic import BaseModel, ConfigDict, Field


class AgentCardProviderMetadata(BaseModel):
    """Provider metadata stored alongside an agent card."""

    organization: str
    url: str | None = None
    team: str | None = None
    contact_email: str | None = Field(default=None, alias="contactEmail")
    slack_channel: str | None = Field(default=None, alias="slackChannel")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AgentCardQueryExamples(BaseModel):
    """Few-shot routing examples for classifier prompts."""

    should_route: list[str] = Field(alias="shouldRoute")
    should_not_route: list[str] = Field(alias="shouldNotRoute")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AgentCardBoundaries(BaseModel):
    """Explicit routing scope boundaries for an agent."""

    handles: list[str]
    does_not_handle: list[str] = Field(alias="doesNotHandle")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AgentCardRoutingMetadata(BaseModel):
    """Routing metadata required for future card-based classification."""

    short_description: str = Field(alias="shortDescription")
    detailed_guidance: str | None = Field(default=None, alias="detailedGuidance")
    domain_aliases: list[str] = Field(alias="domainAliases")
    query_examples: AgentCardQueryExamples = Field(alias="queryExamples")
    boundaries: AgentCardBoundaries
    trigger_keywords: list[str] | None = Field(default=None, alias="triggerKeywords")
    handoff_notes: str | None = Field(default=None, alias="handoffNotes")
    priority: str | None = None
    requires_authentication: bool | None = Field(default=None, alias="requiresAuthentication")
    parallel_execution_group: str | None = Field(default=None, alias="parallelExecutionGroup")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AgentCardSlaMetadata(BaseModel):
    """Operational latency and availability targets for an agent."""

    p50_latency_ms: int | None = Field(default=None, alias="p50LatencyMs")
    p99_latency_ms: int | None = Field(default=None, alias="p99LatencyMs")
    availability_target: str | None = Field(default=None, alias="availabilityTarget")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AgentCardCbaMetadata(BaseModel):
    """CBA-specific operational metadata embedded in agent cards."""

    domain: str
    environment: str
    classification: str
    data_classification: str | None = Field(default=None, alias="dataClassification")
    health_check_url: str | None = Field(default=None, alias="healthCheckUrl")
    runbook_url: str | None = Field(default=None, alias="runbookUrl")
    sla: AgentCardSlaMetadata | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AgentCardDefinition(BaseModel):
    """Local enriched agent card definition.

    The upstream ``a2a.types.AgentCard`` model only preserves transport fields.
    This model retains the broader card definition used for future routing and
    operational metadata while still being convertible to the transport model.
    """

    name: str
    description: str
    url: str
    version: str
    protocol_version: str | None = Field(default=None, alias="protocolVersion")
    preferred_transport: str | None = Field(default=None, alias="preferredTransport")
    provider: AgentCardProviderMetadata | None = None
    capabilities: dict[str, Any]
    skills: list[dict[str, Any]]
    default_input_modes: list[str] = Field(alias="defaultInputModes")
    default_output_modes: list[str] = Field(alias="defaultOutputModes")
    authentication: dict[str, Any] | None = None
    security: list[dict[str, list[str]]] | None = None
    security_schemes: dict[str, dict[str, Any]] | None = Field(default=None, alias="securitySchemes")
    routing: AgentCardRoutingMetadata | None = None
    cba: AgentCardCbaMetadata | None = None
    documentation_url: str | None = Field(default=None, alias="documentationUrl")
    icon_url: str | None = Field(default=None, alias="iconUrl")

    # New fields for A2A optimization
    agent_domain: str | None = Field(
        default=None,
        alias="domain",
        description="Canonical agent domain identifier (e.g., 'products', 'weather'). All other name formats are derived from this.",
    )

    agent_type: str | None = Field(
        default=None,
        description="AgentType enum value. Auto-inferred from domain if not provided (e.g., 'products' -> 'ProductsAgent')",
    )

    deployment: Literal["internal", "external"] = Field(
        default="external",
        description="Whether agent is internal (needs executor + A2A server) or external (A2A only)",
    )

    port: int | None = Field(
        default=None,
        description="Port for internal A2A server. Required if deployment=internal",
    )

    pool_attribute: str | None = Field(
        default=None,
        alias="poolAttribute",
        description="Attribute name on AgentPool (e.g., 'products_agent'). Auto-inferred from domain if absent.",
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_transport_card(self) -> AgentCard:
        """Convert the enriched definition into the upstream A2A transport card."""
        return AgentCard(**self.model_dump(by_alias=True, exclude_none=True))

    def inferred_agent_domain(self) -> str:
        """Get the canonical agent domain identifier, auto-inferring from card name if not set.

        Returns:
            The agent domain identifier as a string. If agent_domain is explicitly set, returns it.
            Otherwise, derives from the card name:
            - "products-agent" -> "products"
            - "weather-agent" -> "weather"
            - "general-queries-agent" -> "general_queries"
        """
        if self.agent_domain:
            return self.agent_domain
        # Remove "-agent" suffix and convert remaining hyphens to underscores
        return self.name.removesuffix("-agent").replace("-", "_")

    def inferred_card_name(self) -> str:
        """Derive the A2A card name from agent domain.

        Returns:
            The card name in kebab-case with '-agent' suffix:
            - 'products' -> 'products-agent'
            - 'general_queries' -> 'general-queries-agent'
        """
        return f"{self.inferred_agent_domain().replace('_', '-')}-agent"

    def inferred_agent_type(self) -> str:
        """Get the AgentType enum value, auto-inferring from agent domain.

        Returns:
            The AgentType enum value in PascalCase with 'Agent' suffix:
            - "products" -> "ProductsAgent"
            - "general_queries" -> "GeneralQueriesAgent"
            - "dispute" -> "DisputeAgent"
        """
        if self.agent_type:
            return self.agent_type
        domain = self.inferred_agent_domain()
        # Split by underscore, capitalize each part, join together
        parts = domain.split("_")
        return "".join(p.title() for p in parts) + "Agent"

    def inferred_pool_attribute(self) -> str:
        """Get the agent pool attribute name.

        Returns:
            The pool attribute name in snake_case with '_agent' suffix:
            - 'products' -> 'products_agent'
            - 'general_queries' -> 'general_queries_agent'
        """
        if self.pool_attribute:
            return self.pool_attribute
        return f"{self.inferred_agent_domain()}_agent"
