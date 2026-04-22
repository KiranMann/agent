"""Personalisation utilities for enabling and managing customer persona features.

This module provides utilities for checking personalisation feature flags and
retrieving customer personalisation data. It centralizes personalisation logic
that can be used across different agents in the system.
"""

from typing import Any

from common.configs.agent_config_settings import AgentConfig
from common.database.sqlalchemy_setup import get_db_session
from common.logging.core import logger
from common.models.feature_flags import FeatureFlags
from common.services.launchdarkly_service import get_feature_flag
from common.tools.customer_personas import CustomerPersonas


def should_enable_personalisation(customer_netbank_id: str | None = None) -> bool:
    """Check if personalisation should be enabled for this customer via LaunchDarkly.

    Args:
        customer_netbank_id: The customer's netbank ID for targeting

    Returns:
        bool: True if personalisation should be enabled, False otherwise
    """
    return get_feature_flag(
        FeatureFlags.ENABLE_PERSONALISATION,
        default_value=False,
        customer_netbank_id=customer_netbank_id,
    )


def is_personalisation_enabled(task: dict[str, Any]) -> bool:
    """Check if personalisation is enabled via both config and LaunchDarkly flags.

    Args:
        task: The task dictionary containing request parameters

    Returns:
        bool: True if both flags are enabled, False otherwise
    """
    config_enabled = AgentConfig.ENABLE_PERSONA_USAGE
    launchdarkly_enabled = should_enable_personalisation(task.get("netbank_id"))

    enabled = config_enabled and launchdarkly_enabled

    if not enabled:
        logger.debug(f"Personalisation disabled - config: {config_enabled}, LaunchDarkly: {launchdarkly_enabled}")

    return enabled


async def get_customer_personalisation(cif_code: str, task: dict[str, Any]) -> Any | None:
    """Retrieve customer personalisation if both config and LaunchDarkly flags are enabled.

    Args:
        cif_code: Customer identification code
        task: The task dictionary containing request parameters

    Returns:
        Customer personalisation data or None if disabled/unavailable
    """
    # Use common personalisation check logic
    if not is_personalisation_enabled(task):
        return None

    # Use SQLAlchemy session for persona retrieval
    try:
        async with get_db_session() as db_session:
            persona_handler = CustomerPersonas(db_session)
            customer_details = {
                "cif_code": task.get("cif_code"),
                "netbank_id": task.get("netbank_id"),
                "client_ip_address": task.get("client_ip_address", "127.0.0.1"),
            }
            return await persona_handler.retrieve_customer_personalisation(cif_code, customer_details)
    except Exception as e:
        logger.warning(f"Failed to retrieve customer personalisation: {e}")
        return None
