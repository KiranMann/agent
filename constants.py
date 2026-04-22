"""Constants for financial companion agent."""

from enum import StrEnum
from pathlib import Path

import common

# agent keys used across modules, e.g., in guardrails and in orchestration
SYNTHESIS_AGENT_KEY = "synthesis_agent"
MIME_TYPE_JSON = "application/json"
COMMON_DIR = Path(common.__file__).resolve().parent
ROOT_DIR = COMMON_DIR.parent
ENVS_DIR = ROOT_DIR / "envs"


class AgentType(StrEnum):
    """Constants for agent types to avoid magic strings."""

    SAVINGS = "SavingsAgent"
    PRODUCTS = "ProductsAgent"
    HOMEBUYING = "HomebuyingAgent"
    INVESTINGHUB = "InvestinghubAgent"
    FINANCIAL = "FinancialCompanionAgent"
    PAYMENT = "PaymentAgent"
    GENERAL_QUERIES = "GeneralQueriesAgent"
