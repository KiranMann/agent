"""Feature flag constants for LaunchDarkly integration.

This module contains the FeatureFlags class with all feature flag key constants
used throughout the Financial Companion application. By separating these constants
into their own module, developers can easily modify flag keys without risk of
affecting the LaunchDarkly service implementation.
"""


class FeatureFlags:
    """Constants for LaunchDarkly feature flag keys."""

    # Flags only for testing purposes
    TEST_FLAG = "test-flag"
    ENABLE_CM_INTEGRATION = "enable-cm-integration"
    ENABLE_DIALOGUE_MONITORING = "enable-dialogue-monitoring"

    # Personalisation feature flag
    ENABLE_PERSONALISATION = "enable-personalisation"

    # Guardrails feature flags
    ENABLE_V3_GUARDRAILS = "enable-v3-guardrails"

    # RAG feature flag
    USE_LD_KNOWLEDGE_BASE_ID = "use-ld-knowledge-base-id"

    # A2A protocol feature flags
    A2A_ENABLED = "a2a-enabled"
    A2A_ROUTING_ENABLED = "a2a-routing-enabled"
