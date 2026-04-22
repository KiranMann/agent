"""Configuration settings module for the application.

This module provides a centralized configuration management system using Pydantic's
BaseSettings to handle environment variables and configuration values. It supports
multiple deployment environments (prod, staging, test, dev) with environment-specific
configuration files.

Key Features:
- Environment-specific configuration loading (.env.prod, .env.stg, .env.t2, .env.t3, .env.nonprod, .env.local)
- Pydantic-based settings validation and type checking
- Support for agent-specific configuration overrides
- Comprehensive API service endpoint configuration (10+ services)
- Authentication and identity provider settings (Group IDP, JWKS)
- Database connection configuration (PostgreSQL)
- Langfuse observability and tracing settings
- Guardrails service configuration with quality options
- Mock API support for testing environments
- SSL/TLS certificate configuration for ALB
- Gradio UI configuration with CIF lists
- HTTP timeout and connection settings

The module automatically loads the appropriate environment file based on the
DHP_ENVIRONMENT variable and provides a cached configuration instance through
the get_config() function. Agent-specific configurations can extend the base
ConfigSettings class to provide specialized settings for different agent types.

Environment Priority:
1. .env.local (highest priority, for local overrides)
2. Environment-specific files (.env.prod, .env.stg, etc.)
3. Default values defined in the class
"""

import os
from functools import lru_cache
from typing import Literal

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.constants import ENVS_DIR

MIN_FACT_EXTRACTION_CONCURRENCY = 1
MAX_FACT_EXTRACTION_CONCURRENCY = 20

HOME_BUYING_TEST_BASE_URL = "https://test01.home-buying.test.aws.groupapi.cba"
CLIENT_ID_FIELD_DESCRIPTION = "Client ID for the Group Identity Provider"


def _env_to_filename(env: str) -> str:
    """Map DHP_ENVIRONMENT -> dotenv filename. Keep mappings in one place to avoid drift."""
    match env:
        case "prod":
            return ".env.prod"
        case "stg" | "staging":
            return ".env.stg"
        case "test2" | "t2":
            return ".env.t2"
        case "test3" | "t3":
            return ".env.t3"
        case "dev" | "test5" | "nonprod":
            return ".env.nonprod"
        case _:
            # Safe default for local dev if DHP_ENVIRONMENT is unset/unknown
            return ".env.nonprod"


def _normalize_env(raw: str) -> str:
    return (raw or "").strip().lower()


def _settings_env_files() -> tuple[str, ...]:
    """Order matters. Earlier = lower priority, later = higher priority.

    We want:
      - base/shared defaults first
      - env-specific next (overrides shared)
      - .env.local last (local overrides)
    """
    env = _normalize_env(os.environ.get("DHP_ENVIRONMENT", ""))
    env_file = _env_to_filename(env)

    app_name = os.environ.get("APP_NAME", "").strip().lower()

    shared_file = ENVS_DIR / "shared" / ".env.shared"
    env_specific_file = ENVS_DIR / "shared" / env_file
    app_specific_file = ENVS_DIR / app_name / env_file
    local_file = ENVS_DIR / "shared" / ".env.local"

    if app_name:
        logger.info(f"APP_NAME is set to '{app_name}'. Looking for app specific configuration in {app_specific_file}")
    else:
        logger.warning("APP_NAME is not set. App specific configuration will be skipped.")

    env_files = (shared_file, env_specific_file, app_specific_file, local_file)
    for idx, f in enumerate(reversed(env_files), start=1):
        if f.exists():
            logger.info(f"{idx}. {f} found, environment variables will be loaded from this file.")
        else:
            logger.info(f"{idx}. {f} not found, skipping this file.")

    # Only include files that exist to avoid surprises if some are not shipped/mounted.
    return tuple(str(p) for p in env_files if p.exists())


