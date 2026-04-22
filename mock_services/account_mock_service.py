# pylint: disable=unused-argument
"""Mock implementation of account_services for testing/evals"""

# pylint: disable=unused-import
from typing import Any

from apps.companion.all_agents.task_agents.payment_agent.services.account_services import AccountServices
from apps.companion.all_agents.task_agents.payment_agent.services.account_services import (
    account_services as real_service,
)
from common.configs.app_config_settings import AppConfig
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdException(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdException()


class MockAccountServices(AccountServices):
    """Mock implementation of AccountServices for testing purposes."""

    async def get_accounts(
        self,
        cif_code: str,
        netbank_id: str,
        session_id: str,
        correlation_id: str,
        referer: str,
        is_business_credit_card_enabled: bool | None = None,
        headers: dict | None = None,
    ) -> dict[str, Any]:
        """Mock get_accounts - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "referer": referer,
            "is_business_credit_card_enabled": is_business_credit_card_enabled,
            "headers": headers,
        }

        cached_response = find_matching_response(
            self,
            "get_accounts",
            input_params,
            ignored_keys=[
                "headers",
                "is_business_credit_card_enabled",
                "referer",
                "correlation_id",
                "session_id",
            ],
        )

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_default_account(
        self,
        cif_code: str,
        netbank_id: str,
        session_id: str,
        correlation_id: str,
        referer: str,
        headers: dict | None = None,
    ) -> dict[str, Any]:
        """Mock get_default_account - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "referer": referer,
            "headers": headers,
        }

        cached_response = find_matching_response(self, "get_default_account", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


account_mock_service = MockAccountServices()
