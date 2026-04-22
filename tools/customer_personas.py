"""Customer personas SQLAlchemy-based repository.

This module provides SQLAlchemy-based operations for managing
customer personalisation data storage using async sessions.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.companion.all_agents.services import commbank_client_service, guardrails_service
from common.configs.agent_config_settings import AgentConfig
from common.configs.app_config_settings import AppConfig
from common.database.models import CustomerPersonas as CustomerPersonasModel
from common.logging.core import logger


class CustomerPersonas:
    """SQLAlchemy-based handler for managing customer personalisation data.

    Provides methods for storing and retrieving customer persona information
    using SQLAlchemy async sessions with PII guardrail integration.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        """Initialize CustomerPersonas with optional session.

        Args:
            session: Optional AsyncSession. If not provided, will use get_db_session()
        """
        self._session = session

    async def _get_session(self) -> AsyncSession:
        """Get the database session."""
        if self._session is not None:
            return self._session
        # This will be used when called from outside with get_db_session()
        raise ValueError("No session provided. Use async context manager with get_db_session()")

    async def store_customer_personalisation(
        self,
        cif_code: str,
        personalisation: dict[str, Any],
        netbank_id: str | None = None,
    ) -> None:
        """Store personalisation data for a given CIF code in the database.

        Args:
            cif_code: The customer CIF code identifier.
            personalisation: The personalisation data to store.
            netbank_id: The customer netbank ID for LaunchDarkly targeting.
        """
        # Apply PII guardrails if enabled
        if AppConfig.ENABLE_MEMORY_PII_GUARDRAIL:
            try:
                masked_personalisation = await guardrails_service.pii_check(
                    user_input=json.dumps(personalisation, default=str),
                    parameters=AgentConfig.PII_PARAMETERS,
                )
                masked_output = masked_personalisation.get("masked_output", "{}")
                personalisation_data = json.loads(masked_output) if masked_output else {}
            except Exception as e:
                logger.error(f"Error applying PII guardrail to personalisation data for customer: {e}")
                # Do not store potentially sensitive data if guardrail fails
                personalisation_data = {}
        else:
            personalisation_data = personalisation

        session = None
        try:
            session = await self._get_session()

            # Use PostgreSQL UPSERT (INSERT ... ON CONFLICT DO UPDATE)
            stmt = insert(CustomerPersonasModel).values(
                customer_id=cif_code,
                netbank_id=netbank_id,
                personalisation_data=personalisation_data,
                version_number=1,
            )

            # On conflict, update the data and increment version
            stmt = stmt.on_conflict_do_update(
                index_elements=["customer_id"],
                set_={
                    "netbank_id": stmt.excluded.netbank_id,
                    "personalisation_data": stmt.excluded.personalisation_data,
                    "version_number": CustomerPersonasModel.version_number + 1,
                    "updated_at": stmt.excluded.updated_at,
                },
            )

            await session.execute(stmt)
            await session.commit()

            logger.info(f"Successfully stored personalisation data for customer {cif_code}")

        except Exception as e:
            logger.error(f"Error storing customer personalisation to DB: {e}")
            if session:
                await session.rollback()
            raise

    async def retrieve_customer_personalisation(
        self,
        cif_code: str,
        customer_details: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve the personalisation data for a given CIF code from the database.

        If no data is found in the database and fallback is enabled, attempts to retrieve
        basic customer information from the Clients API as a fallback.

        Args:
            cif_code: The customer CIF code identifier.
            customer_details: Customer details containing cif_code and client_ip_address for API authentication.

        Returns:
            The personalisation data for the customer, or None if not found or error.
        """
        # First, try to retrieve from database
        persona_data = await self._retrieve_from_database(cif_code)

        if persona_data is not None:
            logger.debug("Retrieved personalisation data from database successfully.")
            return persona_data

        # If no database data and fallback is enabled, try API fallback
        if AppConfig.ENABLE_CUSTOMER_PROFILE_FALLBACK:
            logger.info("No personalisation data found in database for customer, attempting API fallback")
            return await self._retrieve_from_api_fallback(cif_code, customer_details)
        else:
            logger.info("No personalisation data found for customer and fallback is disabled")
            return None

    async def _retrieve_from_database(
        self,
        cif_code: str,
    ) -> dict[str, Any] | None:
        """Retrieve personalisation data from the database with validation.

        Args:
            cif_code: The customer CIF code identifier.

        Returns:
            The personalisation data for the customer, or None if not found or error.
        """
        try:
            session = await self._get_session()
            # Query for the customer persona
            stmt = select(CustomerPersonasModel).where(CustomerPersonasModel.customer_id == cif_code)
            result = await session.execute(stmt)
            persona_record = result.scalar_one_or_none()
            if persona_record is not None:
                # SQLAlchemy JSON field returns Any, so we need to validate and type
                persona_data_raw: Any = persona_record.personalisation_data

                # Ensure it's a dict
                if not isinstance(persona_data_raw, dict):
                    logger.warning(f"Persona data is not a dict for customer: {type(persona_data_raw)}")
                    return None

                # Now we know it's a dict, create properly typed variable
                persona_data: dict[str, Any] = persona_data_raw

                # Validate persona structure - must have persona_summary
                if self._validate_persona_structure(persona_data):
                    return persona_data
                else:
                    return None  # Invalid structure, return None to proceed without personalization
            else:
                return None
        except ValueError as ve:
            # Handle session not available error specifically
            if "No session provided" in str(ve):
                logger.warning(f"No session available for retrieving personalisation: {ve}")
                return None
            else:
                logger.error(f"Error retrieving personalisation for customer from DB: {ve}")
                return None
        except Exception as e:
            logger.error(f"Error retrieving personalisation for customer from DB: {e}")
            return None

    def _validate_persona_structure(self, persona_data: dict[str, Any]) -> bool:
        """Validate that persona data has the required structure.

        Args:
            persona_data: The persona data to validate

        Returns:
            True if valid, False if invalid
        """
        if "persona_summary" not in persona_data:
            logger.warning("Invalid persona structure for customer: missing persona_summary field")
            return False

        if not isinstance(persona_data["persona_summary"], str):
            logger.warning("Invalid persona structure for customer: persona_summary is not a string")
            return False

        # persona_summary should not be empty
        if not persona_data["persona_summary"].strip():
            logger.warning("Invalid persona structure for customer: persona_summary is empty")
            return False

        return True

    async def _retrieve_from_api_fallback(
        self,
        cif_code: str,
        customer_details: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve basic customer information from the Clients API as a fallback.

        Args:
            cif_code: The customer CIF code identifier.
            customer_details: Customer details containing required information for API authentication.

        Returns:
            Basic personalisation data from API, or None if error.
        """
        try:
            # Check if customer_details is provided
            if not customer_details:
                logger.warning("No customer_details provided for API fallback for customer")
                return None
            # Extract required parameters for clients API
            cif = customer_details.get("cif_code") or cif_code
            client_ip_address = customer_details.get("client_ip_address", "127.0.0.1")
            # Call the clients API
            api_response = await commbank_client_service.get_customer_profile_for_persona(
                cif=cif,
                client_ip_address=client_ip_address,
            )
            if not api_response.get("result", False):
                logger.warning(f"Clients API call failed for customer: {api_response.get('data', {})}")
                return None
            # Extract the response data
            profile_data = api_response.get("data", {})
            if not isinstance(profile_data, dict):
                logger.warning(f"Unexpected data type in Clients API response for customer: {type(profile_data)}")
                return None
            # Transform the client data to persona format
            # This returns Any, so we need to validate
            raw_persona_data: Any = commbank_client_service.transform_client_data_to_persona(profile_data)

            # Validate the return type
            if not isinstance(raw_persona_data, dict):
                logger.warning(f"transform_client_data_to_persona returned unexpected type: {type(raw_persona_data)}")
                return None

            # Now we know it's a dict at runtime, create properly typed variable
            persona_dict: dict[str, Any] = raw_persona_data

            logger.info("Successfully retrieved and transformed customer profile data from Clients API for customer")

            # Ensure we persist basic customer information (name etc)
            try:
                await self.store_customer_personalisation(cif_code=cif_code, personalisation=persona_dict)
                logger.info("Successfully persisted API-sourced customer data as seed persona for customer.")
            except Exception as persist_error:
                logger.error(f"Failed to persist API-sourced customer data for customer: {persist_error}")

            return persona_dict

        except Exception as e:
            logger.error(f"Error retrieving customer profile from Clients API for customer: {e!s}")
            return None


# Convenience function for use with async context manager
async def get_customer_personas_repository() -> CustomerPersonas:
    """Get a CustomerPersonas repository instance.

    This should be used within an async context manager with get_db_session().

    Example:
        async with get_db_session() as session:
            repo = CustomerPersonas(session)
            await repo.store_customer_personalisation(...)
    """
    return CustomerPersonas()
