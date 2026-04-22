"""
Utility functions for mock services.

This module provides functionality for mock services including:
- API cache loading and response matching
- API input/output logging for tracking and analysis
- Configuration management for mock services

### Usage

#### Basic Logging

```python
# Log API input/output
log_api_io(
    api_name="api_services.AccountServices.get_accounts",
    input_params={"user_id": "12345", "account_type": "savings"},
    output={"accounts": [...], "total": 5},
)
```

#### Integration with Service Classes

Before logging inputs and outputs, you need to add logging to service methods, follow this pattern:

```python
def get_example_data(self, param1, param2):
    # Capture input parameters
    input_params = {"param1": param1, "param2": param2}

    # Execute the original logic
    result = self._fetch_data(param1, param2)

    # Log the I/O
    log_api_io(
        api_name=f"{self.__class__.__module__}.{self.__class__.__name__}.get_example_data",
        input_params=input_params,
        output=result,
    )

    return result
```

### Implementation Task

Update all service class read-only methods in `api_services/` to log input and output:

#### Target Files
- `api_services/account_services.py`
- `api_services/billhub_service.py`
- `api_services/cashflow_service.py`
- `api_services/home_buying_service.py`
- `api_services/location_data_service.py`
- `api_services/property_insight_service.py`
- `api_services/savings_goals_service.py`
- `api_services/shopping_deals_service.py`
- `api_services/spendlimits_service.py`

#### Implementation Instructions

For all functions in the above files that start with "get_", add logging using `log_api_io()` from `mock_services.mock_utils`.

**Example LLM Query:**
```
In all functions in following python files in api_services, filter functions that starts with "get_". For those functions log the inputs and outputs using log_api_io() from mock_services.mock_utils.

api_services/account_services.py
api_services/billhub_service.py
api_services/cashflow_service.py
api_services/home_buying_service.py
api_services/location_data_service.py
api_services/property_insight_service.py
api_services/savings_goals_service.py
api_services/shopping_deals_service.py
api_services/spendlimits_service.py
```

### Output Format

The logged data is stored in JSON format with the following structure:

```json
{
  "APIs": {
    "api_services.AccountServices.get_accounts": {
      "io_array": [
        {
          "input": {
            "user_id": "12345",
            "account_type": "savings"
          },
          "output": "{\"accounts\": [...], \"total\": 5}"
        }
      ]
    }
  }
}
```
"""

import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

from common.configs.app_config_settings import get_app_config
from common.logging.core import logger
from mock_services.util.config import get_cache_env_var_for_service_method

# Add the project root to the Python path to import common modules
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

# Load configuration which automatically handles .env.local loading
common_config = get_app_config()

# Default keys to ignore when matching parameters or logging input
DEFAULT_IGNORED_KEYS = [
    "correlation_id",
    "session_id",
    "referer",
    "cba_client_ip",
    "cba_device_id",
]

# Default mock response when no cached response is found
DEFAULT_MOCK_RESPONSE = {
    "response": "No cached response found for received input. This is a default response from the Mock service."
}


def load_api_cache(cache_env_var: str) -> dict[str, Any]:
    """Load the API cache from the JSON file specified in environment variable.

    Args:
        cache_env_var: The environment variable name containing the cache file path.

    Returns:
        Dict containing the API cache data, or empty structure if loading fails.
    """
    cache_path_base = os.getenv(cache_env_var)
    agent_name = cache_env_var.replace("_AGENT_MOCK_READ_API_CACHE_PATH", "")
    # Get the version of the cache to use from env vars
    cache_versions = os.getenv(f"{agent_name}_CACHE_VERSIONS")
    if cache_versions is None:
        # Default to v1, and log
        logger.debug(f"Unable to retrieve a cache version for agent: {agent_name}")
        cache_version = "v1"
    else:
        cache_version = ast.literal_eval(cache_versions).get(agent_name.lower(), "v1")

    if cache_path_base is None:
        logger.error(f"{cache_env_var} environment variable not set")
        return {"APIs": {}}

    cache_path = cache_path_base + f"_{cache_version}.json"

    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"API cache file not found: {cache_path}")
        return {"APIs": {}}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing API cache JSON: {e}")
        return {"APIs": {}}


