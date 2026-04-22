"""A2A configuration validation at application startup.

This module provides validation functions for the A2A agent configuration
that run at FastAPI application startup. Validation errors are logged but
do not prevent the application from starting, surfacing issues early while
maintaining availability.
"""

from http import HTTPStatus
from pathlib import Path

import httpx

from common.a2a.config import A2AAgentsConfig
from common.a2a.registry.local_registry import LocalAgentRegistry
from common.configs.agent_config_settings import get_agent_config
from common.logging.core import logger
from common.models.sub_agent_request import AgentName

# Module-level constant for validation log messages
_VALIDATION_LOG_PREFIX = "A2A config validation"


class A2AConfigValidationError:
    """Represents a single validation error."""

    def __init__(self, severity: str, category: str, message: str) -> None:
        """Initialize validation error.

        Args:
            severity: Error severity (ERROR, WARNING, INFO)
            category: Error category (config_enum_mismatch, missing_url, etc.)
            message: Human-readable error message
        """
        self.severity = severity
        self.category = category
        self.message = message

    def __str__(self) -> str:
        """Format error for logging."""
        return f"[{self.severity}] {self.category}: {self.message}"


def _validate_external_agent_urls(agents_config: A2AAgentsConfig) -> list[A2AConfigValidationError]:
    """Validate external agents have URLs and proper format.

    Args:
        agents_config: Parsed A2A agents configuration

    Returns:
        List of validation errors found
    """
    errors: list[A2AConfigValidationError] = []

    for agent in agents_config.agents:
        if agent.type == "external" and agent.enabled and not agent.url:
            error = A2AConfigValidationError(
                severity="ERROR",
                category="external_agent_missing_url",
                message=f"External agent '{agent.name}' is enabled but has no URL configured",
            )
            errors.append(error)

    return errors


def _validate_agent_name_conventions(agents_config: A2AAgentsConfig) -> list[A2AConfigValidationError]:
    """Validate agent names follow conventions and have descriptions.

    Args:
        agents_config: Parsed A2A agents configuration

    Returns:
        List of validation errors found
    """
    errors: list[A2AConfigValidationError] = []

    for agent in agents_config.agents:
        if not agent.name.islower() or " " in agent.name:
            error = A2AConfigValidationError(
                severity="WARNING",
                category="agent_name_convention",
                message=f"Agent name '{agent.name}' should be lowercase without spaces (use hyphens for multi-word names)",
            )
            errors.append(error)

        if not agent.description:
            error = A2AConfigValidationError(
                severity="WARNING",
                category="missing_description",
                message=f"Agent '{agent.name}' is missing a description",
            )
            errors.append(error)

    return errors


def _validate_enum_consistency(
    enabled_agents: set[str],
    config_agents: set[str],
) -> list[A2AConfigValidationError]:
    """Validate consistency between config and AgentName enum.

    Args:
        enabled_agents: Set of enabled agent names from config
        config_agents: Set of all agent names from config

    Returns:
        List of validation errors found
    """
    errors: list[A2AConfigValidationError] = []
    enum_values = {agent.value for agent in AgentName}
    builtin_agents = {"general_queries"}  # Agents that don't need config entries

    # Check: All enabled agents in config should have enum values
    missing_from_enum = enabled_agents - enum_values
    if missing_from_enum:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="config_enum_mismatch",
            message=(
                f"Agents enabled in config but missing from AgentName enum: {missing_from_enum}. "
                f"Add these to common/models/sub_agent_request.py:AgentName"
            ),
        )
        errors.append(error)

    # Check: All enum values should exist in config or be built-in
    orphaned_enum_values = enum_values - config_agents - builtin_agents
    if orphaned_enum_values:
        error = A2AConfigValidationError(
            severity="WARNING",
            category="enum_config_mismatch",
            message=(
                f"Agents in AgentName enum but missing from config: {orphaned_enum_values}. "
                f"Either add them to a2a_agents.yaml or remove from enum"
            ),
        )
        errors.append(error)

    return errors


