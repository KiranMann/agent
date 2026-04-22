"""LaunchDarkly integration service for feature flag management.

This module provides a centralized service for interacting with LaunchDarkly
to manage feature toggles that were previously hardcoded in configuration files.
It supports graceful degradation when LaunchDarkly is unavailable and provides
consistent flag evaluation with proper error handling.
"""

import time
from functools import lru_cache
from typing import cast

from ldclient import Context, LDClient
from ldclient.config import Config as LDConfig
from ldclient.config import HTTPConfig

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger


class LaunchDarklyService:
    """Service for managing feature flags through LaunchDarkly.

    This service encapsulates LaunchDarkly client initialization, flag evaluation,
    and error handling. It provides graceful degradation when LaunchDarkly is
    unavailable by falling back to default values.
    """

    def __init__(
        self,
        sdk_key: str | None = None,
        offline: bool = False,
        disable_ssl_verification: bool = False,
    ):
        """Initialize LaunchDarkly service.

        Args:
            sdk_key: LaunchDarkly SDK key for authentication
            offline: If True, runs in offline mode using default values
            disable_ssl_verification: If True, disables SSL verification for LaunchDarkly connections
        """
        self._client: LDClient | None = None
        self._sdk_key = sdk_key
        self._disable_ssl_verification = disable_ssl_verification
        self._offline = offline
        self._initialized = False

        if self._sdk_key and not self._offline:
            try:
                self._initialize_client()
            except (ValueError, ConnectionError, RuntimeError) as e:
                logger.error(f"Failed to initialize LaunchDarkly client: {e}")
                self._offline = True

    def _initialize_client(self) -> None:
        """Initialize the LaunchDarkly client with configuration."""
        if self._disable_ssl_verification:
            logger.info("LaunchDarkly SSL verification is disabled")

        # Use system certificate bundle unless SSL verification is disabled
        ca_certs_path = None if self._disable_ssl_verification else "/etc/ssl/certs/ca-certificates.crt"

        # Configure proxy if running in DHP environment
        http_proxy = AppConfig.HTTP_PROXY_APP if AppConfig.SET_DHP_PROXY else None
        if http_proxy:
            logger.debug(f"LaunchDarkly using proxy: {http_proxy}")

        try:
            # Ensure sdk_key is not None (should be guaranteed by caller)
            if self._sdk_key is None:
                raise ValueError("SDK key is required for LaunchDarkly initialization")

            config = LDConfig(
                sdk_key=self._sdk_key,
                http=HTTPConfig(
                    disable_ssl_verification=self._disable_ssl_verification,
                    ca_certs=ca_certs_path,
                    http_proxy=http_proxy,
                ),
            )

            # Create and store the client instance
            self._client = LDClient(config=config)

            logger.info(f"LaunchDarkly client created: {self._client}")

            # Wait for initialization with timeout
            if not self._client.is_initialized():
                logger.warning("LaunchDarkly client not immediately initialized, waiting...")
                # Give it a moment to initialize
                time.sleep(1)

            if not self._client.is_initialized():
                logger.error("LaunchDarkly SDK failed to initialize")
                self._offline = True
                self._initialized = False
                return

            # Track initialization event
            logger.info("LaunchDarkly SDK successfully initialized")
            self._initialized = True

        except (ValueError, ConnectionError, RuntimeError, ImportError) as e:
            logger.error(f"Failed to initialize LaunchDarkly client: {e}")
            self._offline = True
            self._initialized = False
            self._client = None

    def get_flag(
        self,
        flag_key: str,
        default_value: bool = False,
        user_context: str | None = None,
    ) -> bool:
        """Evaluate a boolean feature flag.

        Args:
            flag_key: The feature flag key to evaluate
            default_value: Default value to return if flag evaluation fails
            user_context: Optional user context for targeting :: The customer_netbank_id to use for context

        Returns:
            bool: The flag value or default if evaluation fails
        """
        if self._offline or not self._initialized or not self._client:
            logger.debug(
                f"LaunchDarkly offline (offline={self._offline}, initialized={self._initialized}, client={self._client is not None}), returning default value for {flag_key}: {default_value}"
            )
            return default_value

        try:
            # Create proper LaunchDarkly context
            context = get_context(user_context)
            result = cast("bool", self._client.variation(flag_key, context, default_value))
            logger.debug(f"LaunchDarkly flag {flag_key}: {result} (context: {context.key})")
            return bool(result)

        except (AttributeError, ValueError, TypeError, ConnectionError) as e:
            logger.error(f"Error evaluating LaunchDarkly flag {flag_key}: {e}")
            return default_value

    def get_string_flag(
        self,
        flag_key: str,
        default_value: str | None = "",
        user_context: str | None = None,
    ) -> str | None:
        """Evaluate a string feature flag.

        Args:
            flag_key: The feature flag key to evaluate
            default_value: Default string value to return if flag evaluation fails
            user_context: Optional user context for targeting :: The customer_netbank_id to use for context

        Returns:
            str | None: The flag value or default if evaluation fails
        """
        if self._offline or not self._initialized or not self._client:
            logger.debug(
                f"LaunchDarkly offline (offline={self._offline}, initialized={self._initialized}, client={self._client is not None}), returning default value for {flag_key}: {default_value}"
            )
            return default_value

        try:
            # Create proper LaunchDarkly context
            context = get_context(user_context)
            result = self._client.variation(flag_key, context, default_value)
            logger.debug(f"LaunchDarkly string flag {flag_key}: {result} (context: {context.key})")
            return result if isinstance(result, str) else default_value

        except (AttributeError, ValueError, TypeError, ConnectionError) as e:
            logger.error(f"Error evaluating LaunchDarkly string flag {flag_key}: {e}")
            return default_value