def find_matching_response_with_api_method(
    service_instance: object,
    method_name: str,
    input_params: dict[str, Any],
    ignored_keys: list,
) -> Any | None:
    """
    Find matching response from cache based on input parameters.

    When input_params contains keys with None values, this function will match both:
    - Cases where the key doesn't exist in the cached data
    - Cases where the key exists but has a null value in the cached data

    Args:
        service_instance: The service instance name object
        method_name: The method name (e.g., "get_cycle_settings", "get_products")
        input_params: Dictionary of input parameters
        ignored_keys: List of keys to ignore when matching parameters.

    Returns:
        The matching cached response, or None if no match found
    """

    # Get the appropriate cache environment variable for this service/method combination
    cache_env_var = get_cache_env_var_for_service_method(service_instance, method_name)

    cache_data = load_api_cache(cache_env_var)

    method_name_fqdn = infer_api_method_fqdn(service_instance, method_name)

    if "APIs" not in cache_data:
        logger.error("Invalid cache format: missing 'APIs' key")
        return None

    method_data = cache_data["APIs"].get(method_name_fqdn)
    if not method_data or "io_array" not in method_data:
        logger.info(f"No cached data found for method: {method_name_fqdn}")
        return None

    # Create a copy of input params excluding ignored keys for matching
    match_params = {k: v for k, v in input_params.items() if k not in ignored_keys}

    for entry in method_data["io_array"]:
        if "input" not in entry or "output" not in entry:
            continue

        # Create a copy of cached input excluding ignored keys
        cached_input = {k: v for k, v in entry["input"].items() if k not in ignored_keys}

        if _params_match_with_none_handling(match_params, cached_input):
            # Parse the output if it's a JSON string
            output = entry["output"]
            return output

    return None


def _params_match_with_none_handling(match_params: dict[str, Any], cached_input: dict[str, Any]) -> bool:
    """
    Compare parameters with special handling for None values.

    When match_params contains a key with None value, it will match if:
    - The key doesn't exist in cached_input, OR
    - The key exists in cached_input but has a None value

    Args:
        match_params: Parameters to match (from input_params)
        cached_input: Cached parameters to match against

    Returns:
        True if parameters match according to the None-handling rules, False otherwise
    """
    # Check all keys in match_params
    for key, value in match_params.items():
        if value is None:
            # For None values, match if key doesn't exist OR key exists with None value
            if key in cached_input and cached_input[key] is not None:
                return False
        # For non-None values, require exact match
        elif key not in cached_input or cached_input[key] != value:
            return False

    # Check for extra keys in cached_input that aren't None in match_params
    # If cached_input has a key that's not in match_params, it only matches if the cached value is None
    return all(not (key not in match_params and value is not None) for key, value in cached_input.items())


def infer_api_method_fqdn(service_instance: object, method_name: str) -> str:
    """
    Infer the API method FQDN name from the service instance and method name.

    Args:
        service_instance: The service instance (e.g., self in a mock service)
        method_name: The method name (e.g., "get_cycle_settings")

    Returns:
        The inferred FQDN method name (e.g., "api_services.SpendLimitsService.get_cycle_settings")
    """
    # Get the class name from the service instance
    class_name = service_instance.__class__.__name__

    # Remove "Mock" prefix if present to get the original service class name
    if class_name.startswith("Mock"):
        class_name = class_name[4:]  # Remove "Mock" prefix

    # Get the module name from the service instance
    module_name = service_instance.__class__.__module__

    # For mock services, we need to infer the original API service module
    # Convert mock_services.spendlimits_mock_service -> api_services.SpendLimitsService
    api_module = f"api_services.{class_name}" if "mock_services" in module_name else f"{module_name}.{class_name}"

    return f"{api_module}.{method_name}"


