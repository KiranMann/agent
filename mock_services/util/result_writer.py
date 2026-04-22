#!/usr/bin/env python3
"""
Result Writer Module

This module handles JSON output writing and result formatting.
It extracts result writing logic from the original io_recorder.py file.
"""

# pylint: disable=inconsistent-quotes
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from common.logging.core import logger


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime and enum objects."""

    def default(self, o: Any) -> Any:
        """Convert non-serializable objects to JSON-serializable format.

        Args:
            o: Object to convert

        Returns:
            JSON-serializable representation of the object
        """
        if isinstance(o, datetime):
            return o.isoformat()
        elif isinstance(o, Enum):
            return o.value
        return super().default(o)


class ResultWriter:
    """Handles writing API input/output results to JSON files."""

    def __init__(self, output_path: str) -> None:
        """Initialize the result writer.

        Args:
            output_path: Path where the JSON results will be written
        """
        self.output_path = Path(output_path)
        self.results: dict[str, dict[str, Any]] = {"APIs": {}}

    def initialize_api_result(self, api_key: str) -> None:
        """Initialize result structure for a specific API.

        Args:
            api_key: The API key to initialize results for
        """
        self.results["APIs"][api_key] = {"io_array": []}

    def add_io_pair(
        self,
        api_key: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
    ) -> None:
        """Add an input/output pair to the results.

        Args:
            api_key: The API key to add the pair to
            input_params: Input parameters used for the API call
            output_result: Output result from the API call
        """
        if api_key not in self.results["APIs"]:
            self.initialize_api_result(api_key)

        # Create the I/O pair
        io_pair = {
            "input": input_params,
            "output": (
                output_result.get("data")
                if output_result.get("success")
                else {"error": output_result.get("error", "Unknown error")}
            ),
        }

        self.results["APIs"][api_key]["io_array"].append(io_pair)

    def get_api_key_from_method(self, api_method: str) -> str:
        """Convert API method name to the format expected in output JSON.

        Args:
            api_method: Full API method name (e.g., "api_services.cashflow_service.CashflowService.get_account_settings")

        Returns:
            Formatted API key for the results structure
        """
        # With the new hierarchical structure, the API method already contains
        # the correct format: "api_services.cashflow_service.CashflowService.get_account_settings"
        # We need to convert it to: "api_services.CashflowService.get_account_settings"
        parts = api_method.split(".")
        if len(parts) >= 4:
            # Remove the service module part and keep module.class.method format
            service_module_base = parts[0]  # "api_services"
            service_class = parts[-2]  # "CashflowService"
            method_name = parts[-1]  # "get_account_settings"
            return f"{service_module_base}.{service_class}.{method_name}"
        return api_method

    def save_results(self) -> None:
        """Save results to the JSON output file.

        Raises:
            IOError: If there's an error writing the file
            OSError: If there's a system-level error writing the file
        """
        try:
            # Create output directory if it doesn't exist
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write results to JSON file
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2, ensure_ascii=False, cls=CustomJSONEncoder)

            logger.info(f"Results saved to {self.output_path}")

        except OSError as e:
            logger.error(f"Error saving results to {self.output_path}: {e!s}")
            raise

    def get_results_summary(self) -> dict[str, Any]:
        """Get a summary of the current results.

        Returns:
            Dictionary containing summary information about the results
        """
        total_apis = len(self.results["APIs"])
        total_io_pairs = sum(len(api_data["io_array"]) for api_data in self.results["APIs"].values())

        # Count successful vs failed calls
        successful_calls = 0
        failed_calls = 0

        for api_data in self.results["APIs"].values():
            for io_pair in api_data["io_array"]:
                output = io_pair.get("output", {})
                if isinstance(output, dict) and "error" in output:
                    failed_calls += 1
                else:
                    successful_calls += 1

        # Get API method statistics
        api_stats = {}
        for api_key, api_data in self.results["APIs"].items():
            io_count = len(api_data["io_array"])
            success_count = sum(
                1
                for io_pair in api_data["io_array"]
                if not (isinstance(io_pair.get("output", {}), dict) and "error" in io_pair.get("output", {}))
            )
            failure_count = io_count - success_count

            api_stats[api_key] = {
                "total_calls": io_count,
                "successful_calls": success_count,
                "failed_calls": failure_count,
                "success_rate": (success_count / io_count * 100) if io_count > 0 else 0,
            }

        return {
            "output_path": str(self.output_path),
            "total_apis": total_apis,
            "total_io_pairs": total_io_pairs,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "overall_success_rate": ((successful_calls / total_io_pairs * 100) if total_io_pairs > 0 else 0),
            "api_statistics": api_stats,
        }

    def clear_results(self) -> None:
        """Clear all stored results."""
        self.results = {"APIs": {}}

    def get_results(self) -> dict[str, dict[str, Any]]:
        """Get the current results dictionary.

        Returns:
            Current results dictionary
        """
        return self.results

    def load_existing_results(self) -> bool:
        """Load existing results from the output file if it exists.

        Returns:
            True if results were loaded successfully, False otherwise
        """
        if not self.output_path.exists():
            logger.info(f"No existing results file found at {self.output_path}")
            return False

        try:
            with open(self.output_path, encoding="utf-8") as f:
                existing_results = json.load(f)

            # Validate the structure
            if isinstance(existing_results, dict) and "APIs" in existing_results:
                self.results = existing_results
                logger.info(f"Loaded existing results from {self.output_path}")
                return True
            else:
                logger.warning(f"Invalid results structure in {self.output_path}, starting fresh")
                return False

        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Error loading existing results from {self.output_path}: {e!s}")
            return False

    def merge_results(self, other_results: dict[str, dict[str, Any]]) -> None:
        """Merge results from another results dictionary.

        Args:
            other_results: Results dictionary to merge in
        """
        if not isinstance(other_results, dict) or "APIs" not in other_results:
            logger.warning("Invalid results structure for merging")
            return

        for api_key, api_data in other_results["APIs"].items():
            if api_key not in self.results["APIs"]:
                self.results["APIs"][api_key] = {"io_array": []}

            # Merge the io_array
            if isinstance(api_data, dict) and "io_array" in api_data:
                self.results["APIs"][api_key]["io_array"].extend(api_data["io_array"])

        logger.info(f"Merged results for {len(other_results['APIs'])} APIs")

    def export_results_for_api(self, api_key: str, export_path: str) -> bool:
        """Export results for a specific API to a separate file.

        Args:
            api_key: The API key to export results for
            export_path: Path to export the results to

        Returns:
            True if export was successful, False otherwise
        """
        if api_key not in self.results["APIs"]:
            logger.error(f"API key '{api_key}' not found in results")
            return False

        try:
            export_data = {
                "API": api_key,
                "io_array": self.results["APIs"][api_key]["io_array"],
            }

            export_file = Path(export_path)
            export_file.parent.mkdir(parents=True, exist_ok=True)

            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, cls=CustomJSONEncoder)

            logger.info(f"Exported results for API '{api_key}' to {export_path}")
            return True

        except OSError as e:
            logger.error(f"Error exporting results for API '{api_key}': {e!s}")
            return False
