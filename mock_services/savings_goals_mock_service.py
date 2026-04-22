# pylint: disable=unused-argument
"""Mock implementation of savings_goals_service for testing/evals"""

# pylint: disable=unused-import
from typing import Any

from apps.companion.all_agents.task_agents.savings_agent.services.savings_goals_service import SavingsGoalsService
from apps.companion.all_agents.task_agents.savings_agent.services.savings_goals_service import (
    savings_goals_service as real_service,
)
from common.configs.app_config_settings import AppConfig
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdException(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdException()


class MockSavingsGoalsService(SavingsGoalsService):
    """Mock implementation of SavingsGoalsService for testing purposes."""

    def _get_cached_response(self, method_name: str, input_params: dict[str, Any]) -> dict[str, Any] | None:
        """Helper method to find a cached response based on method name and input parameters."""
        cached_response = find_matching_response(self, method_name, input_params)
        return cached_response if cached_response is not None else return_default_mock_response()

    async def get_accounts(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_accounts - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_accounts", input_params)

    async def get_goals_history(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_goals_history - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_goals_history", input_params)

    async def get_goals(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_goals - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_goals", input_params)

    async def get_goal(
        self,
        goal_id: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_goal - returns cached response based on input parameters."""
        input_params = {
            "goal_id": goal_id,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_goal", input_params)

    async def get_goal_transactions(
        self,
        goal_id: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_goal_transactions - returns cached response based on input parameters."""
        input_params = {
            "goal_id": goal_id,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_goal_transactions", input_params)

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


savings_goals_mock_service = MockSavingsGoalsService()
