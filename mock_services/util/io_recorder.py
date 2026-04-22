#!/usr/bin/env python3
"""
IO Recorder Script (Refactored)

This script reads the API methods configuration YAML file, generates parameter combinations
based on binding rules and dynamic values, invokes the APIs, and records input/output pairs
in a JSON file for mock data generation.

This refactored version uses modular components for better maintainability and testability:
- ParameterCombinationGenerator: Handles parameter combination generation
- APIInvoker: Handles API invocation logic
- ConfigurationLoader: Handles YAML configuration loading
- ResultWriter: Handles JSON output writing

Key Updates:
- Respects optional_parameters configuration to exclude optional params when parameter_mode is "required_only"
- Supports parameter_mode setting: "all", "required_only", "custom"
- Modular architecture for improved maintainability and testability
- Comprehensive type hints for better code documentation

Usage:
    python io_recorder.py --input mock_services/util/api_methods_config_updated.yaml --output api_io_data.json
"""

# pylint: disable=inconsistent-quotes
import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from common.logging.core import logger
from mock_services.util.api_invoker import APIInvoker
from mock_services.util.config_loader import ConfigurationLoader
from mock_services.util.parameter_generator import ParameterCombinationGenerator
from mock_services.util.result_writer import ResultWriter


class IORecorder:
    """Main class for recording API input/output pairs using modular components."""

    def __init__(
        self,
        config_path: str,
        output_path: str,
        include_api_methods: list[str] | None = None,
        exclude_api_methods: list[str] | None = None,
    ) -> None:
        """Initialize the IO recorder with modular components.

        Args:
            config_path: Path to the YAML configuration file
            output_path: Path to the output JSON file
            include_api_methods: Optional list of API methods to include
            exclude_api_methods: Optional list of API methods to exclude
        """
        self.config_path = config_path
        self.output_path = output_path
        self.include_api_methods = include_api_methods or []
        self.exclude_api_methods = exclude_api_methods or []

        # Initialize modular components
        self.config_loader: ConfigurationLoader | None = None
        self.combination_generator: ParameterCombinationGenerator | None = None
        self.api_invoker: APIInvoker | None = None
        self.result_writer: ResultWriter | None = None

    async def run(self) -> None:
        """Main execution method."""
        start_time = time.time()
        logger.info(f"🚀 Starting IO recording from {self.config_path}")
        logger.info(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Load configuration
        config_start = time.time()
        await self._initialize_components()
        config_time = time.time() - config_start
        logger.info(f"📋 Components initialized in {config_time:.3f} seconds")

        # Process API methods
        processing_start = time.time()
        await self._process_all_api_methods()
        processing_time = time.time() - processing_start
        logger.info(f"🔄 All API methods processed in {processing_time:.3f} seconds")

        # Save results
        save_start = time.time()
        if self.result_writer:
            self.result_writer.save_results()
        save_time = time.time() - save_start
        logger.info(f"💾 Results saved in {save_time:.3f} seconds")

        # Calculate total time and show summary
        total_time = time.time() - start_time
        await self._log_completion_summary(total_time, config_time, processing_time, save_time)

    async def _initialize_components(self) -> None:
        """Initialize all modular components."""
        # Initialize configuration loader
        self.config_loader = ConfigurationLoader(self.config_path)
        config = self.config_loader.load_config()

        # Validate configuration
        if not self.config_loader.validate_config():
            raise ValueError("Configuration validation failed")

        # Initialize parameter combination generator
        self.combination_generator = ParameterCombinationGenerator(config)

        # Initialize API invoker with parameter mode
        parameter_mode = self.config_loader.get_parameter_mode()
        self.api_invoker = APIInvoker(parameter_mode)

        # Initialize result writer
        self.result_writer = ResultWriter(self.output_path)

        logger.info("⚙️  All components initialized successfully")

    async def _process_all_api_methods(self) -> None:
        """Process all API methods from configuration."""
        if not self.config_loader:
            raise RuntimeError("Configuration loader not initialized")

        # Extract API methods from configuration
        api_methods = self.config_loader.extract_api_methods_from_config()

        # Apply filtering based on include/exclude lists
        filtered_api_methods = self.config_loader.filter_api_methods(
            api_methods, self.include_api_methods, self.exclude_api_methods
        )

        logger.info(f"🔄 Processing {len(filtered_api_methods)} API methods...")
        if self.include_api_methods:
            logger.info(f"📋 Including only: {', '.join(self.include_api_methods)}")
        if self.exclude_api_methods:
            logger.info(f"🚫 Excluding: {', '.join(self.exclude_api_methods)}")

        # Process each API method
        for i, (api_method, api_config) in enumerate(filtered_api_methods.items(), 1):
            method_start = time.time()
            logger.info(f"📡 [{i}/{len(filtered_api_methods)}] Processing API method: {api_method}")
            await self._process_api_method(api_method, api_config)
            method_time = time.time() - method_start
            logger.info(f"✅ [{i}/{len(filtered_api_methods)}] Completed {api_method} in {method_time:.3f} seconds")

    async def _process_api_method(self, api_method: str, api_config: dict[str, Any]) -> None:
        """Process a single API method.

        Args:
            api_method: The API method name
            api_config: Configuration for the API method
        """
        try:
            if not self.combination_generator:
                raise RuntimeError("Parameter combination generator not initialized")
            if not self.api_invoker:
                raise RuntimeError("API invoker not initialized")
            if not self.result_writer:
                raise RuntimeError("Result writer not initialized")

            # Generate parameter combinations
            combinations = self.combination_generator.generate_combinations(api_method, api_config)
            logger.info(f"Generated {len(combinations)} combinations for {api_method}")

            # Extract special parameter metadata from API configuration
            special_metadata = self._extract_special_metadata(api_config)

            # Get API key for results
            api_key = self.result_writer.get_api_key_from_method(api_method)
            self.result_writer.initialize_api_result(api_key)

            # Process each combination
            for i, combination in enumerate(combinations):
                logger.info(f"Processing combination {i + 1}/{len(combinations)} for {api_method}")
                logger.info(f"Parameters: {combination}")

                # Invoke API with special parameter metadata
                result = await self.api_invoker.invoke_api(api_method, combination, special_metadata)

                # Add input/output pair to results
                self.result_writer.add_io_pair(api_key, combination, result)

        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"Error processing API method {api_method}: {e!s}")
            # Continue with next API method

    def _extract_special_metadata(self, api_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Extract special parameter metadata (enum, datetime, etc.) from API configuration.

        Args:
            api_config: API configuration dictionary

        Returns:
            Dictionary containing special parameter metadata
        """
        special_metadata = {}

        for param_name, param_config in api_config.items():
            if isinstance(param_config, dict) and param_config.get("type"):
                param_type = param_config.get("type")

                if param_type == "enum":
                    special_metadata[param_name] = {
                        "type": "enum",
                        "enum_class": param_config.get("enum_class"),
                        "values": param_config.get("values", []),
                    }
                elif param_type == "datetime":
                    special_metadata[param_name] = {
                        "type": "datetime",
                        "values": param_config.get("values", []),
                    }

        return special_metadata

    async def _log_completion_summary(
        self,
        total_time: float,
        config_time: float,
        processing_time: float,
        save_time: float,
    ) -> None:
        """Log completion summary with performance metrics.

        Args:
            total_time: Total execution time
            config_time: Configuration loading time
            processing_time: API processing time
            save_time: Results saving time
        """
        logger.info("🏁 IO recording completed successfully!")
        logger.info(f"⏰ End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"⏱️  Total execution time: {total_time:.3f} seconds")
        logger.info("📊 Performance breakdown:")
        logger.info(f"   - Component initialization: {config_time:.3f}s ({config_time / total_time * 100:.1f}%)")
        logger.info(f"   - API processing: {processing_time:.3f}s ({processing_time / total_time * 100:.1f}%)")
        logger.info(f"   - Results saving: {save_time:.3f}s ({save_time / total_time * 100:.1f}%)")
        logger.info(f"📁 Results saved to: {self.output_path}")

        # Log results summary
        if self.result_writer:
            summary = self.result_writer.get_results_summary()
            logger.info("📈 Results Summary:")
            logger.info(f"   - Total APIs processed: {summary['total_apis']}")
            logger.info(f"   - Total I/O pairs generated: {summary['total_io_pairs']}")
            logger.info(f"   - Successful calls: {summary['successful_calls']}")
            logger.info(f"   - Failed calls: {summary['failed_calls']}")
            logger.info(f"   - Overall success rate: {summary['overall_success_rate']:.1f}%")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Record API input/output pairs from configuration")
    parser.add_argument("--input", required=True, help="Path to the YAML configuration file")
    parser.add_argument("--output", required=True, help="Path to the output JSON file")
    parser.add_argument(
        "--include-api-methods",
        nargs="+",
        help="List of specific API methods to include (e.g., api_services.billhub_service.get_predicted_bills)",
    )
    parser.add_argument(
        "--exclude-api-methods",
        nargs="+",
        help="List of specific API methods to exclude (e.g., api_services.spendlimits_service.get_category_transactions)",
    )

    args = parser.parse_args()

    # Validate input file exists
    if not Path(args.input).exists():
        logger.error(f"Input file does not exist: {args.input}")
        return

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Run the recorder
    recorder = IORecorder(
        args.input,
        args.output,
        include_api_methods=args.include_api_methods,
        exclude_api_methods=args.exclude_api_methods,
    )
    await recorder.run()


if __name__ == "__main__":
    asyncio.run(main())