def find_matching_response(
    service_instance: object,
    method_name: str,
    input_params: dict[str, Any],
    ignored_keys: list | None = None,
) -> Any | None:
    """
    Find matching response from cache with automatic FQDN inference.

    Args:
        service_instance: The service instance (e.g., self in a mock service)
        input_params: Dictionary of input parameters
        method_name: Optional method name. If not provided, will be inferred from the calling method
        ignored_keys: List of keys to ignore when matching parameters.
                     Defaults to ["correlation_id", "session_id"] if not provided.

    Returns:
        The matching cached response, or None if no match found

    Note:
        By default, correlation_id and session_id are excluded from matching as they are unique per request
    """
    logger.info(
        f"Reading API cache: method_name: {method_name}. input_params:{input_params}. ignored_keys: {ignored_keys}"
    )
    # Use default ignored keys if none provided
    if ignored_keys is None:
        ignored_keys = DEFAULT_IGNORED_KEYS

    cached_response = find_matching_response_with_api_method(service_instance, method_name, input_params, ignored_keys)
    if cached_response is not None:
        logger.info(f"Read API cache:HIT. input_params: {input_params}")
    else:
        logger.info(f"Read API cache:MISS. input_params: {input_params}")
    return cached_response


def return_default_mock_response() -> Any:
    """
    Return the default mock response when no cached response is found.

    Returns:
        Any: The default mock response (can be Dict or List depending on context)
    """
    logger.info("No cached response found for received input. This is a default response from the Mock service.")
    return DEFAULT_MOCK_RESPONSE


def log_api_io(
    api_name: str,
    input_params: dict[str, Any],
    output: Any,
    ignored_keys: list | None = None,
):
    """
    Log API input/output to JSON file.

    Args:
        api_name (str): The fully qualified API name (e.g., "api_services.SpendLimitsService.get_cycle_settings")
        input_params (Dict[str, Any]): Dictionary of input parameters
        output (Any): The output/result from the API call
        ignored_keys (Optional[list]): List of keys to replace with empty strings in logged input.
                                     Defaults to ["correlation_id", "session_id"] if not provided.

    Raises:
        ValueError: If MOCK_READ_API_CACHE_PATH is not configured in .env.local
    """
    # Use default ignored keys if none provided
    if ignored_keys is None:
        ignored_keys = DEFAULT_IGNORED_KEYS

    # Use MOCK_READ_API_CACHE_PATH from .env.local - this must be configured
    log_file = getattr(common_config, "MOCK_READ_API_CACHE_PATH", None)
    if not log_file:
        error_msg = "MOCK_READ_API_CACHE_PATH is not configured. Please set this environment variable to specify the API I/O log file path."
        logger.error(f"Error: {error_msg}")
        raise ValueError(error_msg)

    try:
        # Read existing data or create new structure
        if os.path.exists(log_file):
            with open(log_file, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"APIs": {}}

        # Ensure APIs key exists
        if "APIs" not in data:
            data["APIs"] = {}

        # Initialize API entry if it doesn't exist, or ensure io_array exists
        if api_name not in data["APIs"]:
            data["APIs"][api_name] = {"io_array": []}
        elif "io_array" not in data["APIs"][api_name]:
            data["APIs"][api_name]["io_array"] = []

        # Create a copy of input_params and replace ignored keys with empty strings
        logged_input_params = input_params.copy()
        for key in ignored_keys:
            if key in logged_input_params:
                logged_input_params[key] = ""

        # Check if the same input already exists in io_array
        input_exists = False
        for entry in data["APIs"][api_name]["io_array"]:
            if "input" in entry and entry["input"] == logged_input_params:
                input_exists = True
                break

        # Only append new entry if the same input doesn't already exist
        if not input_exists:
            data["APIs"][api_name]["io_array"].append(
                {
                    "input": logged_input_params,
                    "output": output,
                }
            )

            # Write back to file
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    except (OSError, json.JSONDecodeError, KeyError) as e:
        # If logging fails, don't break the API call - just log the error
        logger.error(f"Error logging API I/O for {api_name}: {e!s}")