def _validate_internal_agents_enabled(internal_agents: set[str]) -> list[A2AConfigValidationError]:
    """Validate expected internal agents are enabled.

    Args:
        internal_agents: Set of enabled internal agent names

    Returns:
        List of validation errors found
    """
    errors: list[A2AConfigValidationError] = []
    expected_internal = {"products", "savings", "homebuying"}

    if not expected_internal.issubset(internal_agents):
        missing_internal = expected_internal - internal_agents
        error = A2AConfigValidationError(
            severity="WARNING",
            category="missing_internal_agents",
            message=f"Expected internal agents not enabled in config: {missing_internal}",
        )
        errors.append(error)

    return errors


def _validate_a2a_enabled_state(
    a2a_enabled: bool,
    external_agents: set[str],
) -> list[A2AConfigValidationError]:
    """Validate A2A enabled state consistency with external agents.

    Args:
        a2a_enabled: Whether A2A is enabled in configuration
        external_agents: Set of enabled external agent names

    Returns:
        List of validation errors found
    """
    errors: list[A2AConfigValidationError] = []

    if not a2a_enabled and external_agents:
        error = A2AConfigValidationError(
            severity="INFO",
            category="external_agents_ignored",
            message=(
                f"A2A_ENABLED=false but external agents are enabled in config: {external_agents}. "
                f"These agents will be ignored and excluded from routing."
            ),
        )
        errors.append(error)

    return errors


def validate_a2a_config_startup() -> list[A2AConfigValidationError]:
    """Validate A2A configuration at application startup.

    Performs comprehensive validation of a2a_agents.yaml configuration and
    AgentName enum consistency. Returns all validation errors found.

    This function is designed to be called during FastAPI lifespan startup.
    All errors are collected and returned rather than raising exceptions,
    allowing the application to start even with configuration issues.

    Returns:
        List of A2AConfigValidationError instances. Empty list if valid.
    """
    errors: list[A2AConfigValidationError] = []
    config = get_agent_config()

    # Step 1: Load and parse configuration file
    try:
        config_path = Path(config.A2A_AGENTS_CONFIG)
        agents_config = A2AAgentsConfig.from_yaml(config_path)
        logger.info(
            f"A2A config loaded successfully from {config_path}",
            extra={"agent_count": len(agents_config.agents), "config_path": str(config_path)},
        )
    except FileNotFoundError:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="config_file_missing",
            message=f"A2A configuration file not found: {config.A2A_AGENTS_CONFIG}",
        )
        errors.append(error)
        return errors
    except Exception as e:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="config_parse_error",
            message=f"Failed to parse A2A configuration: {e}",
        )
        errors.append(error)
        return errors

    # Step 2: Validate config structure
    enabled_agents = {agent.name for agent in agents_config.agents if agent.enabled}
    internal_agents = {agent.name for agent in agents_config.agents if agent.type == "internal" and agent.enabled}
    external_agents = {agent.name for agent in agents_config.agents if agent.type == "external" and agent.enabled}

    logger.info(
        "A2A agent configuration summary",
        extra={
            "total_agents": len(agents_config.agents),
            "enabled_agents": len(enabled_agents),
            "internal_agents": len(internal_agents),
            "external_agents": len(external_agents),
        },
    )

    # Run validation checks using helper functions
    errors.extend(_validate_external_agent_urls(agents_config))
    errors.extend(_validate_agent_name_conventions(agents_config))

    config_agents = {agent.name for agent in agents_config.agents}
    errors.extend(_validate_enum_consistency(enabled_agents, config_agents))
    errors.extend(_validate_internal_agents_enabled(internal_agents))
    errors.extend(_validate_a2a_enabled_state(config.A2A_ENABLED, external_agents))

    return errors


