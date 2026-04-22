"""Pydantic models for A2A agents configuration."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class A2AAgentEntry(BaseModel):
    """A single A2A agent declaration (internal or external).

    Attributes:
        name: Canonical domain name (e.g., 'products', 'weather'). Card name derived as '{name}-agent'.
        type: 'internal' = hosted by FC, 'external' = hosted elsewhere
        url: Base URL for external agents (card fetched from {url}/.well-known/agent.json)
        enabled: Whether this agent should be loaded at startup
        description: Optional description for documentation
    """

    name: str = Field(..., description="Canonical domain name (e.g., 'products', 'weather')")
    type: Literal["internal", "external"] = Field(
        ..., description="'internal' = hosted by FC, 'external' = hosted elsewhere"
    )
    url: str = Field(default="", description="Base URL for external agents")
    enabled: bool = Field(default=True, description="Whether agent should be loaded at startup")
    description: str = Field(default="", description="Optional description")

    @model_validator(mode="after")
    def validate_url_for_external(self) -> "A2AAgentEntry":
        """External agents must have a URL."""
        if self.type == "external" and not self.url:
            raise ValueError(f"External agent '{self.name}' must have a 'url' field")
        return self


class A2AAgentsConfig(BaseModel):
    """Unified config for all A2A agents (internal + external).

    Attributes:
        agents: List of all A2A agent declarations
    """

    agents: list[A2AAgentEntry] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "A2AAgentsConfig":
        """Load config from a YAML file.

        Args:
            path: Path to YAML config file

        Returns:
            Parsed A2AAgentsConfig instance
        """
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    def enabled_external_urls(self) -> list[str]:
        """Return URLs of enabled external agents.

        Returns:
            List of base URLs for external agents marked as enabled
        """
        return [a.url for a in self.agents if a.enabled and a.type == "external"]

    def enabled_internal_names(self) -> set[str]:
        """Return canonical domain names of enabled internal agents.

        Returns:
            Set of domain names for internal agents marked as enabled
        """
        return {a.name for a in self.agents if a.enabled and a.type == "internal"}

    def enabled_agent_names(self) -> set[str]:
        """Return canonical domain names of all enabled agents.

        Returns:
            Set of all agent domain names that are enabled
        """
        return {a.name for a in self.agents if a.enabled}

    def enabled_domains(self) -> set[str]:
        """Return domain names of all enabled agents.

        Alias for enabled_agent_names() since names are domains.

        Returns:
            Set of all enabled agent domain names
        """
        return self.enabled_agent_names()

    def enabled_internal_card_names(self) -> set[str]:
        """Return A2A card names for enabled internal agents.

        Returns:
            Set of card names (e.g., 'products-agent') for internal agents
        """
        return {f"{a.name}-agent" for a in self.agents if a.enabled and a.type == "internal"}
