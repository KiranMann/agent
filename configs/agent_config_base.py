"""Base configuration class for agent-specific settings."""

from pathlib import Path
from typing import Any, ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field

from common.logging.core import logger


class AgentConfigBase(BaseModel):
    """Base configuration class for agent-specific settings."""

    agent_name: str = Field(..., description="Name of the agent")
    config_path: ClassVar[str]  # to be set by subclasses
    enabled: bool = Field(default=False, description="Whether the agent is enabled")
    llm_model: str = Field(default="", description="LLM model for this agent")
    model_config = ConfigDict(extra="allow", frozen=False)

    @classmethod
    def from_yaml(cls) -> Self:
        """Load agent config from YAML file using the class config_path.

        Raises ValueError if config_path is not set in subclass.
        """
        if not cls.config_path:
            raise ValueError(f"{cls.__name__}: config_path must be set in subclass")
        resolved_path = Path(cls.config_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"{cls.__name__}: Config file not found: {resolved_path}")

        logger.info(f"{cls.__name__}: Loading agent config from {resolved_path}")
        try:
            with resolved_path.open(encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            if not config_data:
                raise ValueError(f"{cls.__name__}: Empty or invalid YAML file: {resolved_path}")
            flat_config = cls._flatten_config(config_data)
            logger.debug(f"Loaded config for agent: {flat_config.get('agent_name', 'unknown')}")
            return cls(**flat_config)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in {resolved_path}: {e}")
            raise ValueError(f"Invalid YAML in {resolved_path}: {e}") from e
        except Exception as e:
            logger.error(f"Error loading config from {resolved_path}: {e}")
            raise  # TRY201

    @staticmethod
    def _flatten_config(config_data: dict[str, Any]) -> dict[str, Any]:
        flat = {}
        agent = config_data.get("agent", {})
        if isinstance(agent, dict):
            flat["agent_name"] = agent.get("name", "")
            flat["enabled"] = agent.get("enabled", False)

        llm = config_data.get("llm", {})
        if isinstance(llm, dict):
            flat["llm_model"] = llm.get("model", "")

        # Add other top-level fields that are not dicts
        flat.update(
            {
                key: value
                for key, value in config_data.items()
                if key not in ["agent", "llm"] and not isinstance(value, dict)
            }
        )
        return flat
