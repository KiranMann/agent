# ruff: noqa: PLC0415
"""Mock services module for mock implementations.

Note: Imports are intentionally not done at module level to avoid circular imports.
Import directly from the specific mock service module instead:
    from mock_services.account_mock_service import account_mock_service
"""

__all__ = [
    "account_mock_service",
    "billhub_mock_service",
    "cashflow_mock_service",
    "savings_goals_mock_service",
    "shopping_deals_mock_service",
    "spendlimits_mock_service",
]


def __getattr__(name: str) -> object:
    """Lazy import to avoid circular dependencies."""
    if name == "account_mock_service":
        from mock_services.account_mock_service import account_mock_service

        return account_mock_service
    if name == "billhub_mock_service":
        from mock_services.billhub_mock_service import billhub_mock_service

        return billhub_mock_service
    if name == "cashflow_mock_service":
        from mock_services.cashflow_mock_service import cashflow_mock_service

        return cashflow_mock_service
    if name == "savings_goals_mock_service":
        from mock_services.savings_goals_mock_service import savings_goals_mock_service

        return savings_goals_mock_service
    if name == "shopping_deals_mock_service":
        from mock_services.shopping_deals_mock_service import shopping_deals_mock_service

        return shopping_deals_mock_service
    if name == "spendlimits_mock_service":
        from mock_services.spendlimits_mock_service import spendlimits_mock_service

        return spendlimits_mock_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
