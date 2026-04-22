"""Lambda-specific logging setup and configuration.

This module handles AWS Lambda environment initialization, including:
- SSL certificate configuration for secure HTTPS requests
- Splunk HEC token retrieval from AWS Secrets Manager
- Environment variable setup for logging and observability

This module must be imported and `setup_lambda_logging()` called before
importing `common.logging.core` to ensure proper environment configuration.

Example:
    >>> from common.logging.lambda_logging import setup_lambda_logging
    >>> setup_lambda_logging()
    >>> from common.logging.core import logger  # Import after setup
"""

import json
import logging
import os
from pathlib import Path

import boto3


def _get_secret(secret_name: str) -> str | None:
    """Get secret from AWS Secrets Manager (DHP environment).

    Args:
        secret_name: Name of the secret to retrieve

    Returns:
        Secret value if found, None otherwise
    """
    try:
        secret_arns = os.environ.get("SECRET_ARNS", "").split(",")
        for secret_arn in secret_arns:
            if not secret_arn.strip():
                continue

            client = boto3.client(
                "secretsmanager",
                region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
            )
            secret_value = client.get_secret_value(SecretId=secret_arn.strip())
            secrets = json.loads(secret_value["SecretString"])

            if secret_name in secrets:
                return str(secrets[secret_name])

    except Exception:
        return None
    return None


def setup_lambda_logging() -> None:
    """Configure AWS Lambda environment for logging and observability.

    This function performs the following initialization steps:
    1. Locates and configures SSL CA certificate bundle for HTTPS requests
    2. Sets required environment variables for requests/urllib3 SSL verification
    3. Retrieves Splunk HEC token from AWS Secrets Manager

    Environment Variables Set:
        REQUESTS_CA_BUNDLE: Path to CA certificate bundle for requests library
        SSL_CERT_FILE: Path to CA certificate bundle for SSL verification
        CURL_CA_BUNDLE: Path to CA certificate bundle for curl
        DHP_SPLUNK_HEC_TOKEN: Splunk HTTP Event Collector authentication token

    Notes:
        - Must be called before importing common.logging.core
        - Uses AWS Secrets Manager for secure token management
    """
    lambda_ca_bundle = Path(__file__).parent / "certs" / "ca-bundle.crt"
    if lambda_ca_bundle.exists():
        os.environ["REQUESTS_CA_BUNDLE"] = str(lambda_ca_bundle)
        os.environ["SSL_CERT_FILE"] = str(lambda_ca_bundle)
        os.environ["CURL_CA_BUNDLE"] = str(lambda_ca_bundle)
        logging.info(f"INFO: Using bundled CA certificate: {lambda_ca_bundle}")
    else:
        logging.warning("WARNING: CA bundle not found, using system certificates")

    splunk_token = _get_secret("SplunkHecToken")
    if splunk_token is not None:
        os.environ["DHP_SPLUNK_HEC_TOKEN"] = splunk_token
