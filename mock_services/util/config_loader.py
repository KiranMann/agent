#!/usr/bin/env python3
"""
Configuration Loader Module

This module handles YAML configuration loading and validation.
It extracts configuration loading logic from the original io_recorder.py file.
"""

from pathlib import Path
from typing import Any

import yaml

from common.logging.core import logger


class ConfigurationLoader:
    """Handles loading and processing of YAML configuration files."""

    def __init__(self, config_path: str) -> None:
        """Initialize the configuration loader.

        Args:
            config_path: Path to the YAML configuration file

        Raises:
            FileNotFoundError: If the configuration file doesn't exist
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        self.config: dict[str, Any] | None = None

    def load_config(self) -> dict[str, Any]:
        """Load the YAML configuration file.

        Returns:
            Configuration dictionary

        Raises:
            IOError: If there's an error reading the file
            yaml.YAMLError: If there's an error parsing the YAML
        """
        try:
            with open(self.config_path, encoding="utf-8") as f:
                self.config = yaml.safe_load(f)

            if self.config is None:
                self.config = {}

            logger.info(f"Loaded configuration from {self.config_path}")
            return self.config

        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Error loading configuration from {self.config_path}: {e!s}")
            raise

    def get_config(self) -> dict[str, Any]:
        """Get the loaded configuration.

        Returns:
            Configuration dictionary

        Raises:
            RuntimeError: If configuration hasn't been loaded yet
        """
        if self.config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self.config

    def extract_api_methods_from_config(self) -> dict[str, Any]:
        """Extract API methods from the hierarchical configuration structure.

        Returns:
            Dictionary mapping API method names to their configurations

        Raises:
            RuntimeError: If configuration hasn't been loaded yet
        """
        if self.config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")

        api_methods = {}
        service_modules = self.config.get("service_modules", {})

        for service_module, module_config in service_modules.items():
            service_classes = module_config.get("service_classes", {})

            for service_class, class_config in service_classes.items():
                methods = class_config.get("methods", {})

                for method_name, method_config in methods.items():
                    # Construct the full API method name
                    api_method = f"{service_module}.{service_class}.{method_name}"
                    api_methods[api_method] = method_config

        return api_methods

    def get_parameter_bindings(self) -> dict[str, Any]:
        """Get parameter bindings from configuration.

        Returns:
            Parameter bindings dictionary
        """
        if self.config is None:
            return {}
        return self.config.get("parameter_bindings", {})

    def get_dynamic_value_examples(self) -> dict[str, Any]:
        """Get dynamic value examples from configuration.

        Returns:
            Dynamic value examples dictionary
        """
        if self.config is None:
            return {}
        return self.config.get("dynamic_value_examples", {})

    def get_parameter_definitions(self) -> dict[str, Any]:
        """Get parameter definitions from configuration.

        Returns:
            Parameter definitions dictionary
        """
        if self.config is None:
            return {}
        return self.config.get("parameter_definitions", {})

    def get_generation_config(self) -> dict[str, Any]:
        """Get generation configuration settings.

        Returns:
            Generation configuration dictionary
        """
        if self.config is None:
            return {}
        return self.config.get("generation_config", {})

    def get_parameter_mode(self) -> str:
        """Get the parameter mode setting.

        Returns:
            Parameter mode string ("all", "required_only", or "custom")
        """
        generation_config = self.get_generation_config()
        return generation_config.get("parameter_mode", "all")

    def filter_api_methods(
        self,
        api_methods: dict[str, Any],
        include_api_methods: list[str] | None = None,
        exclude_api_methods: list[str] | None = None,
    ) -> dict[str, Any]:
        """Filter API methods based on include/exclude lists.

        Args:
            api_methods: Dictionary of API methods to filter
            include_api_methods: List of API methods to include (if specified, only these will be included)
            exclude_api_methods: List of API methods to exclude

        Returns:
            Filtered dictionary of API methods
        """
        filtered_methods = {}

        for api_method, api_config in api_methods.items():
            # If include list is specified, only include methods in the list
            if include_api_methods:
                if api_method in include_api_methods:
                    filtered_methods[api_method] = api_config
                    logger.info(f"✅ Including API method: {api_method}")
                else:
                    logger.info(f"⏭️  Skipping API method (not in include list): {api_method}")
                continue

            # If exclude list is specified, exclude methods in the list
            if exclude_api_methods:
                if api_method in exclude_api_methods:
                    logger.info(f"🚫 Excluding API method: {api_method}")
                    continue
                else:
                    filtered_methods[api_method] = api_config
                    logger.info(f"✅ Including API method: {api_method}")
            else:
                # No filtering - include all methods
                filtered_methods[api_method] = api_config

        return filtered_methods

    def validate_config(self) -> bool:
        """Validate the loaded configuration structure.

        Returns:
            True if configuration is valid, False otherwise
        """
        if self.config is None:
            logger.error("Configuration not loaded")
            return False

        # Check for required top-level sections
        required_sections = ["service_modules"]
        for section in required_sections:
            if section not in self.config:
                logger.error(f"Missing required configuration section: {section}")
                return False

        # Validate service modules structure
        service_modules = self.config.get("service_modules", {})
        if not isinstance(service_modules, dict):
            logger.error("service_modules must be a dictionary")
            return False

        for service_module, module_config in service_modules.items():
            if not isinstance(module_config, dict):
                logger.error(f"Configuration for service module '{service_module}' must be a dictionary")
                return False

            service_classes = module_config.get("service_classes", {})
            if not isinstance(service_classes, dict):
                logger.error(f"service_classes in '{service_module}' must be a dictionary")
                return False

            for service_class, class_config in service_classes.items():
                if not isinstance(class_config, dict):
                    logger.error(f"Configuration for service class '{service_class}' must be a dictionary")
                    return False

                methods = class_config.get("methods", {})
                if not isinstance(methods, dict):
                    logger.error(f"methods in '{service_class}' must be a dictionary")
                    return False

        logger.info("Configuration validation passed")
        return True

    def get_config_summary(self) -> dict[str, Any]:
        """Get a summary of the loaded configuration.

        Returns:
            Dictionary containing configuration summary information
        """
        if self.config is None:
            return {"status": "not_loaded"}

        api_methods = self.extract_api_methods_from_config()

        summary = {
            "status": "loaded",
            "config_path": str(self.config_path),
            "total_api_methods": len(api_methods),
            "parameter_mode": self.get_parameter_mode(),
            "has_parameter_bindings": bool(self.get_parameter_bindings()),
            "has_dynamic_value_examples": bool(self.get_dynamic_value_examples()),
            "has_parameter_definitions": bool(self.get_parameter_definitions()),
            "service_modules": list(self.config.get("service_modules", {}).keys()),
        }

        # Count methods per service module
        service_method_counts = {}
        service_modules = self.config.get("service_modules", {})
        for service_module, module_config in service_modules.items():
            method_count = 0
            service_classes = module_config.get("service_classes", {})
            for class_config in service_classes.values():
                methods = class_config.get("methods", {})
                method_count += len(methods)
            service_method_counts[service_module] = method_count

        summary["service_method_counts"] = service_method_counts

        return summary
