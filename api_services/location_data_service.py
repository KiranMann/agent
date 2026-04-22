"""Implementation of Location Data Service.

This module provides functionality to interact with the Location Data Management API
for operations such as verifying addresses.
"""

from typing import Any

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.services.service_api_base import ServiceAPIBase


class LocationDataService(ServiceAPIBase):
    """A class representing the Location Data Service API.

    This class is responsible for interacting with the Location Data Management API
    to perform operations related to address verification and management.
    It inherits from the ServiceAPIBase class, which provides common functionality
    for making API calls and handling authentication.
    """

    def __init__(
        self,
        name: str = "LocationData-Service",
        base_url: str = f"{AppConfig.LOCATION_DATA_SERVICE_BASE_URL}",
    ):
        """Initialize the LocationDataService instance.

        Sets up the base URL, client ID, and scope for the API.

        Args:
            name (str): The name of the service.
            base_url (str): The base URL for the API.
        """
        super().__init__(
            name=name,
            base_url=base_url,
            client_id=AppConfig.GROUP_IDP_CLIENT_ID,
            scope="location-data-management.addresses.write",
        )

    async def verify_addresses(  # pylint: disable=dangerous-default-value
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> tuple[bool, str]:
        """Verify addresses by sending them to the Location Data Management API.

        This method constructs the necessary headers and makes an asynchronous POST request
        to the Location Data Management API to verify the provided addresses.

        Args:
            payload (dict): A dictionary containing the address information to be verified.
            headers (LocationDataServiceHeaders): Optional headers to include in the request, by default {}.

        Returns:
            bool: True if the address was successfully verified, False otherwise.

        Raises:
            ValueError: If the API call fails (status code is not 200).
        """
        logger.debug(f"Verifying addresses with payload: {payload}")

        if headers is None:
            headers = {}

        headers = {
            "x-department-code": headers.get("x-department-code", "012522"),
        }

        response = await self.post_call(
            path="/addresses/v1/verified-addresses",
            headers=headers,
            payload=payload,
        )
        if str(response.status_code)[0] != "2":
            raise ValueError("LocationDataService: failed to get verify address")
        data = response.json()
        items = data if AppConfig.USING_MOCK_API else data.get("items")

        # Check if address was verified and domestic
        if isinstance(items, list) and len(items) > 0 and items[0].get("status") == "SUCCESS" and items[0].get("data"):
            found_addr = items[0].get("data")
            if (
                found_addr.get("validationStatus", {}).get("isValidAddress", False)
                and found_addr.get("details", {}).get("country", {}).get("code") == "AU"
            ):
                ldm = found_addr.get("identifiers", {}).get("ldmAddressId")
                return True, ldm

        return False, "N/A"


# UNUSED
location_data_service = LocationDataService()