class AppConfigSettings(BaseSettings):
    """Application configuration settings loaded from environment variables.

    This class defines all configuration parameters for the application, organized
    into logical groups for different services and functionality areas.

    Env var precedence (highest -> lowest) when instantiating AppConfigSettings:
        1) Real process environment variables (os.environ) override everything
        2) .env.local (local/dev overrides)
        3) ENVS_DIR/<app_name>/.env.<mapped from DHP_ENVIRONMENT> (app-specific overrides)
        3) ENVS_DIR/shared/.env.<mapped from DHP_ENVIRONMENT> (env-specific overrides)
        4) ENVS_DIR/shared/.env.shared (base/shared defaults)
    Note: only files that exist are included in env_file, so missing files are skipped.

    Configuration Groups:
        OpenAI Integration:
            OPENAI_BASE_URL, OPENAI_API_KEY : OpenAI API configuration
            AGENT, AGENT_LLM : AI agent and model selection

        Database Configuration:
            DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME : PostgreSQL connection settings

        Authentication & Identity:
            GROUP_IDP_* : Group Identity Provider settings for OAuth2/JWT authentication
            JWKS_URL : JSON Web Key Set URL for token verification
            ACCOUNTS_SERVICE_* : Basic auth username and password for Api.Accounts

        API Service Endpoints:
            LOCATION_DATA_SERVICE_BASE_URL : Location and address data
            GUARDRAILS_SERVICE_BASE_URL : AI guardrails and safety service
            PRODUCTS_SERVICE_BASE_URL : Product catalog service
            ACCOUNT_SERVICES_BASE_URL : To hit Api.Accounts endpoint

        Observability & Monitoring:
            LANGFUSE_* : Langfuse tracing and observability settings
            LOGLEVEL : Application logging level

        Testing & Development:
            MOCK_API_* : Mock API server configuration
            USING_MOCK_API : Flag for mock API usage
            ENABLE_MEMORY_PII_GUARDRAIL : Enable/disable PII guardrail for memory
            DHP_NON_PROD : Non-production environment flag

        Gradio UI:
            GRADIO_* : Gradio interface configuration
            CIF_LIST, CIF_LIST_USING_MOCK_API : Customer identification lists

        Security & Infrastructure:
            SSL_ALB_* : SSL certificate paths for Application Load Balancer
            HTTP_TIMEOUT : Default HTTP request timeout
            QUALITY_GUARDRAIL : Quality guardrail type selection

    The configuration automatically loads environment-specific settings based on
    the DHP_ENVIRONMENT variable and supports local overrides via .env.local.
    """

    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_ignore_empty=True,
        extra="allow",
        validate_default=True,
        case_sensitive=True,
    )

    OPENAI_BASE_URL: str = Field(
        default="",
        validation_alias="OPENAI_BASE_URL",
        description="Base URL for the OpenAI API",
    )

    OPENAI_API_KEY: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY",
        description="API key for authenticating with the OpenAI API",
    )

    HTTP_PROXY_APP: str = Field(
        default="http://app-proxy:3128",
        validation_alias="HTTP_PROXY_APP",
        description="Proxy server URL for HTTP requests",
    )

    SET_DHP_PROXY: bool = Field(
        default=False,
        validation_alias="SET_DHP_PROXY",
        description="Determines whether we're running on DHP for proxy purposes",
    )

    MOCK_API_FLAG: bool = Field(
        default=False,
        validation_alias="MOCK_API_FLAG",
        description="Used to switch to mock APIs instead of using real endpoints",
    )

    # Langraph Agent -> set this to bedrock-claude-3-sonnet
    # Card Reissue Agent -> set this to gpt-4.0_v2024-11-20 in DHP environments
    # Card Reissue Agent -> set this to gpt-4.1_v2025-04-14_GLOBAL in local testing

    AGENT: str = Field(
        default="SampleLanggraphBasicAgent",
        validation_alias="AGENT",
        description="Agent to be used in the application.",
    )

    AGENT_LLM: str = Field(
        default="gpt-4.1_v2025-04-14_EASTUS2",
        validation_alias="AGENT_LLM",
        description="Name of the AI model to be used by the agent",
    )

    AGENT_LLM_PROVIDER: str = Field(
        default="openai",
        validation_alias="AGENT_LLM_PROVIDER",
        description="Name of the AI model provider to be used by the agent",
    )

    ### Database setup
    DB_USER: str | None = Field(
        validation_alias="DB_USER",
        default="",
        description="Database user for connecting to the PostgreSQL database",
    )
    DB_PASSWORD: str | None = Field(
        validation_alias="DB_PASSWORD",
        default="",
        description="Password for connecting to the PostgreSQL database",
    )

    DB_HOST: str | None = Field(
        validation_alias="DB_HOST",
        default="",
        description="Host address for the PostgreSQL database",
    )

    DB_PORT: str | None = Field(
        validation_alias="DB_PORT",
        default="",
        description="Port number for the PostgreSQL database",
    )

    DB_NAME: str | None = Field(
        validation_alias="DB_NAME",
        default="",
        description="Name of the PostgreSQL database",
    )

    ENABLE_MEMORY_PII_GUARDRAIL: bool = Field(
        default=False,
        description="Enable or disable the pii check performed prior to saving to memory guardrail.",
        validation_alias="ENABLE_MEMORY_PII_GUARDRAIL",
    )

    ENABLE_MULTI_STEP_RELEVANCY_OUTPUT_CHECK: bool = Field(
        default=False,
        description="Enable or disable the multi-step relevancy guardrail for response evaluation.",
        validation_alias="ENABLE_MULTI_STEP_RELEVANCY_OUTPUT_CHECK",
    )

    INCLUDE_SOURCES: bool = Field(
        default=False,
        description="Enable or disable including sources in agent responses.",
        validation_alias="INCLUDE_SOURCES",
    )

    LOGLEVEL: str = Field(
        default="INFO",
        validation_alias="LOGLEVEL",
        description="Logging level for the application",
    )
    MOCK_API_SERVER_HOST: str = "http://localhost"
    MOCK_API_SERVER_PORT: int = 8080
    # Authentication and identity provider settings
    GROUP_IDP_CLIENT_ID: str = Field(
        default="session-dialogue-money-management.int.npd.financialcompanion",
        validation_alias="GROUP_IDP_CLIENT_ID",
        description=CLIENT_ID_FIELD_DESCRIPTION,
    )
    GROUP_IDP_URL: str = Field(
        default="https://test01.idp.test.aws.groupapi.cba",
        validation_alias="GROUP_IDP_URL",
        description="URL for the Group Identity Provider",
    )
    GROUP_IDP_SCOPE: str = Field(
        default="",
        description="Scope for the Group Identity Provider",
    )
    GROUP_IDP_PRIVATE_KEY: str = Field(
        default="",
        validation_alias="GROUP_IDP_PRIVATE_KEY",
        description="Private key for the Group Identity Provider",
    )
    JWKS_URL: str = Field(
        default="https://test01.idp.test.aws.groupapi.cba/tls/pf/JWKS",
        validation_alias="JWKS_URL",
        description="URL for the JSON Web Key Set (JWKS) used for token verification",
    )
    GROUP_HYBRID_IDP_URL: str = Field(
        default="",
        validation_alias="GROUP_HYBRID_IDP_URL",
        description=CLIENT_ID_FIELD_DESCRIPTION,
    )
    GROUP_HYBRID_IDP_CERT: str = Field(
        default="",
        validation_alias="GROUP_HYBRID_IDP_CERT",
        description="Certificate for the Group Hybrid Identity Provider",
    )
    GROUP_HYBRID_IDP_PRIVATE_KEY: str = Field(
        default="",
        validation_alias="GROUP_HYBRID_IDP_PRIVATE_KEY",
        description="Private key for the Group Hybrid Identity Provider",
    )
    GROUP_HYBRID_IDP_CERT_PASSWORD: str = Field(
        default="",
        validation_alias="GROUP_HYBRID_IDP_CERT_PASSWORD",
        description=CLIENT_ID_FIELD_DESCRIPTION,
    )

    CONSUMER_IDP_CLIENT: str = Field(
        default="session-dialogue-money-management.int.npd.financialcompanion-experience",
        validation_alias="CONSUMER_IDP_CLIENT",
        description="Client ID for the API Consumer",
    )

    CONVERSATION_MANAGER_SERVICE_BASE_URL: str = Field(
        default="https://dev01.conversation-mngr.test.aws.groupapi.cba",
        validation_alias="CONVERSATION_MANAGER_SERVICE_BASE_URL",
        description="Base URL for the Conversation Manager Service",
    )

    DIALOGUE_MONITORING_SERVICE_BASE_URL: str = Field(
        default="https://t2-s-genai-dmapi-alb.dotdtdp03test201.aws.test.au.internal.cba",
        validation_alias="DIALOGUE_MONITORING_SERVICE_BASE_URL",
        description="Base URL for the Dialogue Monitoring Service",
    )

    DIALOGUE_MONITORING_SERVICE_TOKEN: str = Field(
        default="",
        validation_alias="DIALOGUE_MONITORING_SERVICE_TOKEN",
        description="Token for the Dialogue Monitoring Service",
    )

    LOCATION_DATA_SERVICE_BASE_URL: str = Field(
        default="https://test02.partydataservices.test.aws.groupapi.cba/party-reference/location-data-management",
        validation_alias="LOCATION_DATA_SERVICE_BASE_URL",
        description="Base URL for the Location Data Service",
    )
    GUARDRAILS_SERVICE_BASE_URL: str = Field(
        default="https://guardrail.dp3.dev.ai.dhp.cba",
        validation_alias="GUARDRAILS_SERVICE_BASE_URL",
        description="Base URL for the Guardrails Service",
    )
    GUARDRAILS_V3_SERVICE_BASE_URL: str = Field(
        default="https://d-s-genai-gaas-alb.dotdtdp03dev01.aws.test.au.internal.cba",
        validation_alias="GUARDRAILS_V3_SERVICE_BASE_URL",
        description="Base URL for the Guardrails v3 Service",
    )
    GUARDRAILS_SERVICE_BUSINESS_UNIT: str = Field(
        default="DigitalPlatform3",
        validation_alias="GUARDRAILS_SERVICE_BUSINESS_UNIT",
        description="Business unit identifier for the Guardrails Service",
    )
    HOME_BUYING_SERVICE_BASE_URL: str = Field(
        default="https://commbank-api-homeloancalculators.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="HOME_BUYING_SERVICE_BASE_URL",
        description="Base URL for the Home Buying Service (Home Loan Calculators API)",
    )
    HOME_BUYING_SERVICE_USERNAME: str = Field(
        default="username",
        validation_alias="HOME_BUYING_SERVICE_USERNAME",
        description="Username for Home Buying Service basic authentication",
    )
    HOME_BUYING_SERVICE_PASSWORD: str = Field(
        default="password",
        validation_alias="HOME_BUYING_SERVICE_PASSWORD",
        description="Password for Home Buying Service basic authentication",
    )

    # These settings are required for backwards compatibility with the current production
    # Home Loan Calculators API, which uses a separate endpoint and credentials. Ensure we
    # can call the production calculators directly without affecting the existing service.
    HOME_LOAN_CALCULATORS_PROD_URL: str = Field(
        default="https://commbank-api-homeloancalculators.app-syd.prod.dp-retail.azure.prod.au.internal.cba",
        validation_alias="HOME_LOAN_CALCULATORS_PROD_URL",
        description="Base URL for another Home Loan Calculators Service",
    )

    HOME_BUYING_SERVICE_DEFAULT_CLIENT_ID: str = Field(
        default="",
        validation_alias="HOME_BUYING_SERVICE_DEFAULT_CLIENT_ID",
        description="Default client ID for Home Buying Service API calls",
    )
    HOME_BUYING_SERVICE_DEFAULT_PRODUCT: str = Field(
        default="Digi Home Loan",
        validation_alias="HOME_BUYING_SERVICE_DEFAULT_PRODUCT",
        description="Default home loan product name used for initial interest rate calculations",
    )
    # Property Insight Service Configuration
    PROPERTY_INSIGHT_SERVICE_BASE_URL: str = Field(
        default=HOME_BUYING_TEST_BASE_URL,
        validation_alias="PROPERTY_INSIGHT_SERVICE_BASE_URL",
        description="Base URL for the Property Insight Service (Home Hub API)",
    )
    PROPERTY_INSIGHT_SERVICE_CLIENT_ID: str = Field(
        default="session-dialogue-money-management.int.npd.financialcompanion",
        validation_alias="PROPERTY_INSIGHT_SERVICE_CLIENT_ID",
        description="Client ID for Property Insight Service OAuth2 authentication",
    )

    # CommBank Client Service Configuration
    COMMBANK_CLIENT_SERVICE_BASE_URL: str = Field(
        default="https://services2.test2.finest.online.cba:28022",
        validation_alias="COMMBANK_CLIENT_SERVICE_BASE_URL",
        description="Base URL for the CommBank Client Service",
    )
    COMMBANK_CLIENT_SERVICE_USERNAME: str = Field(
        default="",
        validation_alias="COMMBANK_CLIENT_SERVICE_USERNAME",
        description="Username for authenticating with the CommBank Client Service",
    )
    COMMBANK_CLIENT_SERVICE_PASSWORD: str = Field(
        default="",
        validation_alias="COMMBANK_CLIENT_SERVICE_PASSWORD",
        description="Password for authenticating with the CommBank Client Service",
    )

    # Location Data Management API Configuration
    INSIGHT_LOCATION_DATA_SERVICE_BASE_URL: str = Field(
        default="https://test01.partydataservices.test.aws.groupapi.cba",
        validation_alias="INSIGHT_LOCATION_DATA_SERVICE_BASE_URL",
        description="Base URL for the Location Data Management Service",
    )
    RATES_AND_FEES_BASE_URL: str = Field(
        default=HOME_BUYING_TEST_BASE_URL,
        validation_alias="RATES_AND_FEES_BASE_URL",
        description="Base URL for the Rates and Fees Service",
    )
    LOCATION_DATA_SERVICE_CONSUMER_ID: str = Field(
        default="PropertyReport",
        validation_alias="LOCATION_DATA_SERVICE_CONSUMER_ID",
        description="Consumer ID for Location Data Management Service requests",
    )
    LOCATION_DATA_SERVICE_DEPARTMENT_CODE: str = Field(
        default="cbapp-homehubacquisitions-01",
        validation_alias="LOCATION_DATA_SERVICE_DEPARTMENT_CODE",
        description="Department code for Location Data Management Service requests",
    )

    # Property Data Service (PDaaS) Configuration
    PROPERTY_DATA_SERVICE_BASE_URL: str = Field(
        default=HOME_BUYING_TEST_BASE_URL,
        validation_alias="PROPERTY_DATA_SERVICE_BASE_URL",
        description="Base URL for the Property Data Service (PDaaS)",
    )
    PROPERTY_DATA_SERVICE_CONSUMER_ID: str = Field(
        default="PropertyReport",
        validation_alias="PROPERTY_DATA_SERVICE_CONSUMER_ID",
        description="Consumer ID for Property Data Service requests",
    )

    # Property Valuation Service Configuration
    PROPERTY_VALUATION_SERVICE_BASE_URL: str = Field(
        default=HOME_BUYING_TEST_BASE_URL,
        validation_alias="PROPERTY_VALUATION_SERVICE_BASE_URL",
        description="Base URL for the Property Valuation Service",
    )
    PROPERTY_VALUATION_SERVICE_CONSUMER_ID: str = Field(
        default="PropertyReport",
        validation_alias="PROPERTY_VALUATION_SERVICE_CONSUMER_ID",
        description="Consumer ID for Property Valuation Service requests",
    )
    PREFERRED_VALUATION_COMPANY: str = Field(
        default="CME",
        validation_alias="PREFERRED_VALUATION_COMPANY",
        description="Preferred valuation company for property valuations",
    )
    PRODUCTS_SERVICE_BASE_URL: str = Field(
        default="https://api.commbank.com.au/public/cds-au/v1/banking",
        validation_alias="PRODUCTS_SERVICE_BASE_URL",
        description="Base URL for the Products Service",
    )
    SENSE_SERVICE_BASE_URL: str = Field(
        default="https://dev01.sense.test.aws.groupapi.cba",
        validation_alias="SENSE_SERVICE_BASE_URL",
        description="Base URL for the Sense Transactions API",
    )
    SENSE_SERVICE_SCOPE: str = Field(
        default="sense-transactions-read",
        validation_alias="SENSE_SERVICE_SCOPE",
        description="Default scope for the Sense Transactions API",
    )
    CASHFLOW_SERVICE_BASE_URL: str = Field(
        default="https://internalapi-mel-innovate.test.dp-retail.azure.test.au.internal.cba/api.cashflow",
        validation_alias="CASHFLOW_SERVICE_BASE_URL",
        description="Base URL for the Cashflow Service",
    )
    CASHFLOW_SERVICE_USERNAME: str = Field(
        default="cashflowdefault",
        validation_alias="CASHFLOW_SERVICE_USERNAME",
        description="Username for authenticating with the Cashflow Service",
    )
    CASHFLOW_SERVICE_PASSWORD: str = Field(
        default="cashflowdefault",
        validation_alias="CASHFLOW_SERVICE_PASSWORD",
        description="Password for authenticating with the Cashflow Service",
    )
    ENRICHED_TRAN_SERVICE_BASE_URL: str = Field(
        default="https://api-enrichedtransactions-v1.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="ENRICHED_TRAN_SERVICE_BASE_URL",
        description="Base URL for the Enriched Transactions Service",
    )
    ENRICHED_TRAN_SERVICE_USERNAME: str = Field(
        default="EnrichedTraTest",
        validation_alias="ENRICHED_TRAN_SERVICE_USERNAME",
        description="Username for authenticating with the Enriched Transactions Service",
    )
    ENRICHED_TRAN_SERVICE_PASSWORD: str = Field(
        default="EnrichedTraTest",
        validation_alias="ENRICHED_TRAN_SERVICE_PASSWORD",
        description="Password for authenticating with the Enriched Transactions Service",
    )
    CONSUMER_LOANS_SERVICE_BASE_URL: str = Field(
        default="https://test01.consumer-finance.test.aws.groupapi.cba/consumer-loan/enquiry/v1",
        validation_alias="CONSUMER_LOANS_SERVICE_BASE_URL",
        description="Base URL for the Consumer Loans Enquiry Service",
    )
    CONSUMER_LOANS_SERVICE_SCOPE: str = Field(
        default="consumer-loan.accounts.read",
        validation_alias="CONSUMER_LOANS_SERVICE_SCOPE",
        description="OAuth2 scope for Consumer Loans Service authentication",
    )
    MORTGAGE_LOAN_SERVICE_BASE_URL: str = Field(
        default="https://test01.home-buying.test.aws.groupapi.cba/loans-and-deposits/mortgage-loans/v1/",
        validation_alias="MORTGAGE_LOAN_SERVICE_BASE_URL",
        description="Base URL for Mortgage Loan service",
    )
    MORTGAGE_LOAN_SERVICE_SCOPE: str = Field(
        default="mortgage-loan.account.read",
        validation_alias="MORTGAGE_LOAN_SERVICE_SCOPE",
        description="OAuth2 scope for Mortgage Loan Service authentication",
    )
    SPENDLIMITS_SERVICE_BASE_URL: str = Field(
        default="https://api-spendlimits.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="SPENDLIMITS_SERVICE_BASE_URL",
        description="Base URL for the Spend Limits Service",
    )
    SPENDLIMITS_SERVICE_USERNAME: str = Field(
        default="spendlimitsdefault",
        validation_alias="SPENDLIMITS_SERVICE_USERNAME",
        description="Username for authenticating with the Spend Limits Service",
    )
    SPENDLIMITS_SERVICE_PASSWORD: str = Field(
        default="spendlimitsdefault",
        validation_alias="SPENDLIMITS_SERVICE_PASSWORD",
        description="Password for authenticating with the Spend Limits Service",
    )
    BILLHUB_SERVICE_BASE_URL: str = Field(
        default="https://api-billhub-v1.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="BILLHUB_SERVICE_BASE_URL",
        description="Base URL for the BillHub Service",
    )
    BILLHUB_SERVICE_USERNAME: str = Field(
        default="billhubdefault",
        validation_alias="BILLHUB_SERVICE_USERNAME",
        description="Username for authenticating with the BillHub Service",
    )
    BILLHUB_SERVICE_PASSWORD: str = Field(
        default="billhubdefault",
        validation_alias="BILLHUB_SERVICE_PASSWORD",
        description="Password for authenticating with the BillHub Service",
    )
    SAVINGSGOALS_SERVICE_BASE_URL: str = Field(
        default="https://internalapi-innovate.test.dp-retail.azure.test.au.internal.cba/Commbank.Api.SavingsGoals",
        validation_alias="SAVINGSGOALS_SERVICE_BASE_URL",
        description="Base URL for the SavingsGoals Service",
    )
    SAVINGSGOALS_SERVICE_USERNAME: str = Field(
        default="savingsgoalsdefault",
        validation_alias="SAVINGSGOALS_SERVICE_USERNAME",
        description="Username for authenticating with the SavingsGoals Service",
    )
    SAVINGSGOALS_SERVICE_PASSWORD: str = Field(
        default="savingsgoalsdefault",
        validation_alias="SAVINGSGOALS_SERVICE_PASSWORD",
        description="Password for authenticating with the SavingsGoals Service",
    )

    ACCOUNT_SERVICES_BASE_URL: str = Field(
        default="https://internalapi.test.dp-retail.azure.test.au.internal.cba/api.accounts.v1",
        validation_alias="ACCOUNT_SERVICES_BASE_URL",
        description="Base URL for the accounts service",
    )

    ACCOUNTS_SERVICE_USERNAME: str = Field(
        default="defaultUsername",
        validation_alias="ACCOUNTS_SERVICE_USERNAME",
        description="Username for Basic Auth authentication with the Api.Accounts service",
    )

    ACCOUNTS_SERVICE_PASSWORD: str = Field(
        default="defaultPassword",
        validation_alias="ACCOUNTS_SERVICE_PASSWORD",
        description="Password for Basic Auth authentication with the Api.Accounts service",
    )

    SHOPPING_DEALS_SERVICE_BASE_URL: str = Field(
        default="https://commbank-api-shoppingdeals.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="SHOPPING_DEALS_SERVICE_BASE_URL",
        description="Base URL for Shopping Deals service",
    )

    SHOPPING_DEALS_SERVICE_USERNAME: str = Field(
        default="defaultUsername",
        validation_alias="SHOPPING_DEALS_SERVICE_USERNAME",
        description="Username for Basic Auth authentication with the Shopping Deals service",
    )

    SHOPPING_DEALS_SERVICE_PASSWORD: str = Field(
        default="defaultPassword",
        validation_alias="SHOPPING_DEALS_SERVICE_PASSWORD",
        description="Password for Basic Auth authentication with the Shopping Deals service",
    )

    # Elastic Search Service Configuration
    ELASTIC_SEARCH_SERVICE_BASE_URL: str = Field(
        default="https://dev01.custeng.test.aws.groupapi.cba/elastic-search/v1",
        validation_alias="ELASTIC_SEARCH_SERVICE_BASE_URL",
        description="Base URL for the Elastic Search API",
    )
    ELASTIC_SEARCH_SERVICE_SCOPE: str = Field(
        default="elastic-search.read",
        validation_alias="ELASTIC_SEARCH_SERVICE_SCOPE",
        description="OAuth2 scope for Elastic Search Service authentication",
    )

    # LLM Reranker Service Configuration
    ENABLE_RAG_RERANKING: bool = Field(
        default=True,
        validation_alias="ENABLE_RAG_RERANKING",
        description="Enable LLM-based reranking for RAG document retrieval",
    )
    RERANKER_MODEL: str = Field(
        default="bedrock-claude-3-5-sonnet-v2",
        validation_alias="RERANKER_MODEL",
        description="LLM model to use for document reranking",
    )
    RERANKER_TOP_N: int = Field(
        default=20,
        validation_alias="RERANKER_TOP_N",
        description="Maximum number of documents to return after reranking",
    )

    # Payments Service Configuration
    PAYMENTS_SERVICE_BASE_URL: str = Field(
        default="https://internalapi.test.dp-retail.azure.test.au.internal.cba/api.payments.v1",
        validation_alias="PAYMENTS_SERVICE_BASE_URL",
        description="Base URL for the Payments Backend API",
    )
    PAYMENTS_SERVICE_USERNAME: str = Field(
        default="",
        validation_alias="PAYMENTS_SERVICE_USERNAME",
        description="Username for authenticating with the Payments Service",
    )
    PAYMENTS_SERVICE_PASSWORD: str = Field(
        default="",
        validation_alias="PAYMENTS_SERVICE_PASSWORD",
        description="Password for authenticating with the Payments Service",
    )

    # Digital Payment Limits Service Configuration
    DIGITAL_PAYMENT_LIMITS_SERVICE_BASE_URL: str = Field(
        default="https://commbank-api-digitalpaymentlimits-v0.app-mel.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="DIGITAL_PAYMENT_LIMITS_SERVICE_BASE_URL",
        description="Base URL for the Digital Payment Limits Service",
    )
    DIGITAL_PAYMENT_LIMITS_SERVICE_USERNAME: str = Field(
        default="",
        validation_alias="DIGITAL_PAYMENT_LIMITS_SERVICE_USERNAME",
        description="Username for authenticating with the Digital Payment Limits Service",
    )
    DIGITAL_PAYMENT_LIMITS_SERVICE_PASSWORD: str = Field(
        default="",
        validation_alias="DIGITAL_PAYMENT_LIMITS_SERVICE_PASSWORD",
        description="Password for authenticating with the Digital Payment Limits Service",
    )
    DIGITAL_PAYMENT_LIMITS_SERVICE_API_KEY: str = Field(
        default="",
        validation_alias="DIGITAL_PAYMENT_LIMITS_SERVICE_API_KEY",
        description="API key for authenticating with the Digital Payment Limits Service",
    )

    # Customer Profile Service Configuration
    CUSTOMER_PROFILE_SERVICE_BASE_URL: str = Field(
        default="https://test02.digital.test.aws.groupapi.cba",
        validation_alias="CUSTOMER_PROFILE_SERVICE_BASE_URL",
        description="Base URL for the Customer Profile Service",
    )
    ENABLE_CUSTOMER_PROFILE_FALLBACK: bool = Field(
        default=True,
        validation_alias="ENABLE_CUSTOMER_PROFILE_FALLBACK",
        description="Enable customer profile API fallback when persona data is not found in database",
    )

    # AccountsEdge Service Configuration
    ACCOUNTS_EDGE_BASE_URL: str = Field(
        default="https://test02.core-experiences.test.aws.groupapi.cba/customer-portfolio/accountsedge",
        validation_alias="ACCOUNTS_EDGE_BASE_URL",
        description="Base URL for the AccountsEdge Service",
    )

    HOMELOAN_SERVICE_BASE_URL: str = Field(
        default="https://commbank-api-homeloans.app-syd.test.dp-retail.azure.test.au.internal.cba",
        validation_alias="HOMELOAN_SERVICE_BASE_URL",
        description="Base URL for the Home Loan Service",
    )

    ENABLE_CLIENTS_API: bool = Field(
        default=False,
        validation_alias="ENABLE_CLIENTS_API",
        description="Enable access to client-specific APIs (for hb calc saving to api db)",
    )

    ENABLE_CLIENTS_API_HOME_BUYING: bool = Field(
        default=False,
        validation_alias="ENABLE_CLIENTS_API_HOME_BUYING",
        description="Enable access to client-specific APIs (for hb calc saving to api db)",
    )

    ENABLE_BILL_WRITE_API: bool = Field(
        default=False,
        validation_alias="ENABLE_BILL_WRITE_API",
        description="Enable access to BillHub APIs which have write permissions",
    )
    ENABLE_CONSUMER_LOANS_API: bool = Field(
        default=False,
        validation_alias="ENABLE_CONSUMER_LOANS_API",
        description="Enable access to Consumer Loans API for personal loan account details",
    )
    ENABLE_MORTGAGE_LOANS_API: bool = Field(
        default=False,
        validation_alias="ENABLE_MORTGAGE_LOANS_API",
        description="Enable access to Mortgage Loans API for home loan account details",
    )
    # LaunchDarkly Configuration
    LAUNCHDARKLY_SDK_KEY: str | None = Field(
        default=None,
        validation_alias="LAUNCHDARKLY_SDK_KEY",
        description="LaunchDarkly SDK key for feature flag management",
    )
    LAUNCHDARKLY_OFFLINE: bool = Field(
        default=False,
        validation_alias="LAUNCHDARKLY_OFFLINE",
        description="Run LaunchDarkly in offline mode using default values",
    )
    LAUNCHDARKLY_BASE_URI: str | None = Field(
        default=None,
        validation_alias="LAUNCHDARKLY_BASE_URI",
        description="Base URI for LaunchDarkly server",
    )
    LAUNCHDARKLY_DISABLE_SSL_VERIFICATION: bool = Field(
        default=False,
        validation_alias="LAUNCHDARKLY_DISABLE_SSL_VERIFICATION",
        description="Disable SSL verification for LaunchDarkly SDK",
    )

    # Optional settings with defaults
    E2E_AGENT_HOST: str | None = None
    LANGFUSE_FLAG: bool = False

    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_PUBLIC_KEY: str | None = None
    RAG_KNOWLEDGE_BASE_FLAG: bool = False
    RAG_KNOWLEDGE_BASE_ID: str | None = "BASE_ID"
    RAG_KNOWLEDGE_BASE_MODEL: str | None = "BASE_MODEL"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_SESSION_TOKEN: str | None = None
    LANGFUSE_HOST: str | None = None
    RUN_ID: str = "default_run"
    LANGFUSE_DATASET_NAME: str | None = "default_lf_dataset"
    SKIP_IDP_AUTH_CHECK: bool = False
    JWKS_CACHE_TTL_SECONDS: int = 120  # 2 minutes JWKS cache

    # Investing Hub Basic Authentication
    INVESTING_HUB_AUTH_USERNAME: str | None = Field(
        default="defaultUsername",
        description="Username for Investing Hub basic authentication",
        validation_alias="INVESTING_HUB_AUTH_USERNAME",
    )
    INVESTING_HUB_AUTH_PASSWORD: str | None = Field(
        default="defaultPassword",
        description="Password for Investing Hub basic authentication",
        validation_alias="INVESTING_HUB_AUTH_PASSWORD",
    )
    # Investing Hub Guardrails Configuration
    INVESTINGHUB_GUARDRAILS_SERVICE_BASE_URL: str = Field(
        default="https://guardrail.wealthp1.dev.ai.dhp.cba",
        validation_alias="INVESTINGHUB_GUARDRAILS_SERVICE_BASE_URL",
        description="Base URL for the Guardrails Service used by Investing Hub agent",
    )
    INVESTINGHUB_GUARDRAILS_SERVICE_BUSINESS_UNIT: str = Field(
        default="Wealth&Private",
        validation_alias="INVESTINGHUB_GUARDRAILS_SERVICE_BUSINESS_UNIT",
        description="Business unit identifier for Investing Hub Guardrails Service",
    )

    REDIS_CONFIGURATION_ENDPOINT: str = Field(
        default="127.0.0.1:6379",
        validation_alias="REDIS_CONFIGURATION_ENDPOINT",
        description="Redis configuration endpoint - follows the DHP structure of embedding port number into URL",
    )

    REDIS_AUTH_TOKEN: str = Field(
        default="password",
        validation_alias="REDIS_AUTH_TOKEN",
        description="Authentication token for Redis connection",
    )

    REDIS_MAX_CONNECTIONS: int = Field(
        default=50,
        validation_alias="REDIS_MAX_CONNECTIONS",
        description="Maximum number of Redis connections in the pool",
    )

    REDIS_PENDING_MESSAGE_TTL_SECONDS: int = Field(
        default=120,
        validation_alias="REDIS_PENDING_MESSAGE_TTL_SECONDS",
        description="Time-to-live for pending messages in Redis, in seconds",
    )

    # Additional settings
    HTTP_TIMEOUT: int = 180  # Default HTTP timeout in seconds
    DHP_NON_PROD: bool = False  # Flag to indicate if DHP is in a lower environment
    USING_MOCK_API: bool = False  # Flag to indicate if mock API is being used
    SSL_ALB_CERT_PATH: str = ""  # Location of cert file for SSL usage
    SSL_ALB_KEY_PATH: str = ""  # Location of key file for SSL usage
    QUALITY_GUARDRAIL: Literal["ProcessAdherence", "AutomatedReasoning"] | None = None

    # OTLP Metrics Observability Configuration
    OTLP_METRICS_ENABLED: bool = Field(
        default=False,
        validation_alias="OTLP_METRICS_ENABLED",
        description="Feature flag to enable OTLP metrics export via observability library",
    )
    OTLP_METRICS_ENDPOINT: str = Field(
        default="https://dev.roti.cba:4318/ced/v1/metrics",
        validation_alias="OTLP_METRICS_ENDPOINT",
        description="OTLP collector endpoint URL for metrics export",
    )
    OTLP_METRICS_AUTH_SCHEME: str = Field(
        default="Bearer",
        validation_alias="OTLP_METRICS_AUTH_SCHEME",
        description="Authentication scheme for OTLP metrics endpoint (e.g., Bearer)",
    )
    OTLP_METRICS_AUTH_TOKEN: str = Field(
        default="",
        validation_alias="OTLP_METRICS_AUTH_TOKEN",
        description="Authentication token for OTLP metrics endpoint",
    )
    OTLP_SERVICE_NAME: str = Field(
        default="financial-companion-service",
        validation_alias="OTLP_SERVICE_NAME",
        description="Service name for OTLP resource attributes",
    )
    OTLP_DEPLOYMENT_ENVIRONMENT: str = Field(
        default="dev",
        validation_alias="OTLP_DEPLOYMENT_ENVIRONMENT",
        description="Deployment environment for OTLP resource attributes",
    )
    OTLP_CI_NUMBER: str = Field(
        default="CI107355678",
        validation_alias="OTLP_CI_NUMBER",
        description="CI number for OTLP resource attributes (from _RepoMetadata.yaml)",
    )
    OTLP_FEDERATED_OBSTACK_MODE: bool = Field(
        default=True,
        validation_alias="OTLP_FEDERATED_OBSTACK_MODE",
        description="Enable federated observability stack mode for OTLP metrics",
    )
    OTLP_BUSINESS_UNIT: str = Field(
        default="Retail Technology",
        validation_alias="OTLP_BUSINESS_UNIT",
        description="Business unit for OTLP resource attributes",
    )
    OTLP_DOMAIN: str = Field(
        default="Customer, Digital and AI",
        validation_alias="OTLP_DOMAIN",
        description="Domain for OTLP resource attributes",
    )
    OTLP_CREW: str = Field(
        default="Digital",
        validation_alias="OTLP_CREW",
        description="Crew for OTLP resource attributes",
    )
    OTLP_SQUAD: str = Field(
        default="Financial Companion",
        validation_alias="OTLP_SQUAD",
        description="Squad for OTLP resource attributes",
    )

    # Parallel Fact Extraction Configuration
    FACT_EXTRACTION_PARALLEL_ENABLED: bool = Field(
        default=True,
        validation_alias="FACT_EXTRACTION_PARALLEL_ENABLED",
        description="Enable parallel processing for fact extraction in automated reasoning guardrails",
    )
    FACT_EXTRACTION_CONCURRENCY: int = Field(
        default=4,
        validation_alias="FACT_EXTRACTION_CONCURRENCY",
        description="Number of concurrent fact extraction operations (1-20)",
    )

    # Conversation Streaming Configuration
    CONVERSATION_INTERIM_UPDATES_STREAM_POLL_INTERVAL_SECONDS: int = Field(
        default=2,
        validation_alias="CONVERSATION_INTERIM_UPDATES_STREAM_POLL_INTERVAL_SECONDS",
        description="Polling interval in seconds for interim progress updates of conversation streams",
    )
    CONVERSATION_INTERIM_UPDATES_STREAM_MAX_DURATION_SECONDS: int = Field(
        default=300,
        validation_alias="CONVERSATION_INTERIM_UPDATES_STREAM_MAX_DURATION_SECONDS",
        description="Maximum duration in seconds for interim updates of conversation streams before timeout",
    )

    # Resume Conversation Retry Configuration
    RESUME_CONVERSATION_RETRY_ATTEMPTS: int = Field(
        default=6,
        validation_alias="RESUME_CONVERSATION_RETRY_ATTEMPTS",
        description="Number of retry attempts when polling for new messages in resume conversation",
    )
    RESUME_CONVERSATION_RETRY_INTERVAL_SECONDS: int = Field(
        default=5,
        validation_alias="RESUME_CONVERSATION_RETRY_INTERVAL_SECONDS",
        description="Sleep interval in seconds between retry attempts in resume conversation",
    )
    SSO_DEEPLINK_KB_ID: str | None = Field(
        validation_alias="SSO_DEEPLINK_KB_ID",
        default="",
        description="SSO Deeplink KB ID",
    )

    # Gradio Settings
    GRADIO_USES_DHP: bool = False
    GRADIO_DHP_URL: str = ""
    GRADIO_DHP_SCOPES: str = "issued-device-administration-cards.cards-agentic.handle issued-device-administration-cards.cards-agentic.message"
    CIF_LIST_USING_MOCK_API: list[str] = Field(
        default_factory=lambda: [
            "00234567",
            "03456789",
            "09876543",
            "05432109",
            "07654321",
            "02345678",
            "08765432",
            "01234567",
            "04567890",
            "06543210",
            "00123456",
            "09876540",
        ],
        description="List of CIFs for the Gradio UI",
    )
    CIF_LIST: list[str] = Field(
        default_factory=lambda: [
            "2347662",
            "1309728",
            "416942",
            "553116",
            "1245978",
            "341831",
            "1696531",
            "1121290",
            "1142519",
            "779872",
            "1122155",
            "1243865",
            "729911250",
            "15876985",
            "426530",
            "1249561",
            "171382",
            "341844",
            "1151460",
            "406481690",
            "1241110",
            "331149",
            "775382",
        ],
        description="List of CIFs for the Gradio UI",
    )

    @property
    def e2e_agent_endpoint_url(self) -> str:
        """Constructs the full endpoint URL for the E2E agent.

        Returns:
            str: The complete URL endpoint for the E2E agent.

        Raises:
            ValueError: If E2E_AGENT_HOST is not set.
        """
        if self.E2E_AGENT_HOST is None:
            raise ValueError("E2E_AGENT_HOST is not set")
        return self.E2E_AGENT_HOST.rstrip("/") + "/chat"

    def validate_required_settings(self) -> None:
        """Validates that all required settings are properly set.

        For DHP, OPENAI_API_KEY is set in main.py and therefore not required here.

        Raises:
            ValueError: If any required setting is missing or invalid
        """
        required_settings = [
            "OPENAI_BASE_URL",
            "AGENT_LLM",
            "MOCK_API_SERVER_HOST",
            "MOCK_API_SERVER_PORT",
        ]

        for setting in required_settings:
            if not getattr(self, setting):
                raise ValueError(f"Required setting {setting} is not set")

        # Validate fact extraction concurrency setting
        if not MIN_FACT_EXTRACTION_CONCURRENCY <= self.FACT_EXTRACTION_CONCURRENCY <= MAX_FACT_EXTRACTION_CONCURRENCY:
            raise ValueError(
                f"FACT_EXTRACTION_CONCURRENCY must be between {MIN_FACT_EXTRACTION_CONCURRENCY} and {MAX_FACT_EXTRACTION_CONCURRENCY}, got {self.FACT_EXTRACTION_CONCURRENCY}"
            )


@lru_cache
def get_app_config() -> AppConfigSettings:
    """Returns a cached instance of the application configuration.

    Using this function instead of directly accessing the Config instance
    ensures that the configuration is loaded only when needed and cached
    for subsequent calls.

    Returns:
        AppConfigSettings: The application configuration instance
    """
    config = AppConfigSettings()
    config.validate_required_settings()

    # Set environment variables read in from .env or .env.local
    if config.model_extra is not None:
        for key, value in config.model_extra.items():
            os.environ[key] = str(value)

    return config


# Global configuration instance - use get_app_config() instead for new code
AppConfig = get_app_config()
