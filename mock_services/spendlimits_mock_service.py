# pylint: disable=unused-argument
"""Mock implementation of spendlimits_service write functions for testing/evals"""

# pylint: disable=unused-import
from typing import Any

from apps.companion.all_agents.task_agents.savings_agent.services.spendlimits_service import SpendLimitsService
from apps.companion.all_agents.task_agents.savings_agent.services.spendlimits_service import (
    spendlimits_service as real_service,
)
from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdException(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdException()


class MockSpendLimitsService(SpendLimitsService):
    """Mock implementation of SpendLimitsService for testing purposes."""

    def _get_cached_response(self, method_name: str, input_params: dict[str, Any]) -> dict[str, Any] | None:
        """Helper method to find a cached response based on method name and input parameters."""
        cached_response = find_matching_response(self, method_name, input_params)
        return cached_response if cached_response is not None else return_default_mock_response()

    async def get_cycle_settings(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_cycle_settings - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }
        logger.info(f"Mock: get_cycle_settings called with input: {input_params}")
        cached_response = find_matching_response(self, "get_cycle_settings", input_params)
        logger.info(f"Mock: get_left_to_spend response: {cached_response}")

        if cached_response is not None:
            logger.info(f"Returning cached response for get_cycle_settings with cif_code: {cif_code}")
            return cached_response
        else:
            return return_default_mock_response()

    async def get_left_to_spend(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_left_to_spend - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_left_to_spend", input_params)

    async def get_limits(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
        categories: str | None = None,
        frequency=None,
        cycle_restart_date=None,
    ) -> dict[str, Any]:
        """Mock get_limits - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
            "categories": categories,
            "frequency": frequency.value if frequency else None,
            "cycle_restart_date": (cycle_restart_date.isoformat() if cycle_restart_date else None),
        }
        logger.info(f"Mock: get_limits called with input: {input_params}")

        cached_response = find_matching_response(self, "get_limits", input_params)
        logger.info(f"Mock: get_limits response: {cached_response}")

        if cached_response is not None:
            logger.info(f"Returning cached response for get_limits with cif_code: {cif_code}")
            return cached_response
        else:
            return return_default_mock_response()

    async def get_all_categories(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_all_categories - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }
        logger.info(f"Mock: get_all_categories called with input: {input_params}")

        cached_response = find_matching_response(self, "get_all_categories", input_params)
        logger.info(f"Mock: get_all_categories response: {cached_response}")

        if cached_response is not None:
            logger.info(f"Returning cached response for get_all_categories with cif_code: {cif_code}")
            return cached_response
        else:
            return return_default_mock_response()

    async def get_category_transactions(
        self,
        cif_code: str,
        category: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
        frequency=None,
        cycle_restart_date=None,
        cycle_index: int | None = None,
    ) -> dict[str, Any]:
        """Mock get_category_transactions - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "category": category,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
            "frequency": frequency.value if frequency else None,
            "cycle_restart_date": (cycle_restart_date.isoformat() if cycle_restart_date else None),
            "cycle_index": cycle_index,
        }

        return self._get_cached_response("get_category_transactions", input_params)

    async def get_category_spend_history(
        self,
        cif_code: str,
        category: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_category_spend_history - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "category": category,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_category_spend_history", input_params)

    async def get_spend_summary(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
        frequency=None,
        cycle_seed_date=None,
    ) -> dict[str, Any]:
        """Mock get_spend_summary - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
            "frequency": frequency.value if frequency else None,
            "cycle_seed_date": cycle_seed_date.isoformat() if cycle_seed_date else None,
        }

        return self._get_cached_response("get_spend_summary", input_params)

    async def get_card_prediction(
        self,
        cif_code: str,
        prediction_data: dict[str, Any],
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_card_prediction - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "prediction_data": prediction_data,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }

        return self._get_cached_response("get_card_prediction", input_params)

    async def update_cycle_settings(
        self,
        cif_code: str,
        cycle_settings: dict[str, Any],
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock update_cycle_settings - returns success"""
        return {"success": True, "message": "Cycle settings updated"}

    async def update_category_limit(
        self,
        cif_code: str,
        category: str,
        limit_data: dict[str, Any],
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock update_category_limit - returns success"""
        return {"success": True, "message": "Category limit updated"}

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


spendlimits_mock_service = MockSpendLimitsService()
