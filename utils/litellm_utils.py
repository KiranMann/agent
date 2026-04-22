"""Model configuration module for the application.

This module provides utilities for creating and configuring AI model instances
used throughout the application. It handles the initialization of LiteLLM models
with appropriate configuration settings from the application config and Langfuse
callback integration for observability.

The global `model` instance uses lazy initialization to ensure environment
variables are loaded before model creation. Access it via:
    - `from common.utils.litellm_utils import model` (lazy initialization)
    - `from common.utils.litellm_utils import get_model` (explicit lazy initialization)
    - `create_litellm_model()` (create a new instance on demand)
"""

import os

import httpcore
import httpx
import litellm

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.models.litellm_model import LitellmModel
from common.utils.runtime_utils import SSL_VERIFY


def configure_langfuse_for_litellm(callback_handler: str | None = "langfuse") -> bool:
    """Configure Langfuse integration for LiteLLM.

    Sets up the asynchronous HTTP client for LiteLLM with proper SSL verification
    settings and configures Langfuse as a success callback handler. This enables
    tracing and observability of all LLM interactions through the Langfuse platform.

    The function handles various potential exceptions that might occur during setup,
    logging appropriate error messages while allowing the application to continue
    without Langfuse integration if necessary.

    SSL verification is controlled by the utils.SSL_VERIFY setting, which may be
    disabled in development environments.

    Returns:
        bool: True if Langfuse was successfully configured, False if any errors occurred
              during configuration (allowing the application to continue without tracing)
    """
    try:
        # Defaulting to no callback handler as managing langfuse traces via agents SDK integration
        litellm.success_callback = [cb for cb in [callback_handler] if cb is not None]

        logger.info(
            f"{'No ' if not callback_handler else 'Langfuse'} callback successfully configured for LitellmModel"
        )
        return True

    except (httpx.HTTPError, httpcore.ConnectError) as e:
        # Handle network-related errors when setting up the HTTP client
        logger.error(f"Failed to initialize Langfuse callback due to connection error: {e!s}")
        return False

    except AttributeError as e:
        # Handle cases where LiteLLM properties cannot be set (possibly version mismatch)
        logger.error(f"Failed to initialize Langfuse callback due to attribute error: {e!s}")
        logger.debug("This might be due to an unsupported LiteLLM version")
        return False

    except ValueError as e:
        # Handle invalid values in configuration
        logger.error(f"Failed to initialize Langfuse callback due to invalid configuration: {e!s}")
        return False

    except Exception as e:
        # Catch-all for any unexpected errors to prevent application failure
        logger.error(f"Unexpected error configuring Langfuse callback: {e!s}")
        logger.debug(f"Exception type: {type(e).__name__}")
        return False


def create_litellm_model(
    model_name: str | None = None,
    llm_provider: str | None = None,
) -> LitellmModel:
    """Create and configure a LitellmModel instance with Langfuse callback.

    This function initializes a LitellmModel with configuration values from the Config
    object. It also sets up Langfuse integration for observability if enabled.

    Args:
        model_name: Optional model name to use. If not provided, falls back to Config.AGENT_LLM
        llm_provider: Optional LLM provider name. If not provided, falls back to Config.AGENT_LLM_PROVIDER

    Returns:
        LitellmModel: Configured model instance with Langfuse integration

    Raises:
        ValueError: If required configuration values (OPENAI_BASE_URL, OPENAI_API_KEY,
                   or AGENT_LLM) are missing
    """
    openai_base_url = AppConfig.OPENAI_BASE_URL
    openai_api_key = AppConfig.OPENAI_API_KEY
    model_name = model_name or AppConfig.AGENT_LLM
    provider = llm_provider or AppConfig.AGENT_LLM_PROVIDER.lower()

    if not openai_base_url or not openai_api_key or not model_name or not provider:
        raise ValueError("Please check and set OPENAI_BASE_URL, OPENAI_API_KEY, AGENT_LLM via env var or code.")
    # Create LitellmModel instance

    # Load so model_config can be used across different envs
    in_dev = os.environ.get("IN_DEV", "false").lower() == "true"
    litellm_model = LitellmModel(
        model=f"{provider}/{model_name}" if in_dev else model_name,
        base_url=openai_base_url,
        api_key=openai_api_key,
    )

    # Disable aiohttp transport to avoid conflicts with httpx
    litellm.disable_aiohttp_transport = True

    # Configure SSL and HTTPX client for async operations
    aclient = httpx.AsyncClient(verify=SSL_VERIFY)

    # Set the async client for LiteLLM
    litellm.aclient_session = aclient

    # Configure Langfuse integration if enabled
    if AppConfig.LANGFUSE_FLAG:
        configure_langfuse_for_litellm()
    return litellm_model


# Global model instance (lazily initialized)
# Using a list to avoid the need for 'global' statement (mutable container pattern)
_model_container: list[LitellmModel] = []


def get_model() -> LitellmModel:
    """Get the global LitellmModel instance, creating it if necessary.

    This function implements lazy initialization to ensure the model is only
    created when first accessed, allowing environment variables to be loaded
    before model creation.

    Returns:
        LitellmModel: The global model instance

    Raises:
        ValueError: If required configuration values are missing
    """
    if not _model_container:
        _model_container.append(create_litellm_model())
    return _model_container[0]


# For backwards compatibility, provide a model property that lazily initializes
# This allows existing code using `from common.utils.litellm_utils import model` to continue working
def __getattr__(name: str) -> LitellmModel:
    """Module-level attribute accessor for backwards compatibility.

    Args:
        name: The attribute name being accessed

    Returns:
        LitellmModel: The global model instance if name is 'model'

    Raises:
        AttributeError: If the attribute name is not recognized
    """
    if name == "model":
        return get_model()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
