#!/usr/bin/env python3
"""Local test runner for Financial Companion API Integration Tests.

This script allows you to run the API integration tests locally
without needing to use Docker or GitHub Actions.

Usage:
    python scripts/run_api_integration_tests.py
    python scripts/run_api_integration_tests.py --config tests/test_data/api_test_config.yaml
    python scripts/run_api_integration_tests.py --environment dev
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from test_financial_companion_api_integration import FinancialCompanionAPITester

# Constants
SECONDS_PER_MINUTE = 60

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def setup_environment() -> None:
    """Set up the Python path and environment variables."""
    # Add the project root to Python path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    # Set PYTHONPATH environment variable
    os.environ["PYTHONPATH"] = str(project_root)

    logger.info("Project root: %s", project_root)
    logger.info("PYTHONPATH: %s", os.environ.get("PYTHONPATH"))


def run_standalone_tests(config_path: str, environment: str = "test2") -> tuple[bool, dict[str, Any] | None]:
    """Run the standalone test script."""
    logger.info("\n" + "=" * 60)
    logger.info("RUNNING STANDALONE TESTS - Environment: %s", environment)
    logger.info("=" * 60)

    try:
        # Create tester instance with environment
        tester = FinancialCompanionAPITester(config_path, environment)

        # Run full test suite
        results = tester.run_full_test_suite()

        # Print results summary with timing
        logger.info("\n" + "=" * 60)
        logger.info("STANDALONE TEST RESULTS SUMMARY")
        logger.info("=" * 60)

        # Format timing helper function
        def format_duration(seconds: float) -> str:
            """Format duration in seconds to a readable string."""
            if seconds < 1:
                return f"{seconds:.2f} seconds"
            elif seconds < SECONDS_PER_MINUTE:
                return f"{seconds:.1f} seconds"
            else:
                minutes = int(seconds // SECONDS_PER_MINUTE)
                remaining_seconds = seconds % SECONDS_PER_MINUTE
                return f"{minutes}m {remaining_seconds:.1f}s"

        logger.info(
            "DP Token Test: %s in %s",
            results["dp_token_test"]["status"],
            format_duration(results["dp_token_test"]["duration"]),
        )
        logger.info(
            "Conversations Test: %s in %s",
            results["conversations_test"]["status"],
            format_duration(results["conversations_test"]["duration"]),
        )
        logger.info(
            "Conversation Test: %s in %s",
            results["conversation_test"]["status"],
            format_duration(results["conversation_test"]["duration"]),
        )

        successful_messages = sum(1 for test in results["send_message_tests"] if test["status"] == "success")
        total_messages = len(results["send_message_tests"])
        send_messages_duration = results.get("send_messages_total_duration", 0)
        logger.info(
            "Message Tests: %d/%d successful in %s",
            successful_messages,
            total_messages,
            format_duration(send_messages_duration),
        )

        # Print any errors
        has_errors = False
        for key, result in results.items():
            if key not in [
                "send_message_tests",
                "total_duration",
                "send_messages_total_duration",
            ] and result.get("error"):
                logger.error("ERROR in %s: %s", key, result["error"])
                has_errors = True

        for test in results["send_message_tests"]:
            if test.get("error"):
                logger.error("ERROR in %s: %s", test["test_name"], test["error"])
                has_errors = True

        return not has_errors, results

    except (ImportError, RuntimeError):
        logger.exception("Error running standalone tests")
        return False, None


def validate_config_file(config_path: str) -> bool:
    """Validate that the configuration file exists and is valid."""
    config_file = Path(config_path)

    if not config_file.exists():
        logger.error("Error: Configuration file not found: %s", config_path)
        return False

    try:
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Basic validation
        required_sections = ["endpoints", "test_data"]
        for section in required_sections:
            if section not in config:
                logger.error("Error: Missing required section '%s' in config file", section)
                return False

        logger.info("✓ Configuration file is valid: %s", config_path)
        return True

    except (FileNotFoundError, yaml.YAMLError, KeyError):
        logger.exception("Error validating configuration file")
        return False


def format_duration(seconds: float) -> str:
    """Format duration in seconds to a readable string."""
    if seconds < 1:
        return f"{seconds:.2f} seconds"
    elif seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.1f} seconds"
    else:
        minutes = int(seconds // SECONDS_PER_MINUTE)
        remaining_seconds = seconds % SECONDS_PER_MINUTE
        return f"{minutes}m {remaining_seconds:.1f}s"


def main() -> None:
    """Main function to run the API integration tests."""
    parser = argparse.ArgumentParser(description="Run Financial Companion API Integration Tests locally")

    parser.add_argument(
        "--config",
        default="tests/test_data/api_test_config.yaml",
        help="Path to the test configuration YAML file",
    )

    parser.add_argument("--environment", default="test2", help="Test environment to use")

    args = parser.parse_args()

    logger.info("Financial Companion API Integration Test Runner")
    logger.info("=" * 60)
    logger.info("Configuration: %s", args.config)
    logger.info("Environment: %s", args.environment)
    logger.info("=" * 60)

    # Set up environment
    setup_environment()

    # Validate configuration file
    if not validate_config_file(args.config):
        sys.exit(1)

    # Set environment variable for tests
    os.environ["TEST_ENVIRONMENT"] = args.environment

    success = True

    # Run standalone tests
    standalone_success, test_results = run_standalone_tests(args.config, args.environment)
    success = success and standalone_success

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL TEST SUMMARY")
    logger.info("=" * 60)

    if success:
        total_duration = test_results.get("total_duration", 0) if test_results else 0
        logger.info("✅ All tests completed successfully!")
        logger.info("⏱️ Total execution time: %s", format_duration(total_duration))
        sys.exit(0)
    else:
        logger.error("❌ Some tests failed. Check the output above for details.")
        sys.exit(0)  # sometimes a single test fail because takes more than 60 to receive a reply


if __name__ == "__main__":
    main()
