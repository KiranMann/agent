#!/usr/bin/env python3
"""
Parameter Generator Module

This module handles parameter combination generation based on binding rules and dynamic values.
It extracts parameter generation logic from the original io_recorder.py file.
"""

import importlib
import itertools
from datetime import datetime
from itertools import combinations as iter_combinations
from typing import Any

from common.logging.core import logger


class ParameterCombinationGenerator:
    """Generates parameter combinations based on binding rules and dynamic values."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the parameter combination generator.

        Args:
            config: Configuration dictionary containing parameter bindings,
                   dynamic value examples, parameter definitions, and generation config.
        """
        self.config = config
        self.parameter_bindings: dict[str, Any] = config.get("parameter_bindings", {})
        self.dynamic_value_examples: dict[str, Any] = config.get("dynamic_value_examples", {})
        self.parameter_definitions: dict[str, Any] = config.get("parameter_definitions", {})
        self.generation_config: dict[str, Any] = config.get("generation_config", {})
        self.parameter_mode: str = self.generation_config.get("parameter_mode", "all")

    def generate_combinations(self, api_method: str, api_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate all valid parameter combinations for an API method.

        Args:
            api_method: The API method name
            api_config: Configuration for the specific API method

        Returns:
            List of parameter combination dictionaries
        """
        combinations: list[dict[str, Any]] = []

        # Check if this API method uses parameter bindings
        parameter_binding = api_config.get("parameter_binding")

        if parameter_binding:
            # Handle single or multiple bindings
            bindings = parameter_binding if isinstance(parameter_binding, list) else [parameter_binding]

            # Get all valid combinations from bindings
            bound_combinations = self._get_bound_combinations(bindings)

            # Get additional parameter combinations
            additional_combinations = self._get_additional_combinations(api_config, api_method)

            # Cross-multiply bound and additional combinations
            for bound_combo in bound_combinations:
                for additional_combo in additional_combinations:
                    combined = {**bound_combo, **additional_combo}
                    combinations.append(combined)
        else:
            # No bindings - generate combinations from all parameters
            combinations = self._generate_simple_combinations(api_config)

        # Apply dynamic value generation
        combinations = self._apply_dynamic_values(combinations, api_config)

        # Filter parameters based on parameter_mode
        combinations = self._filter_parameters_by_mode(combinations)

        return combinations

    def _get_bound_combinations(self, binding_names: list[str]) -> list[dict[str, Any]]:
        """Get valid combinations from parameter bindings.

        Args:
            binding_names: List of binding names to process

        Returns:
            List of valid parameter combinations from bindings
        """
        all_combinations: list[dict[str, Any]] = []

        for binding_name in binding_names:
            binding_config = self.parameter_bindings.get(binding_name, {})
            valid_combinations = binding_config.get("valid_combinations", [])

            if not all_combinations:
                all_combinations = valid_combinations.copy()
            else:
                # Merge combinations from multiple bindings
                merged_combinations = []
                for existing_combo in all_combinations:
                    for new_combo in valid_combinations:
                        # Check if combinations are compatible
                        merged = {**existing_combo, **new_combo}
                        # Simple compatibility check - no conflicting values
                        if all(
                            existing_combo.get(k) == new_combo.get(k) for k in existing_combo.keys() & new_combo.keys()
                        ):
                            merged_combinations.append(merged)
                all_combinations = merged_combinations

        return all_combinations or [{}]

    def _get_additional_combinations(
        self,
        api_config: dict[str, Any],
        api_method: str,  # pylint: disable=unused-argument
    ) -> list[dict[str, Any]]:
        """Get combinations of additional parameters (beyond parameter bindings).

        Args:
            api_config: API configuration dictionary
            api_method: API method name (unused but kept for compatibility)

        Returns:
            List of additional parameter combinations
        """
        required_params: dict[str, Any] = {}
        optional_params: dict[str, Any] = {}

        for param_name, param_values in api_config.items():
            if param_name in ["parameter_binding", "dynamic"]:
                continue

            # Skip if parameter should be excluded based on mode
            if self._should_exclude_parameter(param_values):
                continue

            # Process parameter values
            if isinstance(param_values, list):
                if len(param_values) == 0 and param_name in self.parameter_definitions:
                    # Use values from parameter_definitions for reusable parameters
                    param_def = self.parameter_definitions.get(param_name, {})
                    possible_values = param_def.get("possible_values", [param_def.get("default", "default_value")])
                    param_values = possible_values

                # Handle list of dictionaries (complex parameter structures)
                if param_values and isinstance(param_values[0], dict):
                    # Process complex dictionary parameters
                    processed_values = self._process_dict_parameter_list(param_values)
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = processed_values
                    else:
                        required_params[param_name] = processed_values
                # Check if this parameter is optional
                elif self._is_optional_parameter(param_values):
                    optional_params[param_name] = param_values
                else:
                    required_params[param_name] = param_values
            elif isinstance(param_values, dict):
                # Handle special parameter types (e.g., enums)
                if param_values.get("type") == "enum":
                    # Initialize enum objects directly
                    enum_objects = self._create_enum_objects(param_values)

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = enum_objects
                    else:
                        required_params[param_name] = enum_objects
                elif param_values.get("type") == "datetime":
                    # Initialize datetime objects directly
                    datetime_objects = self._create_datetime_objects(param_values)

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = datetime_objects
                    else:
                        required_params[param_name] = datetime_objects
                elif param_values.get("type") == "bool":
                    # Handle boolean parameters
                    bool_values = param_values.get("values", [True, False])

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = bool_values
                    else:
                        required_params[param_name] = bool_values
                elif param_values.get("type") == "dict":
                    # Handle complex dictionary parameters with nested types
                    dict_objects = self._create_dict_objects(param_values)

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = dict_objects
                    else:
                        required_params[param_name] = dict_objects
                else:
                    # Handle other dict-based parameter configurations
                    values = param_values.get("values", [param_values])

                    # If values is empty, check parameter_definitions
                    if len(values) == 0 and param_name in self.parameter_definitions:
                        param_def = self.parameter_definitions.get(param_name, {})
                        values = param_def.get(
                            "possible_values",
                            [param_def.get("default", "default_value")],
                        )

                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = values
                    else:
                        required_params[param_name] = values
            # Single value parameters
            elif self._is_optional_parameter(param_values):
                optional_params[param_name] = [param_values]
            else:
                required_params[param_name] = [param_values]

        # Generate combinations for required parameters
        required_combinations = self._generate_param_combinations(required_params)

        # Generate combinations for optional parameters (including combinations without them)
        optional_combinations = self._generate_optional_param_combinations(optional_params)

        # Cross-multiply required and optional combinations
        all_combinations = []
        for req_combo in required_combinations:
            for opt_combo in optional_combinations:
                combined = {**req_combo, **opt_combo}
                all_combinations.append(combined)

        return all_combinations

    def _process_dict_parameter_list(self, param_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process a list of dictionary parameters, expanding nested enum/special types.

        Args:
            param_list: List of parameter dictionaries to process

        Returns:
            List of processed parameter dictionaries
        """
        processed_list = []

        for param_dict in param_list:
            # Generate all combinations for this dictionary
            dict_combinations = self._generate_dict_combinations(param_dict)
            processed_list.extend(dict_combinations)

        return processed_list

    def _generate_dict_combinations(self, param_dict: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate all combinations for a dictionary parameter with nested special types.

        Args:
            param_dict: Dictionary parameter to generate combinations for

        Returns:
            List of dictionary combinations
        """
        # Extract all keys and their possible values
        keys = []
        value_lists = []
        special_metadata = {}

        for key, value in param_dict.items():
            keys.append(key)

            if isinstance(value, dict) and value.get("type"):
                # Handle special types (enum, datetime, etc.)
                param_type = value.get("type")
                if param_type == "enum":
                    enum_values = value.get("values", [])
                    value_lists.append(enum_values)
                    special_metadata[key] = {
                        "type": "enum",
                        "enum_class": value.get("enum_class"),
                    }
                elif param_type == "datetime":
                    datetime_values = value.get("values", [])
                    value_lists.append(datetime_values)
                    special_metadata[key] = {"type": "datetime"}
                else:
                    # Other special types
                    values = value.get("values", [value])
                    value_lists.append(values)
            elif isinstance(value, list):
                # Regular list of values
                value_lists.append(value)
            else:
                # Single value
                value_lists.append([value])

        # Generate all combinations
        combinations = []
        for combo in itertools.product(*value_lists):
            combination_dict = dict(zip(keys, combo, strict=False))

            # Store special metadata for later conversion
            if special_metadata:
                combination_dict["_special_metadata"] = special_metadata

            combinations.append(combination_dict)

        return combinations

    def _generate_simple_combinations(self, api_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate simple parameter combinations when no bindings are used.

        Args:
            api_config: API configuration dictionary

        Returns:
            List of parameter combinations
        """
        required_params: dict[str, Any] = {}
        optional_params: dict[str, Any] = {}

        for param_name, param_values in api_config.items():
            if param_name in ["parameter_binding", "dynamic"]:
                continue

            # Skip if parameter should be excluded based on mode
            if self._should_exclude_parameter(param_values):
                continue

            # Process parameter values and separate required vs optional
            if isinstance(param_values, list):
                if len(param_values) == 0 and param_name in self.parameter_definitions:
                    # Use values from parameter_definitions for reusable parameters
                    param_def = self.parameter_definitions.get(param_name, {})
                    possible_values = param_def.get("possible_values", [param_def.get("default", "default_value")])
                    param_values = possible_values

                # Check if this parameter is optional
                if self._is_optional_parameter(param_values):
                    optional_params[param_name] = param_values
                else:
                    required_params[param_name] = param_values
            elif isinstance(param_values, dict):
                # Handle special parameter types (e.g., enums, datetime)
                if param_values.get("type") == "enum":
                    # Create enum objects directly
                    enum_objects = self._create_enum_objects(param_values)

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = enum_objects
                    else:
                        required_params[param_name] = enum_objects
                elif param_values.get("type") == "datetime":
                    # Create datetime objects directly
                    datetime_objects = self._create_datetime_objects(param_values)

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = datetime_objects
                    else:
                        required_params[param_name] = datetime_objects
                elif param_values.get("type") == "bool":
                    # Handle boolean parameters
                    bool_values = param_values.get("values", [True, False])

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = bool_values
                    else:
                        required_params[param_name] = bool_values
                else:
                    # Handle other dict-based parameter configurations
                    values = param_values.get("values", [param_values])

                    # Check if this parameter is optional
                    if self._is_optional_parameter(param_values):
                        optional_params[param_name] = values
                    else:
                        required_params[param_name] = values
            # Single value parameters
            elif self._is_optional_parameter(param_values):
                optional_params[param_name] = [param_values]
            else:
                required_params[param_name] = [param_values]

        # Generate combinations for required parameters
        required_combinations = self._generate_param_combinations(required_params)

        # Generate combinations for optional parameters (including combinations without them)
        optional_combinations = self._generate_optional_param_combinations(optional_params)

        # Cross-multiply required and optional combinations
        all_combinations = []
        for req_combo in required_combinations:
            for opt_combo in optional_combinations:
                combined = {**req_combo, **opt_combo}
                all_combinations.append(combined)

        return all_combinations

    def _should_exclude_parameter(self, param_config: dict[str, Any] | None = None) -> bool:
        """Determine if a parameter should be excluded based on parameter_mode.

        Args:
            param_config: Parameter configuration dictionary

        Returns:
            True if parameter should be excluded, False otherwise
        """
        if self.parameter_mode == "all":
            return False

        if self.parameter_mode == "required_only":
            # Check if parameter has is_optional field set to True
            if param_config and isinstance(param_config, dict):
                is_optional = param_config.get("is_optional", False)
                if is_optional:
                    return True

        return False

    def _apply_dynamic_values(
        self, combinations: list[dict[str, Any]], api_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Apply dynamic value generation to combinations.

        Args:
            combinations: List of parameter combinations
            api_config: API configuration dictionary

        Returns:
            Updated combinations with dynamic values applied
        """
        # For now, just add default values for dynamic parameters
        # In a full implementation, this would call the source APIs

        for combination in combinations:
            for param_name, param_config in api_config.items():
                if isinstance(param_config, dict) and param_config.get("dynamic"):
                    dynamic_name = param_config["dynamic"]
                    dynamic_config = self.dynamic_value_examples.get(dynamic_name, {})
                    fallback_values = dynamic_config.get("fallback", ["default_value"])
                    combination[param_name] = fallback_values[0]

        return combinations

    def _filter_parameters_by_mode(self, combinations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter parameters in combinations based on parameter_mode.

        Args:
            combinations: List of parameter combinations to filter

        Returns:
            Filtered combinations
        """
        if self.parameter_mode == "all":
            return combinations

        filtered_combinations = []

        for combination in combinations:
            filtered_combination = {}

            for param_name, param_value in combination.items():
                if not self._should_exclude_parameter():
                    filtered_combination[param_name] = param_value

            filtered_combinations.append(filtered_combination)

        return filtered_combinations

    def _is_optional_parameter(self, param_config: dict[str, Any] | None = None) -> bool:
        """Check if a parameter is marked as optional.

        Args:
            param_config: Parameter configuration dictionary

        Returns:
            True if parameter is optional, False otherwise
        """
        # Check if parameter has is_optional field set to True
        if param_config and isinstance(param_config, dict):
            is_optional = param_config.get("is_optional", False)
            return is_optional

        return False

    def _generate_param_combinations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate all combinations for a set of parameters.

        Args:
            params: Dictionary of parameters and their possible values

        Returns:
            List of parameter combinations
        """
        if not params:
            return [{}]

        param_names = list(params.keys())
        param_value_lists = []

        # Process each parameter to extract values
        for param_name in param_names:
            param_config = params[param_name]

            if isinstance(param_config, dict) and "values" in param_config:
                # Handle enum or other special parameter types
                # Extract the actual values from the configuration
                param_value_lists.append(param_config["values"])
            elif isinstance(param_config, list):
                # Handle regular list of values
                param_value_lists.append(param_config)
            else:
                # Handle single values
                param_value_lists.append([param_config])

        combinations = []
        for combo in itertools.product(*param_value_lists):
            combination = dict(zip(param_names, combo, strict=False))
            combinations.append(combination)

        return combinations

    def _generate_optional_param_combinations(self, optional_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate combinations for optional parameters, including combinations with and without them.

        Args:
            optional_params: Dictionary of optional parameters and their values

        Returns:
            List of optional parameter combinations
        """
        if not optional_params:
            return [{}]

        param_names = list(optional_params.keys())

        # Extract actual values from each parameter (handling enum metadata)
        param_value_lists = []
        for param_name in param_names:
            param_config = optional_params[param_name]

            if isinstance(param_config, dict) and "values" in param_config:
                # Handle enum or other special parameter types
                param_value_lists.append(param_config["values"])
            elif isinstance(param_config, list):
                # Handle regular list of values
                param_value_lists.append(param_config)
            else:
                # Handle single values
                param_value_lists.append([param_config])

        # Generate the powerset of optional parameters (all possible subsets)
        all_combinations: list[dict[str, Any]] = []

        # Include empty combination (no optional parameters) - this is crucial for valid inputs without optional params
        all_combinations.append({})

        # For each possible subset size (1 to all parameters)
        for subset_size in range(1, len(param_names) + 1):
            # Get all possible subsets of this size
            for param_subset in iter_combinations(param_names, subset_size):
                # Get the corresponding value lists for this subset
                subset_indices = [param_names.index(param) for param in param_subset]
                subset_values = [param_value_lists[i] for i in subset_indices]

                # Generate all combinations for this subset
                for value_combo in itertools.product(*subset_values):
                    combination = dict(zip(param_subset, value_combo, strict=False))
                    all_combinations.append(combination)

        return all_combinations

    def _create_enum_objects(self, param_config: dict[str, Any]) -> list[Any]:
        """Create enum objects from parameter configuration.

        Args:
            param_config: Parameter configuration containing enum information

        Returns:
            List of enum objects or string values as fallback
        """
        enum_objects = []
        enum_class_path = param_config.get("enum_class")
        enum_values = param_config.get("values", [])

        if enum_class_path:
            try:
                # Import the enum class dynamically
                module_path, class_name = enum_class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                enum_class = getattr(module, class_name)

                # Create enum objects for each value
                for value_name in enum_values:
                    for enum_value in enum_class:
                        if enum_value.name == value_name or enum_value.value == value_name:
                            enum_objects.append(enum_value)
                            logger.info(f"Created enum object: {enum_class.__name__}.{enum_value.name}")
                            break
                    else:
                        logger.error(f'Could not find enum value "{value_name}" in {enum_class.__name__}')

            except (ImportError, AttributeError) as e:
                logger.error(f"Error importing enum class {enum_class_path}: {e!s}")
                # Fallback to string values
                enum_objects = enum_values
        else:
            # No enum class specified, use string values
            enum_objects = enum_values

        return enum_objects

    def _create_datetime_objects(self, param_config: dict[str, Any]) -> list[datetime]:
        """Create datetime objects from parameter configuration.

        Args:
            param_config: Parameter configuration containing datetime information

        Returns:
            List of datetime objects or string values as fallback
        """
        datetime_objects = []
        datetime_values = param_config.get("values", [])

        for datetime_str in datetime_values:
            try:
                # Try to parse the date string (assuming ISO format or YYYY-MM-DD)
                try:
                    # First try ISO format
                    dt_obj = datetime.fromisoformat(datetime_str)
                except ValueError:
                    # Try YYYY-MM-DD format
                    dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d")

                datetime_objects.append(dt_obj)
                logger.info(f"Created datetime object: {dt_obj}")

            except ValueError as e:
                logger.error(f"Error parsing datetime string '{datetime_str}': {e!s}")
                # Fallback to string value
                datetime_objects.append(datetime_str)

        return datetime_objects

    def _create_dict_objects(self, param_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Create dictionary objects from parameter configuration with nested enum and datetime types.

        Args:
            param_config: Parameter configuration containing dictionary information

        Returns:
            List of dictionary objects
        """
        dict_objects = []
        dict_values = param_config.get("values", [])

        for dict_spec in dict_values:
            # Process each dictionary specification
            if isinstance(dict_spec, dict):
                # Generate all combinations for this dictionary specification
                dict_combinations = self._generate_dict_combinations(dict_spec)
                dict_objects.extend(dict_combinations)
            else:
                # Fallback for non-dict specifications
                dict_objects.append(dict_spec)

        return dict_objects
