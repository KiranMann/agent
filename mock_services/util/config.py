"""
Configuration module for mapping service instances and methods to their associated agents.
"""

import os

import yaml

# Global variables to cache loaded configuration
_SERVICE_AGENT_MAPPING: dict | None = None
_AGENT_ENV_VAR_MAPPING: dict | None = None
_CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "service_agent_mapping.yaml")


def _load_configuration() -> None:
    """
    Load configuration from YAML file if not already loaded.
    This function is called lazily when configuration is first needed.
    """
    global _SERVICE_AGENT_MAPPING, _AGENT_ENV_VAR_MAPPING

    if _SERVICE_AGENT_MAPPING is not None and _AGENT_ENV_VAR_MAPPING is not None:
        return  # Already loaded

    try:
        with open(_CONFIG_FILE_PATH, encoding="utf-8") as file:
            config = yaml.safe_load(file)

        _SERVICE_AGENT_MAPPING = config.get("service_agent_mapping", {})
        _AGENT_ENV_VAR_MAPPING = config.get("agent_env_var_mapping", {})

    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Configuration file not found: {_CONFIG_FILE_PATH}. "
            "Please ensure the service_agent_mapping.yaml file exists."
        ) from exc
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML configuration file: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error loading configuration: {e}") from e


def get_service_agent_mapping() -> dict:
    """
    Get the service-to-agent mapping configuration.

    Returns:
        Dict: The service-to-agent mapping dictionary
    """
    _load_configuration()
    return _SERVICE_AGENT_MAPPING or {}


def get_agent_env_var_mapping() -> dict:
    """
    Get the agent-to-environment-variable mapping configuration.

    Returns:
        Dict: The agent-to-environment-variable mapping dictionary
    """
    _load_configuration()
    return _AGENT_ENV_VAR_MAPPING or {}


def get_agent_for_service_method(service_instance: str, method_name: str) -> str:
    """
    Returns the associated agent based on the service instance and method name.

    Args:
        service_instance (str): The name of the service instance
        method_name (str): The name of the method being called

    Returns:
        str: The name of the associated agent, or None if no mapping found

    Raises:
        ValueError: If the service_instance or method_name is not found in the mapping
    """
    service_agent_mapping = get_service_agent_mapping()

    # Search through the mapping to find the agent for the given service and method
    for agent_name, services in service_agent_mapping.items():
        if service_instance in services:
            if method_name in services[service_instance]:
                return agent_name

    # If no mapping found, raise an error
    raise ValueError(f"No agent mapping found for service '{service_instance}' and method '{method_name}'")


def get_agent_cache_env_var(agent_name: str) -> str:
    """
    Returns the environment variable name for the agent's API cache path.

    Args:
        agent_name (str): The name of the agent

    Returns:
        str: The environment variable name for the agent's cache path

    Raises:
        ValueError: If the agent_name is not found in the mapping
    """
    agent_env_var_mapping = get_agent_env_var_mapping()

    if agent_name not in agent_env_var_mapping:
        raise ValueError(f"Agent '{agent_name}' not found in environment variable mapping")

    return agent_env_var_mapping[agent_name]


def get_cache_env_var_for_service_method(service_instance: object, method_name: str) -> str:
    """
    Returns the cache environment variable name for a given service instance and method.

    This function combines the functionality of finding the agent for a service/method
    and then returning the corresponding cache environment variable.

    Args:
        service_instance: The service instance
        method_name (str): The name of the method being called

    Returns:
        str: The environment variable name for the agent's cache path

    Raises:
        ValueError: If the service_instance/method_name combination is not found
    """

    class_name = service_instance.__class__.__name__
    # Remove "Mock" prefix if present to get the original service class name
    if class_name.startswith("Mock"):
        class_name = class_name[4:]  # Remove "Mock" prefix

    # First, get the agent for the service and method
    agent_name = get_agent_for_service_method(class_name, method_name)

    # Then, get the cache environment variable for that agent
    return get_agent_cache_env_var(agent_name)
