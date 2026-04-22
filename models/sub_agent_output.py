from typing import Any

from pydantic import BaseModel, Field, model_validator

from common.models.sub_agent_request import SubAgentRequests
from common.tools.conversation_messages import ConversationMessage


class SubAgentOutput(BaseModel):
    """Individual sub-agent output."""

    message: str = Field(..., min_length=1, description="Message to customer")
    ui_components: list[dict[str, Any] | str] = Field(default_factory=list, description="UI components for rendering")
    sources: list[dict[str, Any]] = Field(default_factory=list, description="Sources from RAG tools used by this agent")
    tool_execution_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tool execution data captured during agent run (tool name, outputs)",
    )
    tool_calls_with_inputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tool calls with their input arguments from raw_responses",
    )
    tool_input_schemas: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Tool input type schemas: {tool_name: {param: type_string}}",
    )
    synthesis_instructions: str = Field(
        default="",
        max_length=500,
        description="Instructions for the synthesis agent on how to handle this sub-agent's output. "
        "Used to guide synthesis behaviour, e.g., 'preserve exact wording', 'do not modify numerical values'.",
    )
    synthesis_bypass: bool = Field(
        default=False,
        description="When True, the synthesis layer is skipped entirely and this sub-agent's raw message "
        "is returned directly to the caller without any synthesis processing.",
    )


class SubAgentLLMOutputWithSynthesisInstructions(BaseModel):
    """Structured output schema for sub-agent LLM responses with synthesis instructions.

    This model is used as the output_type for sub-agents that need to provide
    explicit instructions to the synthesis layer on how their output should be handled.
    """

    message: str = Field(..., min_length=1, description="Message to customer")
    synthesis_instructions: str = Field(
        default="",
        description="Instructions for the synthesis agent on how to handle this response. "
        "Use this to preserve exact wording, numerical values, or formatting. "
        "Leave empty if no special handling is needed. "
        "Examples: 'Preserve exact numerical values', 'Do not paraphrase the spending breakdown'.",
    )


class SynthesisInput(BaseModel):
    """Synthesis input mapping requests to sub-agent outputs."""

    subagent_messages: list[str] = Field(..., description="List of all sub-agent outputs to synthesise.")
    subagent_requests: SubAgentRequests = Field(..., description="The requests originally made to the sub-agents.")
    conversation_history: list[ConversationMessage]
    customer_persona: str | None = Field(
        None,
        description="Customer persona summary as plain text for personalised responses",
    )
    subagent_synthesis_instructions: list[str] = Field(
        default_factory=list,
        description="List of synthesis instructions from each sub-agent, indexed to match subagent_messages. "
        "Each instruction guides how the synthesis agent should handle that sub-agent's output. "
        "Must be empty or have the same length as subagent_messages.",
    )

    @model_validator(mode="after")
    def validate_synthesis_instructions_length(self) -> "SynthesisInput":
        """Ensure subagent_synthesis_instructions length matches subagent_messages when provided."""
        if self.subagent_synthesis_instructions and len(self.subagent_synthesis_instructions) != len(
            self.subagent_messages
        ):
            raise ValueError(
                f"subagent_synthesis_instructions length ({len(self.subagent_synthesis_instructions)}) "
                f"must match subagent_messages length ({len(self.subagent_messages)}) when provided"
            )
        return self
