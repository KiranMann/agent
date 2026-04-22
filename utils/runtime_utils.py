# pylint: disable=logging-too-many-args
"""Service-layer utilities for Financial Companion.

Provides infrastructure utilities for FastAPI service operations including
secret management, HTTP response handling, environment configuration,
and database connection access.
"""

import functools
import operator
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

import boto3
import simplejson as json
from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.stickiness_cookie_manager import cookie_manager

SERVICE_NAME = AppConfig.AGENT
JWT_SIGNING_ALGORITHM = os.getenv(
    "AGENT_AUTH_JWT_SIGNING_ALG", "HS256"
)  # Algorithm used for signing/verifying the token if none is specified in a given JWT's headers
ALLOWED_ISSUERS = list(os.getenv("AGENT_AUTH_ALLOWED_ISSUERS", "").split(" "))
REQUIRED_SCOPES = set(os.getenv("AGENT_AUTH_REQUIRED_SCOPES", "").split(" "))

GUARDRAIL_MSG = """Based on the customer's messages, it is possible that the customer may be experiencing a vulnerable circumstance.
Please review the conversation, and follow your training and the Extra Care Guide to support the customer through this
conversation.

After you have reviewed the conversation, please confirm if extra care was required (Thumbs up or down)"""
TIMEOUT_MSG = "I'm sorry, I am taking longer than expected to respond. Please try again."
GENERIC_ERROR_MSG = "There's a problem on our end. Please try again."


SSL_VERIFY = True
IN_DEV = os.environ.get("IN_DEV", "false").lower() == "true"
SKIP_SCOPE_CHECK = False


RESET = "__RESET__"

# HTTP status and retry constants
HTTP_NOT_FOUND = 404
MAX_RETRIES = 4
COOKIE_TIMEOUT_SECONDS = 10


def get_stickyness_cookie() -> dict[str, Any] | None:
    """Retrieve the stickiness cookie.

    Returns:
        Dictionary containing the stickiness cookie if available and fresh (less than 10 seconds old),
        otherwise None.
    """
    return cookie_manager.get_cookie()


