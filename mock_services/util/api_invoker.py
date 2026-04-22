#!/usr/bin/env python3
"""
API Invoker Module

This module handles API invocation for different service types.
It extracts API invocation logic from the original io_recorder.py file.
"""

import importlib
import traceback
from datetime import datetime
from typing import Any

from common.logging.core import logger


class APIInvoker:
    """Handles API invocation for different service types."""

    def __init__(self, parameter_mode: str = "all") -> None:
        """Initialize the API invoker.

        Args:
            parameter_mode: Parameter mode for handling session parameters ("all", "required_only", "custom")
        """
        self.service_instances: dict[str, Any] = {}
        self.parameter_mode = parameter_mode

    async def invoke_api(
        self,
        api_method: str,
        parameters: dict[str, Any],
        enum_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Invoke an API method with the given parameters.

        Args:
            api_method: The API method to invoke (e.g., "api_services.cashflow_service.CashflowService.get_account_settings")
            parameters: Dictionary of parameters to pass to the API method
            enum_metadata: Optional metadata for converting special parameters

        Returns:
            Dictionary containing success status and either data or error information
        """
        try:
            # Parse the API method name
            service_module, service_class, method_name = self._parse_api_method(api_method)

            # Get or create service instance
            service_instance = await self._get_service_instance(service_module, service_class)

            # Convert special parameters if metadata is provided
            if enum_metadata:
                parameters = self._convert_special_parameters(parameters, enum_metadata)

            # Add default session parameters if missing (only if parameter_mode allows)
            if self.parameter_mode != "required_only":
                parameters = self._add_default_session_params(parameters)
            else:
                # Only add required session parameters that are missing
                parameters = self._add_required_session_params(parameters)

            # Invoke the method
            method = getattr(service_instance, method_name)
            result = await method(**parameters)

            return {"success": True, "data": result}

        except (ImportError, AttributeError, ValueError) as e:
            logger.error(f"Error invoking API {api_method}: {e!s}")
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

    def _parse_api_method(self, api_method: str) -> tuple[str, str, str]:
        """Parse API method string into components.

        Args:
            api_method: API method string (e.g., "api_services.cashflow_service.CashflowService.get_account_settings")

        Returns:
            Tuple of (service_module, service_class, method_name)

        Raises:
            ValueError: If the API method format is invalid
        """
        parts = api_method.split(".")

        if len(parts) >= 4:
            # New format: service_module.service_class.method_name
            service_module = ".".join(parts[:-2])  # "api_services.cashflow_service"
            service_class = parts[-2]  # "CashflowService"
            method_name = parts[-1]  # "get_account_settings"

            return service_module, service_class, method_name
        else:
            raise ValueError(f"Invalid API method format: {api_method}")

    async def _get_service_instance(self, service_module: str, service_class: str) -> Any:
        """Get or create a service instance.

        Args:
            service_module: The module path (e.g., "api_services.cashflow_service")
            service_class: The service class name (e.g., "CashflowService")

        Returns:
            Service instance

        Raises:
            ImportError: If the service module cannot be imported
            AttributeError: If the service class cannot be found
        """
        if service_module not in self.service_instances:
            try:
                # Import the service module
                module = importlib.import_module(service_module)

                # Try to get the singleton instance first (lowercase with underscore)
                # e.g., SpendLimitsService -> spendlimits_service
                instance_name = "".join(
                    ["_" + c.lower() if c.isupper() and i > 0 else c.lower() for i, c in enumerate(service_class)]
                )

                try:
                    service_instance = getattr(module, instance_name)
                except AttributeError:
                    # Fallback: try to create an instance from the class
                    service_class_obj = getattr(module, service_class)
                    service_instance = service_class_obj()

                self.service_instances[service_module] = service_instance

            except (ImportError, AttributeError) as e:
                logger.error(f"Error importing service {service_module}: {e!s}")
                raise

        return self.service_instances[service_module]

    def _add_default_session_params(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Add default session parameters if missing.

        Args:
            parameters: Current parameters dictionary

        Returns:
            Parameters dictionary with default session parameters added
        """
        defaults: dict[str, str] = {}

        # Add defaults for missing parameters
        for key, value in defaults.items():
            if key not in parameters:
                parameters[key] = value

        return parameters

    def _add_required_session_params(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Add only required session parameters if missing.

        Args:
            parameters: Current parameters dictionary

        Returns:
            Parameters dictionary with required session parameters added
        """
        # Only add the most essential parameters
        required_defaults: dict[str, str] = {}

        # Add required defaults for missing parameters
        for key, value in required_defaults.items():
            if key not in parameters:
                parameters[key] = value

        return parameters

    def _convert_special_parameters(
        self, parameters: dict[str, Any], special_metadata: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Convert string parameters to special objects (enum, datetime, etc.) based on metadata.

        Args:
            parameters: Parameters dictionary to convert
            special_metadata: Metadata for special parameter types

        Returns:
            Parameters dictionary with converted special parameters
        """
        converted_params = parameters.copy()

        for param_name, param_info in special_metadata.items():
            if param_name in converted_params:
                param_value = converted_params[param_name]
                param_type = param_info.get("type")

                try:
                    if param_type == "enum":
                        enum_class_path = param_info.get("enum_class")
                        if enum_class_path:
                            # Import the enum class dynamically
                            module_path, class_name = enum_class_path.rsplit(".", 1)
                            module = importlib.import_module(module_path)
                            enum_class = getattr(module, class_name)

                            # Convert string value to enum
                            if isinstance(param_value, str):
                                # Try to find the enum value by name
                                for enum_value in enum_class:
                                    if param_value in (enum_value.name, enum_value.value):
                                        converted_params[param_name] = enum_value
                                        logger.info(
                                            f'Converted {param_name}="{param_value}" to {enum_class.__name__}.{enum_value.name}'
                                        )
                                        break
                                else:
                                    logger.error(
                                        f'Could not find enum value for {param_name}="{param_value}" in {enum_class.__name__}'
                                    )

                    elif param_type == "datetime":
                        if isinstance(param_value, str):
                            # Convert string to datetime object
                            # Try to parse the date string (assuming ISO format or YYYY-MM-DD)
                            try:
                                # First try ISO format
                                dt_obj = datetime.fromisoformat(param_value)
                            except ValueError:
                                # Try YYYY-MM-DD format
                                dt_obj = datetime.strptime(param_value, "%Y-%m-%d")

                            converted_params[param_name] = dt_obj
                            logger.info(f'Converted {param_name}="{param_value}" to datetime object: {dt_obj}')

                except (ImportError, AttributeError, ValueError) as e:
                    logger.error(f"Error converting {param_type} parameter {param_name}: {e!s}")

        # Handle nested dictionary parameters with special metadata
        for param_name, param_value in converted_params.items():
            if isinstance(param_value, dict) and "_special_metadata" in param_value:
                # Extract special metadata and remove it from the parameter
                nested_metadata = param_value.pop("_special_metadata")

                # Convert nested special parameters
                converted_params[param_name] = self._convert_nested_special_parameters(param_value, nested_metadata)

        return converted_params

    def _convert_nested_special_parameters(
        self, param_dict: dict[str, Any], nested_metadata: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Convert special parameters within a nested dictionary.

        Args:
            param_dict: Dictionary containing parameters to convert
            nested_metadata: Metadata for nested special parameter types

        Returns:
            Dictionary with converted nested special parameters
        """
        converted_dict = param_dict.copy()

        for field_name, field_metadata in nested_metadata.items():
            if field_name in converted_dict:
                field_value = converted_dict[field_name]
                field_type = field_metadata.get("type")

                try:
                    if field_type == "enum":
                        enum_class_path = field_metadata.get("enum_class")
                        if enum_class_path:
                            # Import the enum class dynamically
                            module_path, class_name = enum_class_path.rsplit(".", 1)
                            module = importlib.import_module(module_path)
                            enum_class = getattr(module, class_name)

                            # Convert string value to enum
                            if isinstance(field_value, str):
                                # Try to find the enum value by name
                                for enum_value in enum_class:
                                    if field_value in (enum_value.name, enum_value.value):
                                        converted_dict[field_name] = enum_value
                                        logger.info(
                                            f'Converted nested {field_name}="{field_value}" to {enum_class.__name__}.{enum_value.name}'
                                        )
                                        break
                                else:
                                    logger.error(
                                        f'Could not find enum value for nested {field_name}="{field_value}" in {enum_class.__name__}'
                                    )

                    elif field_type == "datetime":
                        if isinstance(field_value, str):
                            # Convert string to datetime object
                            try:
                                # First try ISO format
                                dt_obj = datetime.fromisoformat(field_value)
                            except ValueError:
                                # Try YYYY-MM-DD format
                                dt_obj = datetime.strptime(field_value, "%Y-%m-%d")

                            converted_dict[field_name] = dt_obj
                            logger.info(f'Converted nested {field_name}="{field_value}" to datetime object: {dt_obj}')

                except (ImportError, AttributeError, ValueError) as e:
                    logger.error(f"Error converting nested {field_type} parameter {field_name}: {e!s}")

        return converted_dict
