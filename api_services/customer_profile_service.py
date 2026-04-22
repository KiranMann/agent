"""Customer Profile Service Module.

This module provides functionality to interact with the CommBank Customer Profile API
for retrieving customer contact details as a fallback when persona data is not available.

The service uses Bearer token authentication with dptoken from customer_details and
is designed to extract the 'individual' section from the customer profile response
for use as basic customer information.
"""

import uuid
from http import HTTPStatus
from typing import Any

from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.services.service_api_base import AuthType, ServiceAPIBase


class CustomerProfileService(ServiceAPIBase):
    """Customer Profile Service API client.

    This class provides methods to interact with the CommBank Customer Profile API
    for retrieving basic customer information as a fallback when persona data
    is not available in the database.
    """

    # Error message constants
    INVALID_TOKEN_ERROR_MESSAGE = "Invalid or missing dptoken"  # noqa: S105
    INDIVIDUAL_DATA_NOT_FOUND = "Individual data not found in response"

    def __init__(
        self,
        name: str = "customer-profile-service",
        base_url: str = AppConfig.CUSTOMER_PROFILE_SERVICE_BASE_URL,
    ):
        """Initialize the CustomerProfileService instance.

        Sets up the service with Bearer token authentication and base URL
        for the Customer Profile API service.

        Args:
            name (str): Identifier for the service instance
            base_url (str): Base URL for the API endpoints
        """
        # Initialize the base class with the service configuration
        super().__init__(
            name=name,
            base_url=base_url or AppConfig.CUSTOMER_PROFILE_SERVICE_BASE_URL,
        )

    async def get_customer_profile(
        self,
        customer_details: dict[str, Any],
        correlation_id: str | None = None,
        x_request_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve customer profile information including individual details.

        This method calls the CommBank Customer Profile API to retrieve
        customer contact details and personal information using Bearer token authentication.
        The customer is identified by the dptoken in customer_details.

        Args:
            customer_details (Dict): Customer details containing dptoken for authentication
            correlation_id (Optional[str]): Correlation ID for request tracking
            x_request_id (Optional[str]): Request ID for request tracking
            headers (Optional[Dict]): Optional additional headers to include in the request

        Returns:
            Dict[str, Union[bool, dict, str]]: Dictionary containing:
                - "result": Boolean indicating if the request was successful
                - "data": Customer profile data if successful, error details otherwise
        """
        logger.debug("Retrieving customer profile using dptoken authentication")

        # Extract dptoken from customer_details
        dptoken = customer_details.get("dptoken")
        if not dptoken:
            logger.error(f"Cannot retrieve customer profile: {self.INVALID_TOKEN_ERROR_MESSAGE}")
            return {
                "result": False,
                "data": {"error": self.INVALID_TOKEN_ERROR_MESSAGE},
            }

        # Construct the API path
        path = "/xapi/manage-contact-detail/v1/customer-profile"

        if headers is None:
            headers = {}

        # Set required headers
        headers.update(
            {
                "correlationid": correlation_id or str(uuid.uuid4()),
                "x-request-id": x_request_id or "string",
            }
        )

        try:
            response = await self.get_call(
                path=path,
                headers=headers,
                auth_type=AuthType.BEARER,
                bearer_token=dptoken,
            )

            if response.status_code == HTTPStatus.OK:
                logger.debug("Customer profile retrieval successful")
                response_data = response.json()

                # Validate that we have the expected structure
                if isinstance(response_data, dict) and "individual" in response_data:
                    logger.debug("Successfully retrieved customer profile with individual data")
                    return {
                        "result": True,
                        "data": response_data,
                    }
                else:
                    logger.error("Individual data not found in customer profile response")
                    return {
                        "result": False,
                        "data": {
                            "error": self.INDIVIDUAL_DATA_NOT_FOUND,
                            "response": response_data,
                        },
                    }
            else:
                logger.error(f"Customer profile retrieval failed with status {response.status_code}: {response.text}")
                return {
                    "result": False,
                    "data": {
                        "error": response.text,
                        "status_code": response.status_code,
                    },
                }

        except Exception as e:
            logger.error(f"Error retrieving customer profile: {e!s}")
            return {
                "result": False,
                "data": {"error": str(e)},
            }

    @staticmethod
    def transform_individual_to_persona(individual_data: dict[str, Any]) -> dict[str, Any]:
        """Transform the 'individual' section from the API response into persona format.

        Returns the same structure as production personas from PersonalisationAgent.

        Args:
            individual_data (dict): The 'individual' section from the API response

        Returns:
            dict: Transformed data in production persona format
        """
        try:
            # Extract individual fields with defaults
            first_name = individual_data.get("firstName", "")
            last_name = individual_data.get("lastName", "")
            preferred_name = individual_data.get("preferredName", "")

            # Create display name for persona summary
            display_name = preferred_name or first_name
            full_display_name = f"{display_name} {last_name}".strip()

            # Transform to production persona format (same as PersonalisationAgent output)
            persona_data = {
                "persona_summary": (f"Customer: {full_display_name}" if full_display_name else "Customer Profile"),
                "conversation_count": 0,  # API fallback has no conversation history
                "correlation_id": "",  # Empty for API fallback
                "analysis_timestamp": "",  # Empty for API fallback
                "agent_version": "api_fallback",  # Distinguish from PersonalisationAgent_v1
            }

            logger.debug("Successfully transformed individual data from API to production persona format")
            return persona_data

        except Exception as e:
            logger.error(f"Error transforming individual data: {e!s}")
            # Return minimal fallback data in production format
            return {
                "persona_summary": "Customer Profile",
                "conversation_count": 0,
                "correlation_id": "",
                "analysis_timestamp": "",
                "agent_version": "api_fallback_error",
            }


# UNUSED
# Create a singleton instance for easy import
customer_profile_service = CustomerProfileService()