@lru_cache
def get_launchdarkly_service() -> LaunchDarklyService:
    """Get or create the cached LaunchDarkly service instance.

    This function is cached to ensure we only create one service instance
    throughout the application lifecycle.

    Returns:
        LaunchDarklyService: The cached service instance
    """
    logger.debug("Getting LaunchDarkly service instance")

    sdk_key = AppConfig.LAUNCHDARKLY_SDK_KEY
    offline_mode = AppConfig.LAUNCHDARKLY_OFFLINE
    disable_ssl_verification = AppConfig.LAUNCHDARKLY_DISABLE_SSL_VERIFICATION

    logger.debug(f"LaunchDarkly offline mode: {offline_mode}")
    logger.debug(f"LaunchDarkly disable SSL verification: {disable_ssl_verification}")

    service = LaunchDarklyService(
        sdk_key=sdk_key,
        offline=offline_mode,
        disable_ssl_verification=disable_ssl_verification,
    )

    logger.info("LaunchDarkly service initialized")
    return service


def get_feature_flag(
    flag_key: str,
    default_value: bool = False,
    customer_netbank_id: str | None = None,
) -> bool:
    """Convenience function to get a feature flag value.

    Args:
        flag_key: The feature flag key to evaluate
        default_value: Default value to return if flag evaluation fails
        customer_netbank_id: Optional customer netbank ID for context targeting

    Returns:
        bool: The flag value or default if evaluation fails
    """
    service = get_launchdarkly_service()
    return service.get_flag(flag_key, default_value, customer_netbank_id)


def get_string_feature_flag(
    flag_key: str,
    default_value: str | None = "",
    customer_netbank_id: str | None = None,
) -> str | None:
    """Convenience function to get a string feature flag value.

    Args:
        flag_key: The feature flag key to evaluate
        default_value: Default string value to return if flag evaluation fails
        customer_netbank_id: Optional customer netbank ID for context targeting

    Returns:
        str | None: The flag value or default if evaluation fails
    """
    service = get_launchdarkly_service()
    return service.get_string_flag(flag_key, default_value, customer_netbank_id)


def get_context(customer_netbank_id: str | None = None) -> Context:
    """Get LaunchDarkly context for targeting based on agent type.

    Args:
        customer_netbank_id: The customer_netbank_id to use for context.
                           If None or empty, defaults to "system"

    Returns:
        Context: LaunchDarkly Context object for targeting
    """
    if not customer_netbank_id:  # This catches "", None, and other falsy values
        customer_netbank_id = "system"

    context_key = f"{customer_netbank_id}"

    # Create a proper LaunchDarkly Context with custom attributes
    context = Context.builder(context_key).set("kind", "user").build()

    return context