def write_http_response(status: int, content: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    """Write an HTTP response.

    Args:
        status (int): HTTP status code.
        content (dict): Response content.
        headers (dict, optional): Response headers. Defaults to None.

    Returns:
        JSONResponse: FastAPI JSON response object.
    """
    if headers is None:
        headers = {}
    response = JSONResponse(
        status_code=status,
        content=content,
        headers=headers,
    )
    cookies = get_stickyness_cookie()
    if cookies:
        for c in cookies:
            response.set_cookie(key=c, value=cookies[c].value)
    return response


@functools.cache
def _get_secrets_manager_client() -> Any:
    """Get or create the AWS Secrets Manager client (singleton via cache).

    Returns:
        boto3 Secrets Manager client instance.
    """
    return boto3.session.Session().client(
        service_name="secretsmanager",
        region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2"),
    )


@functools.cache
def get_secret_string(
    secret_id: str,
) -> str:
    """Retrieve a secret string from AWS Secrets Manager.

    Args:
        secret_id (str): The ID of the secret to retrieve.

    Returns:
        str: The secret string retrieved from AWS Secrets Manager.
    """
    client = _get_secrets_manager_client()
    response = client.get_secret_value(SecretId=secret_id)
    return str(response["SecretString"])


def get_secret(key: str, default_value: str | None = None) -> str:
    """Retrieve a specific secret by key from AWS Secrets Manager.

    Args:
        key: The key of the secret to retrieve.
        default_value: Default value to return if key not found. Must be a string.

    Returns:
        str: The value of the secret associated with the given key.
    """
    try:
        secrets_dict: dict[str, str] = functools.reduce(
            operator.or_,
            (json.loads(get_secret_string(arn)) for arn in os.environ["SECRET_ARNS"].split(",")),
            {},
        )
        return secrets_dict[key]
    except KeyError as exc:
        logger.warning(f"Secret key not found: {key}")
        if default_value is not None:
            return default_value
        else:
            raise KeyError from exc


def get_time() -> str:
    """Get the current time in UTC formatted as an ISO 8601 string.

    Returns:
        str: The current time in UTC formatted as "%Y-%m-%dT%H:%M:%S.%fZ".
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_connection_pool(request: Request) -> AsyncConnectionPool | None:
    """Get the PostgreSQL connection pool from the FastAPI app state.

    Args:
        request (Request): The FastAPI request object.

    Returns:
        AsyncConnectionPool: The PostgreSQL connection pool.
    """
    return request.app.state.connection_pool


def log_agent_error_without_interrupt(error: str | Exception) -> None:
    """Log an error during agent operation, when the agent still needs to return a valid response to CM.

    Args:
        error (str | Exception): Error message to log
    """
    if isinstance(error, str):
        logger.error("\n======== Agent workflow error ========")
        logger.error("Traceback (most recent call last):")
        for line in traceback.format_stack():
            logger.error(line.rstrip("\n"))
        logger.error(f"Agent error: {error}")
        logger.warning("\nError sent downstream as response message.\n")
    else:
        logger.error("\n======== Agent workflow error ========")
        logger.error(traceback.format_exc())
        logger.warning("Error sent downstream as response message.\n")


def load_dev_environment_variables() -> None:
    """Load development environment variables for local dev/testing."""
    with open("private.key", encoding="utf-8") as file:
        content = file.read()
        AppConfig.GROUP_IDP_PRIVATE_KEY = content


def get_env_char() -> str:
    env_dict = {
        "dev": "d",
        "test2": "t2",
        "test3": "t3",
        "test5": "t5",
        "stg": "s",
        "prod": "p",
    }

    dhp_env = os.getenv("DHP_ENVIRONMENT", "").lower()
    env_char = env_dict.get(dhp_env, "")
    return env_char


def load_environment_variables() -> None:
    """Load environment variables from the Config class and AWS Secrets Manager."""
    # Load secrets from AWS Secrets Manager if SECRET_ARNS is set

    db_name = "financialcompanion_db"
    logger.info(f"Using DB name {db_name}")

    if "SECRET_ARNS" in os.environ:
        try:
            AppConfig.OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
            AppConfig.GROUP_IDP_PRIVATE_KEY = get_secret("AgenticAiPrivateKey")

            set_db_secrets(get_env_char())
            set_redis_secrets()
            set_api_service_secrets()
            set_idp_secrets()
            set_langfuse_secrets(AppConfig.LANGFUSE_FLAG)
            set_aws_resource_secrets()

        except Exception as err:
            logger.error(
                "unable to retrieve from secrets manager: {}",
                err,
            )
            sys.exit(-1)

    set_env_langfuse(AppConfig.LANGFUSE_FLAG)


def load_cron_environment_variables() -> None:
    """Load environment variables from the Config class and AWS Secrets Manager."""
    # Load secrets from AWS Secrets Manager if SECRET_ARNS is set

    if "SECRET_ARNS" in os.environ:
        try:
            AppConfig.OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
            AppConfig.GROUP_IDP_PRIVATE_KEY = get_secret("AgenticAiPrivateKey")
            # Temporary loading this to make it work, clean up after adding secrets mounting for lower envs
            # Temporary fix for overriding default DB credentials
            set_db_secrets(get_env_char())
            set_langfuse_secrets()
            set_env_langfuse()

        except Exception as err:
            logger.error(
                "unable to retrieve from secrets manager: %s",
                err,
            )
            sys.exit(-1)


def set_aws_resource_secrets() -> None:
    if AppConfig.RAG_KNOWLEDGE_BASE_FLAG:
        AppConfig.RAG_KNOWLEDGE_BASE_ID = get_secret("RAG_KNOWLEDGE_BASE_ID")
        AppConfig.RAG_KNOWLEDGE_BASE_MODEL = get_secret("RAG_KNOWLEDGE_BASE_MODEL")


def set_langfuse_secrets(langfuse_flag: bool = True) -> None:
    if langfuse_flag:
        AppConfig.LANGFUSE_PUBLIC_KEY = get_secret("LANGFUSE_PUBLIC_KEY")
        AppConfig.LANGFUSE_SECRET_KEY = get_secret("LANGFUSE_SECRET_KEY")
        AppConfig.LANGFUSE_HOST = get_secret("LANGFUSE_HOST")


def set_env_langfuse(langfuse_flag: bool = True) -> None:
    if langfuse_flag:
        if AppConfig.LANGFUSE_PUBLIC_KEY is not None:
            os.environ["LANGFUSE_PUBLIC_KEY"] = AppConfig.LANGFUSE_PUBLIC_KEY
        else:
            logger.error("LANGFUSE_PUBLIC_KEY is not set but LANGFUSE_FLAG is True")

        if AppConfig.LANGFUSE_SECRET_KEY is not None:
            os.environ["LANGFUSE_SECRET_KEY"] = AppConfig.LANGFUSE_SECRET_KEY
        else:
            logger.error("LANGFUSE_SECRET_KEY is not set but LANGFUSE_FLAG is True")

        if AppConfig.LANGFUSE_HOST is not None:
            os.environ["LANGFUSE_HOST"] = AppConfig.LANGFUSE_HOST
        else:
            logger.error("LANGFUSE_HOST is not set but LANGFUSE_FLAG is True")


def set_db_secrets(env_char: str) -> None:
    # Temporary loading this to make it work, clean up after adding secrets mounting for lower envs
    # Temporary fix for overriding default DB credentials
    db_secret_base_path = f"databases/{env_char}-s-agenticai-agent-aurora/financialcompanion_db/app"

    AppConfig.DB_PASSWORD = get_secret(
        f"{db_secret_base_path}:password",
        "",
    )
    AppConfig.DB_USER = get_secret(
        f"{db_secret_base_path}:username",
        "",
    )
    AppConfig.DB_HOST = get_secret(
        f"{db_secret_base_path}:host",
        "",
    )
    AppConfig.DB_PORT = get_secret(
        f"{db_secret_base_path}:port",
        "",
    )
    AppConfig.DB_NAME = get_secret(
        f"{db_secret_base_path}:dbname",
        "",
    )


def set_idp_secrets() -> None:
    AppConfig.GROUP_HYBRID_IDP_CERT = get_secret("GROUP_HYBRID_IDP_CERT", "")
    AppConfig.GROUP_HYBRID_IDP_CERT_PASSWORD = get_secret("GROUP_HYBRID_IDP_CERT_PASSWORD", "")
    AppConfig.GROUP_HYBRID_IDP_PRIVATE_KEY = get_secret("GROUP_HYBRID_IDP_PRIVATE_KEY", "")
    AppConfig.GROUP_IDP_CLIENT_ID = get_secret("GROUP_IDP_CLIENT_ID", "")


def set_api_service_secrets() -> None:
    # Savings Goals Credentials
    AppConfig.SAVINGSGOALS_SERVICE_USERNAME = get_secret("SAVINGSGOALS_SERVICE_USERNAME", "")
    AppConfig.SAVINGSGOALS_SERVICE_PASSWORD = get_secret("SAVINGSGOALS_SERVICE_PASSWORD", "")

    # Home Buying Service credentials
    AppConfig.HOME_BUYING_SERVICE_USERNAME = get_secret("HOME_BUYING_SERVICE_USERNAME", "")
    home_buying_service_password = get_secret("HOMELOAN_CALCULATOR_API_PASSWORD", "")
    if not home_buying_service_password:
        home_buying_service_password = get_secret("HOME_BUYING_SERVICE_PASSWORD", "")
    AppConfig.HOME_BUYING_SERVICE_PASSWORD = home_buying_service_password

    # Cashflow Service credentials - Basic Auth
    AppConfig.CASHFLOW_SERVICE_USERNAME = get_secret("CASHFLOW_SERVICE_USERNAME", "")
    AppConfig.CASHFLOW_SERVICE_PASSWORD = get_secret("CASHFLOW_SERVICE_PASSWORD", "")
    # Spendlimits Service credentials - Basic Auth
    AppConfig.SPENDLIMITS_SERVICE_USERNAME = get_secret("SPENDLIMITS_SERVICE_USERNAME", "")
    AppConfig.SPENDLIMITS_SERVICE_PASSWORD = get_secret("SPENDLIMITS_SERVICE_PASSWORD", "")
    # Accounts Service credentials - Basic Auth
    AppConfig.BILLHUB_SERVICE_USERNAME = get_secret("BILLHUB_SERVICE_USERNAME", "")
    AppConfig.BILLHUB_SERVICE_PASSWORD = get_secret("BILLHUB_SERVICE_PASSWORD", "")
    # BillHub credentials - Basic Auth
    AppConfig.ACCOUNTS_SERVICE_USERNAME = get_secret("ACCOUNTS_SERVICE_USERNAME", "")
    # InvestingHub credentials - Basic Auth
    AppConfig.INVESTING_HUB_AUTH_PASSWORD = get_secret("INVESTING_HUB_AUTH_PASSWORD", "")
    AppConfig.INVESTING_HUB_AUTH_USERNAME = get_secret("INVESTING_HUB_AUTH_USERNAME", "")
    # Enriched Transactions Service credentials - Basic Auth
    AppConfig.ENRICHED_TRAN_SERVICE_PASSWORD = get_secret("ENRICHED_TRAN_SERVICE_PASSWORD", "")
    # Shopping deals Service credentials - Basic Auth
    AppConfig.SHOPPING_DEALS_SERVICE_PASSWORD = get_secret("SHOPPING_DEALS_SERVICE_PASSWORD", "")

    AppConfig.DIALOGUE_MONITORING_SERVICE_TOKEN = get_secret("DIALOGUE_MONITORING_SERVICE_TOKEN", "")

    accounts_service_password = get_secret("ACCOUNTS_SERVICE_PASSWORD", "")
    if not accounts_service_password:
        accounts_service_password = get_secret("ACCOUNTS_PASSWORD", "")
    AppConfig.ACCOUNTS_SERVICE_PASSWORD = accounts_service_password

    AppConfig.COMMBANK_CLIENT_SERVICE_PASSWORD = get_secret("COMMBANK_CLIENT_SERVICE_PASSWORD", "")
    if not AppConfig.COMMBANK_CLIENT_SERVICE_PASSWORD:
        AppConfig.COMMBANK_CLIENT_SERVICE_PASSWORD = get_secret("fol1ClientsV3Password", "")

    AppConfig.COMMBANK_CLIENT_SERVICE_USERNAME = get_secret("COMMBANK_CLIENT_SERVICE_USERNAME", "")
    if not AppConfig.COMMBANK_CLIENT_SERVICE_USERNAME:
        AppConfig.COMMBANK_CLIENT_SERVICE_USERNAME = get_secret("channel_clients_staging", "")
    if not AppConfig.COMMBANK_CLIENT_SERVICE_USERNAME:
        AppConfig.COMMBANK_CLIENT_SERVICE_USERNAME = get_secret("channel_clients_production", "")

    # LaunchDarkly SDK Key
    AppConfig.LAUNCHDARKLY_SDK_KEY = get_secret("LAUNCH_DARKLY_KEY", "")

    # OTLP Metrics Auth Token
    otlp_metrics_auth_token = get_secret("bearertoken_ced", "")
    if otlp_metrics_auth_token:
        AppConfig.OTLP_METRICS_AUTH_TOKEN = otlp_metrics_auth_token


def set_redis_secrets() -> None:
    AppConfig.REDIS_CONFIGURATION_ENDPOINT = get_secret("configurationEndpoint")
    AppConfig.REDIS_AUTH_TOKEN = get_secret("authToken")


def is_production_environment() -> bool:
    """Check if running in production environment.

    Returns:
        bool: True if DHP_ENVIRONMENT is 'prod', False otherwise
    """
    environment = os.environ.get("DHP_ENVIRONMENT", "").lower()
    return environment == "prod"
