# pylint: disable=unused-argument
"""Mock implementation of cashflow_service for testing/evals"""

# pylint: disable=unused-import
from datetime import datetime
from typing import Any

from apps.companion.all_agents.task_agents.savings_agent.services.cashflow_service import (
    AccountsView,
    CashflowService,
    CreditDebitType,
)
from apps.companion.all_agents.task_agents.savings_agent.services.cashflow_service import (
    cashflow_service as real_service,
)
from common.configs.app_config_settings import AppConfig
from mock_services.util import find_matching_response
from mock_services.util.mock_utils import return_default_mock_response


# Enforce no mocks in higher environments
class NoMocksInProdError(Exception):
    pass


if AppConfig.MOCK_API_FLAG is False:
    raise NoMocksInProdError()


class MockCashflowService(CashflowService):
    """Mock implementation of CashflowService for testing purposes."""

    async def get_account_settings(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_account_settings - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(self, "get_account_settings", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_summary(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_summary - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_summary", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_summary_transaction_types(
        self,
        cif_code: str,
        transaction_types: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        include_average: bool = False,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_summary_transaction_types - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "transaction_types": transaction_types,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "include_average": include_average,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_summary_transaction_types", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_accounts(
        self,
        cif_code: str,
        account_view: AccountsView,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        for_date: datetime | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_accounts - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "account_view": account_view.value,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "for_date": for_date.isoformat() if for_date else None,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_accounts", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_categories(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        for_date: datetime | None = None,
        transaction_type: str | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_categories - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "for_date": for_date.isoformat() if for_date else None,
            "transaction_type": transaction_type,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_categories", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_top_categories(
        self,
        cif_code: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        for_date: datetime | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_top_categories - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "for_date": for_date.isoformat() if for_date else None,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_top_categories", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_cashflow_spend_tracker(
        self,
        cif_code: str,
        account_hash: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        for_date: datetime | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_cashflow_spend_tracker - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "account_hash": account_hash,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "for_date": for_date.isoformat() if for_date else None,
            "period": period,
        }

        cached_response = find_matching_response(self, "get_cashflow_spend_tracker", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_insights(
        self,
        cif_code: str,
        account_hash: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_insights - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "account_hash": account_hash,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(self, "get_insights", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_savings_summary(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        cif_code: str | None = None,
        timescale: int | None = None,
        frequency: str | None = None,
        reset_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Mock get_savings_summary - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "cif_code": cif_code,
            "timescale": timescale,
            "frequency": frequency,
            "reset_date": reset_date.isoformat() if reset_date else None,
        }

        ignored_keys = [
            "referer",
            "correlation_id",
            "session_id",
            "cba_device_id",
            "cba_client_ip",
            "timescale",
            "reset_date",
        ]

        cached_response = find_matching_response(self, "get_savings_summary", input_params, ignored_keys=ignored_keys)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_savings_account_preferences(
        self,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
        cif_code: str | None = None,
    ) -> dict[str, Any]:
        """Mock get_savings_account_preferences - returns cached response based on input parameters."""
        input_params = {
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
            "cif_code": cif_code,
        }

        cached_response = find_matching_response(self, "get_savings_account_preferences", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_transactions_by_category_and_card_type(
        self,
        cif_code: str,
        category: str,
        credit_debit_type: CreditDebitType,
        account_hash: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        from_date: str,
        to_date: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_transactions_by_category_and_card_type - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "category": category,
            "credit_debit_type": credit_debit_type.value,
            "account_hash": account_hash,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "from_date": from_date,
            "to_date": to_date,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(self, "get_transactions_by_category_and_card_type", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_transactions_by_category_type(
        self,
        cif_code: str,
        category: str,
        referer: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        from_date: str,
        to_date: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_transactions_by_category_type - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "category": category,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "from_date": from_date,
            "to_date": to_date,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(self, "get_transactions_by_category_type", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    async def get_all_account_transactions(
        self,
        cif_code: str,
        referer: str,
        account_hash: str,
        correlation_id: str,
        netbank_id: str,
        session_id: str,
        from_date: str,
        to_date: str,
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_all_account_transactions - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "account_hash": account_hash,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "from_date": from_date,
            "to_date": to_date,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(
            self,
            "get_all_account_transactions",
            input_params,
            ignored_keys=[
                "referer",
                "correlation_id",
                "session_id",
                "cba_device_id",
                "cba_client_ip",
                "from_date",
                "to_date",
            ],
        )

        if cached_response is not None:
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
        cba_device_id: str,
        cba_client_ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        """Mock get_all_categories - returns cached response based on input parameters."""
        input_params = {
            "cif_code": cif_code,
            "referer": referer,
            "correlation_id": correlation_id,
            "netbank_id": netbank_id,
            "session_id": session_id,
            "cba_device_id": cba_device_id,
            "cba_client_ip": cba_client_ip,
        }

        cached_response = find_matching_response(self, "get_all_categories", input_params)

        if cached_response is not None:
            return cached_response
        else:
            return return_default_mock_response()

    # Delegate all other methods to real service
    def __getattr__(self, name):
        return getattr(real_service, name)


cashflow_mock_service = MockCashflowService()
