# pylint: disable=unused-argument
"""Mock implementation of enriched_transactions_service for testing/evals"""

from typing import Any

from apps.companion.all_agents.task_agents.savings_agent.services.enriched_transactions_service import (
    EnrichedTransactionsService,
)
from apps.companion.all_agents.task_agents.savings_agent.services.enriched_transactions_service import (
    enriched_transactions_service as real_service,
)
from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdError(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdError()


class MockEnrichedTransactionsService(EnrichedTransactionsService):
    """Mock implementation of EnrichedTransactionsService for testing purposes."""

    async def transactions_query_all(
        self,
        request: dict[str, Any],
        referer: str,
        correlation_id: str,
        netbank_id: str,
        cif_code: str,
        session_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock transactions_query_all - returns cached response based on input parameters."""
        input_params = {
            "request": request,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "cif_code": cif_code,
            "session_id": session_id,
            "cba_client_ip": cba_client_ip,
        }
        logger.info(f"Mock: transactions_query_all called with input: {input_params}")
        ignored_keys = [
            "referer",
            "correlation_id",
            "session_id",
            "cba_device_id",
            "cba_client_ip",
            "request",
        ]
        cached_response = find_matching_response(
            self, "transactions_query_all", input_params, ignored_keys=ignored_keys
        )

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


enriched_transactions_mock_service = MockEnrichedTransactionsService()