def log_a2a_config_validation_results(errors: list[A2AConfigValidationError]) -> None:
    """Log A2A configuration validation results.

    Groups errors by severity and logs them appropriately. This function
    is designed to make validation issues visible in application logs
    during startup without crashing the application.

    Args:
        errors: List of validation errors from validate_a2a_config_startup()
    """
    if not errors:
        logger.info("✓ A2A configuration validation passed - no issues found")
        return

    # Group errors by severity
    errors_by_severity: dict[str, list[A2AConfigValidationError]] = {"ERROR": [], "WARNING": [], "INFO": []}

    for error in errors:
        errors_by_severity[error.severity].append(error)

    # Log summary
    error_count = len(errors_by_severity["ERROR"])
    warning_count = len(errors_by_severity["WARNING"])
    info_count = len(errors_by_severity["INFO"])

    logger.warning(
        f"A2A configuration validation completed with issues: "
        f"{error_count} error(s), {warning_count} warning(s), {info_count} info",
        extra={"error_count": error_count, "warning_count": warning_count, "info_count": info_count},
    )

    # Log each error with appropriate severity
    for error in errors_by_severity["ERROR"]:
        logger.error(
            f"{_VALIDATION_LOG_PREFIX}: %s", error, extra={"category": error.category, "severity": error.severity}
        )

    for error in errors_by_severity["WARNING"]:
        logger.warning(
            f"{_VALIDATION_LOG_PREFIX}: %s", error, extra={"category": error.category, "severity": error.severity}
        )

    for error in errors_by_severity["INFO"]:
        logger.info(
            f"{_VALIDATION_LOG_PREFIX}: %s", error, extra={"category": error.category, "severity": error.severity}
        )

    # Add guidance for errors
    if errors_by_severity["ERROR"]:
        logger.error(
            "⚠️  Critical A2A configuration errors detected. "
            "See docs/a2a/adding-external-agents.md for configuration guide."
        )


async def _check_internal_agent_health(
    agent_name: str,
    cards_dir: str,
) -> list[A2AConfigValidationError]:
    """Check health of a single internal agent.

    Args:
        agent_name: Name of the internal agent to check
        cards_dir: Directory containing agent cards

    Returns:
        List of validation errors for this agent
    """
    errors: list[A2AConfigValidationError] = []

    try:
        registry = LocalAgentRegistry()
        registry.load(cards_dir)
        card_name = f"{agent_name}-agent"
        card_definition = registry.get_agent_card_definition(card_name)

        if not card_definition or not card_definition.cba or not card_definition.cba.health_check_url:
            error = A2AConfigValidationError(
                severity="WARNING",
                category="health_check_url_missing",
                message=f"Internal agent '{agent_name}' has no health check URL in card",
            )
            errors.append(error)
            return errors

        health_url = card_definition.cba.health_check_url

        # Perform health check with short timeout
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(health_url, timeout=5.0)
                if response.status_code == HTTPStatus.OK:
                    logger.info(f"✓ Internal agent '{agent_name}' health check passed: {health_url}")
                else:
                    error = A2AConfigValidationError(
                        severity="ERROR",
                        category="internal_agent_unhealthy",
                        message=f"Internal agent '{agent_name}' health check failed with status {response.status_code}: {health_url}",
                    )
                    errors.append(error)
            except httpx.TimeoutException:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="internal_agent_timeout",
                    message=f"Internal agent '{agent_name}' health check timed out (>5s): {health_url}",
                )
                errors.append(error)
            except httpx.ConnectError:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="internal_agent_unreachable",
                    message=f"Internal agent '{agent_name}' not reachable - server may not have started: {health_url}",
                )
                errors.append(error)
            except Exception as e:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="internal_agent_health_error",
                    message=f"Internal agent '{agent_name}' health check error: {e}",
                )
                errors.append(error)

    except Exception as e:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="health_check_exception",
            message=f"Failed to check health for internal agent '{agent_name}': {e}",
        )
        errors.append(error)

    return errors


async def _check_external_agent_health(
    agent_name: str,
    agent_url: str,
) -> list[A2AConfigValidationError]:
    """Check health of a single external agent.

    Args:
        agent_name: Name of the external agent to check
        agent_url: Base URL of the external agent

    Returns:
        List of validation errors for this agent
    """
    errors: list[A2AConfigValidationError] = []
    base_url = agent_url.rstrip("/")
    health_url = f"{base_url}/health"

    try:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(health_url, timeout=5.0)
                if response.status_code == HTTPStatus.OK:
                    logger.info(f"✓ External agent '{agent_name}' health check passed: {health_url}")
                else:
                    error = A2AConfigValidationError(
                        severity="ERROR",
                        category="external_agent_unhealthy",
                        message=f"External agent '{agent_name}' health check failed with status {response.status_code}: {health_url}",
                    )
                    errors.append(error)
            except httpx.TimeoutException:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="external_agent_timeout",
                    message=f"External agent '{agent_name}' health check timed out (>5s): {health_url}",
                )
                errors.append(error)
            except httpx.ConnectError:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="external_agent_unreachable",
                    message=f"External agent '{agent_name}' not reachable at {health_url}",
                )
                errors.append(error)
            except Exception as e:
                error = A2AConfigValidationError(
                    severity="ERROR",
                    category="external_agent_health_error",
                    message=f"External agent '{agent_name}' health check error: {e}",
                )
                errors.append(error)

    except Exception as e:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="health_check_exception",
            message=f"Failed to check health for external agent '{agent_name}': {e}",
        )
        errors.append(error)

    return errors


