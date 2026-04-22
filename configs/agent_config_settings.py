"""Agent-specific configuration settings for the Financial Companion Agent.

This module defines the AgentConfigSettings class, which extends the common
ConfigSettings with additional fields specific to the SampleOpenAIBasicAgent.
It also provides a cached configuration instance for use throughout the agent.
"""

import os
from functools import lru_cache

from pydantic import Field, field_validator

from common.configs.app_config_settings import AppConfigSettings


class AgentConfigSettings(AppConfigSettings):
    """Centralized configuration settings for enabling and disabling specific guardrails within the Guardrail system.

    Attributes:
        enable_complaint_check (bool): Toggle for complaint guardrail.
        enable_harmful_content_check (bool): Toggle for harmful content guardrail.
        enable_jailbreak_check (bool): Toggle for jailbreak guardrail.
        enable_offtopic_check (bool): Toggle for offtopic guardrail.
        enable_vulnerability_check (bool): Toggle for vulnerability guardrail.
        enable_quality_check (bool): Toggle for quality guardrail.
        enable_v3_guardrails_override (bool): Env var override to force-enable V3 guardrails regardless of LaunchDarkly.
    """

    ALLOWED_FINANCIAL_ADVICE_TYPES: list[str] = Field(
        default=["factual"],
        description="List of financial advice types allowed to be given, in order from safest to riskiest/hardest to reach compliance with",
    )

    # --- Agent temperature settings ---
    # Controls LLM response variability (0.0 = deterministic, 1.0 = creative).
    # Routing and synthesis use 0.0 for consistency; task agents use 0.1.
    # PRINCIPAL_AGENT_TEMPERATURE is shared by the general agent and the guardrail response agent.
    PRINCIPAL_AGENT_TEMPERATURE: float = Field(
        default=0.1,
        description="Temperature setting for principal agent responses",
    )

    ROUTING_AGENT_TEMPERATURE: float = Field(
        default=0.0,
        description="Temperature setting for routing (layer-1 intent classification) agent responses",
    )

    SYNTHESIS_AGENT_TEMPERATURE: float = Field(
        default=0.0,
        description="Temperature setting for synthesis agent responses",
    )

    HOMEBUYING_AGENT_TEMPERATURE: float = Field(
        default=0.05,
        description="Temperature setting for homebuying agent responses",
    )

    SAVINGS_AGENT_TEMPERATURE: float = Field(
        default=0.1,
        description="Temperature setting for savings agent responses",
    )

    PRODUCTS_AGENT_TEMPERATURE: float = Field(
        default=0.05,
        description="Temperature setting for products agent responses",
    )

    GUARDRAIL_RESPONSE_AGENT_TEMPERATURE: float = Field(
        default=0.1,
        description="Temperature setting for guardrail response agent",
    )

    FINANCIAL_ADVICE_SLM_THRESHOLD: float = Field(
        default=0.0017,
        description="Threshold for the financial advice SLM score to trigger quality check cascading",
        ge=0.0,
        le=1.0,
    )

    INTENT_CONFIDENCE_THRESHOLD: float = Field(
        default=0.4,
        description="Confidence threshold for intent classification routing decisions. Requests below this threshold are routed to general_queries.",
        ge=0.0,
        le=1.0,
    )

    ENABLE_INTENT_CLASSIFIER_PROMPT_CACHING: bool = Field(
        default=False,
        validation_alias="ENABLE_INTENT_CLASSIFIER_PROMPT_CACHING",
        description="Enable prompt caching metadata for layer 1 intent classification requests when the model supports it.",
    )

    ENABLE_SYNTHESIS_PROMPT_CACHING: bool = Field(
        default=False,
        validation_alias="ENABLE_SYNTHESIS_PROMPT_CACHING",
        description="Enable prompt caching metadata for layer 3 synthesis requests when the model supports it.",
    )

    ENABLE_GROUNDEDNESS_CHECK: bool = Field(
        default=False,
        description="Enable or disable the groundedness check guardrail.",
    )

    ENABLE_PROMPT_IN_CONTEXT: bool = Field(
        default=True,
        description="Enable or disable the groundedness context to take in directions from prompt.",
    )

    ENABLE_INPUT_PII_CHECK: bool = Field(
        default=True,
        description="Enable or disable the pii check input guardrail.",
    )

    ENABLE_OUTPUT_PII_CHECK: bool = Field(
        default=True,
        description="Enable or disable the pii check output guardrail.",
    )

    # PII Detection Configuration
    PII_PARAMETERS: list[dict[str, str]] = Field(
        default=[
            {
                "key": "filter_list",
                "value": "['AU_MEDICARE', 'CRN', 'DRIVERS_LICENSE', 'PASSPORT', 'AU_TFN', 'AU_ABN', 'AU_ACN', 'IBAN_CODE', 'CREDIT_CARD', 'USI', 'UNIQUE_SUPERANNUATION_IDENTIFIER', 'SUPERANNUATION_MEMBERSHIP', 'IMMI_CARD']",
            },
            {
                "key": "mask_rule",
                "value": '{"AU_MEDICARE": 0, "CRN": 0, "DRIVERS_LICENSE": 0, "PASSPORT": 0, "AU_TFN": 0, "AU_ABN": 4, "AU_ACN": 4, "IBAN_CODE": 4, "CREDIT_CARD": 4, "USI": 0, "UNIQUE_SUPERANNUATION_IDENTIFIER": 0, "SUPERANNUATION_MEMBERSHIP": 0, "IMMI_CARD": 0}',
            },
        ],
        description="List of PII types to detect and filter for Australian financial services, as well as their masking rules. PII masking rules: 0 = fully mask, >0 = show last N characters",
    )

    VULNERABILITY_PARAMETERS: list[dict[str, str]] = Field(
        default=[
            {"key": "vulnerability_strictness", "value": "0.0013"},
            {"key": "GAAS__SLM_ENABLED", "value": "True"},
        ],
        description="List of vulnerability parameters for vulnerability guardrail configuration.",
    )

    JAILBREAK_PARAMETERS: list[dict[str, str]] = Field(
        default=[
            {"key": "jailbreak_strictness", "value": "0.0132"},
            {"key": "GAAS__SLM_ENABLED", "value": "True"},
        ],
        description="List of jailbreak parameters for jailbreak guardrail configuration.",
    )

    COMPLAINT_PARAMETERS: list[dict[str, str]] = Field(
        default=[
            {"key": "complaint_strictness", "value": "0.0013"},
            {"key": "GAAS__SLM_ENABLED", "value": "True"},
        ],
        description="List of complaint parameters for complaint guardrail configuration.",
    )

    ENABLE_FINANCIAL_ADVICE_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the financial advice check guardrail.",
    )
    ENABLE_FINANCIAL_ADVICE_INPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the financial advice input check guardrail.",
    )
    ENABLE_DISPUTES_INPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the disputes detection input check guardrail.",
    )
    ENABLE_TOOL_FAITHFULNESS_CHECK: bool = Field(
        default=False,
        description="Enable or disable the tool faithfulness check guardrail.",
    )
    TOOL_FAITHFULNESS_PASS_THRESHOLD: float = Field(
        default=0.75,
        description="Threshold for tool faithfulness score to pass the guardrail check",
        ge=0.0,
        le=1.0,
    )
    TOOL_FAITHFULNESS_N_PARALLEL: int = Field(
        default=4,
        validation_alias="TOOL_FAITHFULNESS_N_PARALLEL",
        description="Number of parallel claims to evaluate simultaneously in tool faithfulness check",
        ge=1,
        le=10,
    )
    ENABLE_RELEVANCY_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the relevancy check output guardrail.",
    )
    RELEVANCY_PASS_THRESHOLD: float = Field(
        default=0.75,
        description="Threshold for relevancy score to pass the guardrail check",
        ge=0.0,
        le=1.0,
    )
    ENABLE_COMPLIANCE_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the compliance check output guardrail.",
    )
    COMPLIANCE_PASS_THRESHOLD: float = Field(
        default=0.75,
        description="Threshold for compliance score to pass the guardrail check",
        ge=0.0,
        le=1.0,
    )
    RELEVANT_CONTEXT_SECTIONS: list[str] = Field(
        default=["agent_role", "tools_and_process", "additional_information"],
        description="List of relevant context sections to include for groundedness and tool faithfulness checks",
    )
    ENABLE_PROFANITY_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the profanity check output guardrail.",
    )
    ENABLE_PROFANITY_INPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the profanity check input guardrail.",
    )
    ENABLE_COMPETITOR_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the competitor check output guardrail.",
    )
    ENABLE_COMPETITOR_INPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the competitor check input guardrail.",
    )
    ENABLE_LANGUAGE_CHECK: bool = Field(
        default=False,
        description="Enable or disable the language check guardrail.",
    )
    ENABLE_COMPLAINT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the complaint check guardrail.",
    )
    ENABLE_HARMFUL_CONTENT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the harmful content check guardrail.",
    )
    ENABLE_JAILBREAK_CHECK: bool = Field(
        default=False,
        description="Enable or disable the jailbreak check guardrail.",
    )
    JAILBREAK_TOOL_BLOCKING_EXCEPTIONS: list[str] = Field(
        default=[
            "classify_advice_type",
            "get_relevant_knowledge",
        ],
        description="List of tool names that should NOT be blocked by jailbreak guardrail. "
        "These tools can execute even if jailbreak check hasn't completed.",
    )
    ENABLE_OFFTOPIC_CHECK: bool = Field(
        default=False,
        description="Enable or disable the offtopic check guardrail.",
    )
    ENABLE_V3_GUARDRAILS_OVERRIDE: bool = Field(
        default=False,
        description="Env var override to force-enable V3 consolidated guardrails regardless of LaunchDarkly. When True, bypasses LD entirely. When False, defers to the LaunchDarkly flag 'enable-v3-guardrails'.",
    )
    ENABLE_VULNERABILITY_CHECK: bool = Field(
        default=False,
        description="Enable or disable the vulnerability check guardrail.",
    )
    ENABLE_QUALITY_CHECK: bool = Field(
        default=False,
        description="Enable or disable the quality check guardrail.",
    )
    GUARDRAILS_V3_MAX_MESSAGES: int = Field(
        default=6,  # three turns of conversation (user + assistant)
        description="Maximum number of messages to include in the input for guardrail checks.",
    )

    GUARDRAILS_V3_MODEL: str = Field(
        default="dev-syd-gai-digitalpla-eastus2-gpt-41-2025-04-14-NF-federated-gaip",
        description="Model deployment label for V3 guardrails LLM-based validators",
    )

    OPENAI_VOICE_KEY: str = Field(
        default="",
        validation_alias="OPENAI_VOICE_KEY",
        description="API key for authenticating with the OpenAI API",
    )

    SUB_AGENT_SHORTCUT: str = Field(
        default="",
        description="Direct sub-agent routing: SavingsAgent, ProductsAgent, HomebuyingAgent or empty for normal routing",
    )

    USE_LANGFUSE_PROMPT: bool = Field(
        default=False,
        description="This controls whether or not system prompts are being pulled from Langfuse prompt manager",
    )

    ENABLE_DEV_FEATURES: bool = Field(
        default=False,
        description="Controls development features, including restarting principal agent on execution",
    )

    # Memory Truncation Configuration
    MEMORY_TRUNCATION_STRATEGY: str = Field(
        default="sliding_window",
        validation_alias="MEMORY_TRUNCATION_STRATEGY",
        description="Strategy for truncating conversation history: 'sliding_window' or 'llm_summarisation'",
    )
    MAX_CONVERSATION_EXCHANGES: int = Field(
        default=20,
        validation_alias="MAX_CONVERSATION_EXCHANGES",
        description="Maximum number of customer back-and-forths to keep for sliding window strategy",
    )

    # Information Freshness Configuration
    MESSAGE_FRESHNESS_THRESHOLD_DAYS: int = Field(
        default=1,
        validation_alias="MESSAGE_FRESHNESS_THRESHOLD_DAYS",
        description=(
            "Number of days after which a historical conversation message is considered stale. "
            "Sub-agents will be instructed to re-confirm time-sensitive information "
            "(e.g. income, financial goals, employment status) from messages older than this threshold "
            "rather than assuming it is still current."
        ),
    )

    # Persona Usage Configuration
    ENABLE_PERSONA_USAGE: bool = Field(
        default=True,
        validation_alias="ENABLE_PERSONA_USAGE",
        description="Enable customer persona usage. If False, disables persona retrieval while keeping conversation history enabled.",
    )

    # Guardrail Response Configuration
    ENABLE_LLM_GUARDRAIL_RESPONSES: bool = Field(
        default=True,
        validation_alias="ENABLE_LLM_GUARDRAIL_RESPONSES",
        description="Enable LLM-based dynamic guardrail response generation",
    )
    GUARDRAIL_FALLBACK_TO_PRECANNED: bool = Field(
        default=True,
        validation_alias="GUARDRAIL_FALLBACK_TO_PRECANNED",
        description="Fall back to precanned responses if LLM generation fails",
    )
    GUARDRAIL_MAX_RETRIES: int = Field(
        default=3,
        validation_alias="GUARDRAIL_MAX_RETRIES",
        description="Maximum number of retry attempts for guardrail response generation",
    )
    GUARDRAIL_RETRY_DELAY: float = Field(
        default=1.0,
        validation_alias="GUARDRAIL_RETRY_DELAY",
        description="Delay between retry attempts in seconds",
    )
    GUARDRAIL_MAX_CONVERSATION_HISTORY: int = Field(
        default=10,
        validation_alias="GUARDRAIL_MAX_CONVERSATION_HISTORY",
        description="Maximum conversation history items to include in guardrail context",
    )

    # Guardrail Service Error Retry Configuration
    GUARDRAIL_ERROR_MAX_RETRIES: int = Field(
        default=3,
        validation_alias="GUARDRAIL_ERROR_MAX_RETRIES",
        description="Maximum number of retry attempts when guardrail service calls fail",
    )
    GUARDRAIL_ERROR_RETRY_DELAY: float = Field(
        default=1.0,
        validation_alias="GUARDRAIL_ERROR_RETRY_DELAY",
        description="Delay between retry attempts for guardrail service errors in seconds",
    )

    # Per-Agent Model Configuration
    FINANCIAL_COMPANION_AGENT_LLM: str = Field(
        default="",
        validation_alias="FINANCIAL_COMPANION_AGENT_LLM",
        description="Model name for the main Financial Companion Agent. Falls back to AGENT_LLM if not set.",
    )

    SAVINGS_AGENT_LLM: str = Field(
        default="",
        validation_alias="SAVINGS_AGENT_LLM",
        description="Model name for the Savings Agent. Falls back to AGENT_LLM if not set.",
    )

    PRODUCTS_AGENT_LLM: str = Field(
        default="",
        validation_alias="PRODUCTS_AGENT_LLM",
        description="Model name for the Products Agent. Falls back to AGENT_LLM if not set.",
    )

    HOMEBUYING_AGENT_LLM: str = Field(
        default="",
        validation_alias="HOMEBUYING_AGENT_LLM",
        description="Model name for the Homebuying Agent. Falls back to AGENT_LLM if not set.",
    )

    PAYMENT_AGENT_FEATURE_FLAG: bool = Field(
        default=False,
        validation_alias="PAYMENT_AGENT_FEATURE_FLAG",
        description="Enable Payment SubAgent and tools for Financial Companion Agent",
    )

    PAYMENT_AGENT_LLM: str = Field(
        default="",
        validation_alias="PAYMENT_AGENT_LLM",
        description="Model name for the Payment Agent. Falls back to AGENT_LLM if not set.",
    )

    GUARDRAILS_RESPONSE_LLM: str = Field(
        default="",
        validation_alias="GUARDRAILS_RESPONSE_LLM",
        description="Model name for the Guardrails Response Generation. Falls back to AGENT_LLM if not set.",
    )

    TOOL_FAITHFULNESS_CLAIMS_EXTRACTION_LLM: str = Field(
        default="",
        validation_alias="TOOL_FAITHFULNESS_CLAIMS_EXTRACTION_LLM",
        description="LLM model for tool faithfulness claims extraction (response claims and UI claims)",
    )

    TOOL_FAITHFULNESS_CLAIMS_EVALUATION_LLM: str = Field(
        default="",
        validation_alias="TOOL_FAITHFULNESS_CLAIMS_EVALUATION_LLM",
        description="LLM model for tool faithfulness claims evaluation (faithfulness evaluation)",
    )

    RELEVANCY_GUARDRAIL_LLM: str = Field(
        default="",
        validation_alias="RELEVANCY_GUARDRAIL_LLM",
        description="Model name for the Relevancy guardrail. Falls back to AGENT_LLM if not set.",
    )

    INVESTINGHUB_AGENT_LLM: str = Field(
        default="",
        validation_alias="INVESTINGHUB_AGENT_LLM",
        description="Model name for the Investinghub Agent. Falls back to AGENT_LLM if not set.",
    )

    SQL_QUERY_TOOL_LLM: str = Field(
        default="",
        validation_alias="SQL_QUERY_TOOL_LLM",
        description="Model name for the sql query tool. Falls back to AGENT_LLM if it's not set.",
    )

    TITLE_GENERATION_LLM: str = Field(
        default="openai/gpt-4.1_v2025-04-14_EASTUS2",
        validation_alias="TITLE_GENERATION_LLM",
        description="Model name for conversation title generation. Falls back to FINANCIAL_COMPANION_AGENT_LLM then AGENT_LLM if not set. Use a faster/cheaper model for efficiency.",
    )

    INVESTING_HUB_SECURITIES_API_URL: str = Field(
        default="",
        validation_alias="INVESTING_HUB_SECURITIES_API_URL",
        description="Base URL for the Securities Lookup API used by the InvestingHub Agent",
    )

    INVESTING_HUB_SECURITIES_API_SCOPE: str = Field(
        default="investing-companion-read",
        validation_alias="INVESTING_HUB_SECURITIES_API_SCOPE",
        description="API scope for Securities Lookup API",
    )

    INVESTING_HUB_FEATURE_FLAG_ALL_TOOLS: bool = Field(
        default=False,
        validation_alias="INVESTING_HUB_FEATURE_FLAG_ALL_TOOLS",
        description="Enable Investing SubAgent and tools for Financial Companion Agent",
    )

    ENABLE_CONVERSATION_HISTORY_SEARCH: bool = Field(
        default=False,
        validation_alias="ENABLE_CONVERSATION_HISTORY_SEARCH",
        description="Enable search_customer_history tool for agents",
    )

    INVESTING_HUB_FEATURE_FLAG_PHASE_2: bool = Field(
        default=False,
        validation_alias="INVESTING_HUB_FEATURE_FLAG_PHASE_2",
        description="Enable Phase 2 features for InvestingHub Agent",
    )
    # Investing Hub Agent Specific Guardrail Configuration
    # NOTE: These flags are currently not used in the guardrail decision logic.
    # Guardrails are applied based on: called_from_fc, is_experimental, and INVESTING_HUB_FEATURE_FLAG_PHASE_2.
    # These flags are kept for future flexibility when Phase 2 flag is removed and/or we need
    # more granular control over InvestingHub guardrails. Should also try to align with overall guardrail strategy.
    ENABLE_INVESTING_HUB_INPUT_GUARDRAILS: bool = Field(
        default=True,
        validation_alias="ENABLE_INVESTING_HUB_INPUT_GUARDRAILS",
        description="[RESERVED FOR FUTURE USE] Enable or disable all input guardrails for Investing Hub agent. "
        "Currently not used - guardrails are controlled by called_from_fc, is_experimental, and phase 2 flags.",
    )
    ENABLE_INVESTING_HUB_OUTPUT_GUARDRAILS: bool = Field(
        default=True,
        validation_alias="ENABLE_INVESTING_HUB_OUTPUT_GUARDRAILS",
        description="[RESERVED FOR FUTURE USE] Enable or disable all output guardrails for Investing Hub agent. "
        "Currently not used - guardrails are controlled by called_from_fc, is_experimental, and phase 2 flags.",
    )

    INVESTINGHUB_ENABLE_RUNTIME_SCORING: bool = Field(
        default=False,
        validation_alias="INVESTINGHUB_ENABLE_RUNTIME_SCORING",
        description="Enable or disable runtime scoring for InvestingHub Agent tool executions. "
        "When enabled, tool executions are scored for correctness and success, with results sent to Langfuse.",
    )

    SYNTHESIS_AGENT_LLM: str = Field(
        default="",
        validation_alias="SYNTHESIS_AGENT_LLM",
        description="Model name for the Synthesis Agent. Falls back to AGENT_LLM if not set.",
    )

    PROMPT_OPTIMIZER_LLM: str = Field(
        default="",
        validation_alias="PROMPT_OPTIMIZER_LLM",
        description="Model name for the Prompt Optimizer Agent. Falls back to AGENT_LLM if not set.",
    )

    # Progress Store Configuration
    INTERIM_PROGRESS_STORE_MAX_AGE_SECONDS: int = Field(
        default=600,
        validation_alias="INTERIM_PROGRESS_STORE_MAX_AGE_SECONDS",
        description="Maximum age in seconds for progress store sessions before cleanup (default: 10 minutes)",
    )
    INTERIM_PROGRESS_STORE_CLEANUP_CYCLE_SECONDS: int = Field(
        default=300,
        validation_alias="INTERIM_PROGRESS_STORE_CLEANUP_CYCLE_SECONDS",
        description="Cleanup cycle interval in seconds for progress store background worker (default: 5 minutes)",
    )

    # A2A Protocol Configuration
    A2A_ENABLED: bool = Field(
        default=False,
        validation_alias="A2A_ENABLED",
        description="Enable A2A protocol for all sub-agent (Products, Savings, Home Loans) communication. "
        "When True, the principal agent calls each sub-agent via A2A JSON-RPC over localhost. "
        "When False, uses existing in-process Python calls.",
    )

    A2A_CARDS_DIR: str = Field(
        default="common/a2a/agent_cards",
        validation_alias="A2A_CARDS_DIR",
        description="Directory containing agent card JSON files.",
    )

    A2A_CLIENT_TIMEOUT_SECONDS: int = Field(
        default=30,
        validation_alias="A2A_CLIENT_TIMEOUT_SECONDS",
        description="HTTP timeout in seconds for A2A client calls.",
    )

    A2A_AGENTS_CONFIG: str = Field(
        default="common/a2a/config/a2a_agents.yaml",
        validation_alias="A2A_AGENTS_CONFIG",
        description="Path to YAML config file listing all A2A agents (internal + external).",
    )

    A2A_ROUTING_ENABLED: bool = Field(
        default=False,
        validation_alias="A2A_ROUTING_ENABLED",
        description="Enable A2A protocol routing for all eligible agents. "
        "When True, eligible sub-agent requests are routed via A2A JSON-RPC with in-process fallback. "
        "When False, uses existing in-process Python calls directly.",
    )

    A2A_SERVER_HOST: str = Field(
        default="127.0.0.1",
        validation_alias="A2A_SERVER_HOST",
        description="Host address to bind A2A servers to. Use '127.0.0.1' for localhost-only (secure, default), "
        "or '0.0.0.0' to allow external access (required for Docker port forwarding).",
    )

    @field_validator("ALLOWED_FINANCIAL_ADVICE_TYPES")
    @classmethod
    def validate_allowed_financial_advice_types(cls, v: list[str]) -> list[str]:
        """Validate that ALLOWED_FINANCIAL_ADVICE_TYPES meets the required constraints.

        Args:
            v: The list of allowed financial advice types

        Returns:
            The validated list

        Raises:
            ValueError: If validation fails
        """
        # Check length constraints
        max_advice_types = 4
        if not 1 <= len(v) <= max_advice_types:
            raise ValueError(
                f"ALLOWED_FINANCIAL_ADVICE_TYPES must contain between 1 and {max_advice_types} items, got {len(v)}"
            )

        # Define valid types in the required order
        valid_types = ["factual", "general", "personal", "scaled"]

        # Check that all values are valid
        invalid_types = [t for t in v if t not in valid_types]
        if invalid_types:
            raise ValueError(
                f"ALLOWED_FINANCIAL_ADVICE_TYPES contains invalid types: {invalid_types}. "
                f"Valid types are: {valid_types}"
            )

        # Check that the order is correct (must be a subset in the same order)
        # Find the indices of the provided types in the valid_types list
        indices = [valid_types.index(t) for t in v]

        # Check if indices are in ascending order (maintaining the required sequence)
        if indices != sorted(indices):
            raise ValueError(
                f"ALLOWED_FINANCIAL_ADVICE_TYPES must maintain the required order: {valid_types}. Got: {v}"
            )

        return v


@lru_cache
def get_agent_config() -> AgentConfigSettings:
    """Returns a cached instance of the application configuration.

    Using this function instead of directly accessing the Config instance
    ensures that the configuration is loaded only when needed and cached
    for subsequent calls.

    Returns:
        AgentConfigSettings: The application configuration instance
    """
    config = AgentConfigSettings()
    # Set environment variables read in from .env or .env.local
    if config.model_extra is not None:
        for key, value in config.model_extra.items():
            os.environ[key] = str(value)

    return config


# Global configuration instance - use get_agent_config() instead for new code
AgentConfig = get_agent_config()
