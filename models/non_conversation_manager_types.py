"""This module defines types and models for non-conversation manager-related payloads.

It includes payload structures and utilities for processing simple input data.
"""

from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict

from common.agent_base import AgentResponseMessage


class AgentType(Enum):
    """Type of agent."""

    OPENAI = "openai"
    LANGGRAPH = "langgraph"


class SimpleInputPayload(BaseModel):
    """Represents a simple input payload.

    Attributes:
        session_id (str): The session ID.
        uid (str): The unique identifier for the user.
        name (str): The name of the user (default is an empty string).
        activity_id (str): The activity ID (default is an empty string).
        message (str): The message content.
    """

    model_config = ConfigDict(extra="allow")
    session_id: str
    uid: str
    name: str = ""
    activity_id: str = ""
    message: str

    @property
    def extra_fields(self) -> set[str]:
        """Returns the extra fields in the payload that are not part of the model fields.

        Returns:
            set[str]: A set of extra field names.
        """
        return set(self.__dict__) - set(self.model_fields)


class SimpleInputResponse(TypedDict):
    """Response format for simple /message call."""

    session_id: str
    messages: list[dict[str, Any]]
    action: str | None
    response_message: list[AgentResponseMessage]
    ui_flags: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class QualityOutput(BaseModel):
    """Pydantic Model Class for Process Adherence Guardrail Output.

    This model defines the structure for the quality control guardrail's output.
    It is used to validate whether the agent followed the correct process steps
    and to provide reasoning for any detected deviations.

    Attributes:
        reasoning: Detailed explanation of why the process was followed correctly or not.
        deviation: Boolean flag indicating if a process deviation was detected.
    """

    reasoning: str
    deviation: bool


class ARPolicyAdherence(BaseModel):
    """Pydantic Model Class for Automated Reasoning Guardrail Output.

    This model defines the structure for the quality control guardrail's output.
    It is used to validate whether the agent followed the correct process steps
    and to provide reasoning for any detected deviations.

    Attributes:
        reasoning: Detailed explanation of why the policy was followed correctly or not.
        policy_variables: The policy variable values from the automated reasoning.
        deviation: Boolean flag indicating if a policy deviation was detected.
    """

    reasoning: str
    policy_variables: dict[str, Any]
    deviation: bool