async def validate_agent_health_checks() -> list[A2AConfigValidationError]:
    """Validate agent health checks at application startup.

    Performs health checks on all enabled agents (both internal A2A servers
    and external agents). Returns all health check errors found.

    This function is designed to be called during FastAPI lifespan startup
    AFTER A2A servers have been started. All errors are collected and returned
    rather than raising exceptions, allowing the application to start even
    with unhealthy agents.

    Returns:
        List of A2AConfigValidationError instances. Empty list if all healthy.
    """
    errors: list[A2AConfigValidationError] = []
    config = get_agent_config()

    # Only check health if A2A is enabled
    if not config.A2A_ENABLED:
        logger.info("A2A disabled - skipping agent health checks")
        return errors

    # Load agent configuration
    try:
        config_path = Path(config.A2A_AGENTS_CONFIG)
        agents_config = A2AAgentsConfig.from_yaml(config_path)
    except Exception as e:
        error = A2AConfigValidationError(
            severity="ERROR",
            category="config_load_failed",
            message=f"Could not load agent config for health checks: {e}",
        )
        errors.append(error)
        return errors

    # Get enabled agents
    enabled_internal = {agent.name for agent in agents_config.agents if agent.enabled and agent.type == "internal"}
    enabled_external = [agent for agent in agents_config.agents if agent.enabled and agent.type == "external"]

    logger.info(
        f"Starting health checks for {len(enabled_internal)} internal and {len(enabled_external)} external agents"
    )

    # Check internal agents (A2A servers that should be running on localhost)
    for agent_name in enabled_internal:
        agent_errors = await _check_internal_agent_health(agent_name, config.A2A_CARDS_DIR)
        errors.extend(agent_errors)

    # Check external agents
    for agent_entry in enabled_external:
        agent_errors = await _check_external_agent_health(agent_entry.name, agent_entry.url)
        errors.extend(agent_errors)

    return errors


def log_agent_health_check_results(errors: list[A2AConfigValidationError]) -> None:
    """Log agent health check validation results.

    Groups errors by severity and logs them appropriately. This function
    is designed to make health check issues visible in application logs
    during startup without crashing the application.

    Args:
        errors: List of validation errors from validate_agent_health_checks()
    """
    if not errors:
        logger.info("✓ All enabled agents passed health checks")
        return

    # Group errors by severity
    errors_by_severity: dict[str, list[A2AConfigValidationError]] = {"ERROR": [], "WARNING": [], "INFO": []}

    for error in errors:
        errors_by_severity[error.severity].append(error)

    # Log summary
    error_count = len(errors_by_severity["ERROR"])
    warning_count = len(errors_by_severity["WARNING"])
    info_count = len(errors_by_severity["INFO"])

    logger.warning(
        f"Agent health check validation completed with issues: "
        f"{error_count} error(s), {warning_count} warning(s), {info_count} info",
        extra={"error_count": error_count, "warning_count": warning_count, "info_count": info_count},
    )

    # Log each error with appropriate severity
    for error in errors_by_severity["ERROR"]:
        logger.error(f"Agent health check: {error}", extra={"category": error.category, "severity": error.severity})

    for error in errors_by_severity["WARNING"]:
        logger.warning(f"Agent health check: {error}", extra={"category": error.category, "severity": error.severity})

    for error in errors_by_severity["INFO"]:
        logger.info(f"Agent health check: {error}", extra={"category": error.category, "severity": error.severity})

    # Add guidance for errors
    if errors_by_severity["ERROR"]:
        logger.error(
            "⚠️  Agent health check failures detected. "
            "Affected agents may not respond correctly to requests. "
            "Check agent logs and ensure all agents are running."
        )
