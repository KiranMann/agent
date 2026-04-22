"""Mock implementation of billhub_service for testing/evals"""

from typing import Any

from apps.companion.all_agents.task_agents.savings_agent.services.billhub_service import BillHubService
from apps.companion.all_agents.task_agents.savings_agent.services.billhub_service import billhub_service as real_service
from common.configs.app_config_settings import AppConfig
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdException(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdException()


class MockBillHubService(BillHubService):
    """Mock implementation of BillHubService for testing purposes."""

    def _get_cached_response(self, method_name: str, input_params: dict[str, Any]) -> dict[str, Any] | None:
        """Helper method to find a cached response based on method name and input parameters."""
        cached_response = find_matching_response(self, method_name, input_params)
        return cached_response if cached_response is not None else return_default_mock_response()

    async def get_bill_instances(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_bill_instances - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_bill_instances", input_params)

    async def get_bills_by_status(
        self,
        statuses: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_bills_by_status - returns cached response based on input parameters."""
        input_params = {
            "statuses": statuses,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_bills_by_status", input_params)

    async def get_predicted_bills(
        self,
        statuses: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_predicted_bills - returns cached response based on input parameters."""
        input_params = {
            "statuses": statuses,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_predicted_bills", input_params)

    async def get_unconfirmed_predicted_bills(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_unconfirmed_predicted_bills - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_unconfirmed_predicted_bills", input_params)

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


billhub_mock_service = MockBillHubService()
