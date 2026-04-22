# pylint: disable=unused-argument
"""Mock implementation of accounts_edge_service for testing/evals"""

# pylint: disable=unused-import
from typing import Any

from apps.companion.all_agents.services.accounts_edge_service import AccountsEdgeService as BaseAccountsEdgeService
from common.configs.app_config_settings import AppConfig
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdException(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdException()


class MockAccountsEdgeService(BaseAccountsEdgeService):
    """Mock implementation of AccountsEdgeService for testing purposes."""

    async def get_accounts(
        self,
        customer_details: dict[str, Any],
        user_agent: str,
        retry: int | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mock get_accounts - returns cached response based on input parameters."""
        input_params = {
            "customer_details": customer_details,
            "user_agent": user_agent,
            "retry": retry,
            "headers": headers,
        }

        cached_response = find_matching_response(
            self,
            "get_accounts",
            input_params,
        )

        if cached_response is not None:
            return cached_response

        return return_default_mock_response()


# Replace the real service with the mock
accounts_edge_service = MockAccountsEdgeService()
