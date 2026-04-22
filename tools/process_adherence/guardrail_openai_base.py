"""This class creates a base process adherence guardrail that can be used in openai-agents applications.

It can also be extended to be customized to work with other frameworks.
"""

import ast
import re
from typing import Any, cast

from agents import Agent, ModelSettings, RunConfig, Runner, items
from litellm import ResponseFunctionToolCall

from common.configs.app_config_settings import AppConfig
from common.model_config import model
from common.models.non_conversation_manager_types import QualityOutput
from common.tools.prompt_reader import Jinja2PromptReader


class OpenaiProcessAdherenceGuardrailBase:
    """Base class to be used for process adherence guardrails.

    Usable with agents built with the OpenAi Agents SDK's item-based model.
    """

    def __init__(
        self,
        agent_prompts: dict[str, Any],
        run_config: RunConfig = RunConfig(tracing_disabled=True),
        system_prompt_template: str = "process_adherence_system_prompt.md",
        guardrail_prompt_template: str = "process_adherence_guardrail_prompt.md",
    ) -> None:
        """Initialize the ProcessAdherenceGuardrailBase.

        Args:
            agent_prompts (Dict): Dictionary mapping agent names to their prompt templates.
            run_config (RunConfig, optional): Configuration for running the guardrail agent.
                Defaults to RunConfig with tracing disabled.
            system_prompt_template (str, optional): Path to the system prompt template file.
                Defaults to "process_adherence_system_prompt.md".
            guardrail_prompt_template (str, optional): Path to the guardrail prompt template file.
                Defaults to "process_adherence_guardrail_prompt.md".
        """
        self.prompt_reader = Jinja2PromptReader()
        self.run_config = run_config

        self.system_prompt_template = self.prompt_reader.read(system_prompt_template)
        self.guardrail_prompt_template = self.prompt_reader.read(guardrail_prompt_template)

        self.agent_templates = agent_prompts

        # Define a regex expression to capture only the instructions for the agent where possible, based on the template used in cards reissuance
        self.instructions_pattern: str = rf"# {re.escape('Execution Instructions')}(.*?)# {re.escape('Role')}"  # pylint: disable=inconsistent-quotes

        self.quality_agent = Agent(
            name="ProcessAdherenceGuardrail",
            instructions=self.prompt_reader.render(self.system_prompt_template),
            model=model,
            output_type=QualityOutput,
            model_settings=ModelSettings(temperature=0),
        )

    def get_agent_instructions(
        self,
        render_template: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Extract and return agent instructions from their prompt templates.

        Attempts to extract only the 'Execution Instructions' section from each agent's
        prompt template using regex pattern matching. If the pattern is not found,
        returns the entire prompt template.

        Args:
            render_template (dict, optional): Template variables for rendering prompts.
                Defaults to {"retry_instructions": ""} for if using with card reissuance prompt template

        Returns:
            dict: Dictionary mapping agent names to their extracted instructions.
        """
        render_template = render_template or {"retry_instructions": ""}
        agent_instructions: dict[str, str] = {}

        for agent, template in self.agent_templates.items():
            prompt: str = self.prompt_reader.render(template, render_template)

            match: re.Match[str] | None = re.search(self.instructions_pattern, prompt, re.DOTALL)

            # If the agent conforms to a template that segments agent instructions, take only the agent instructions
            if match:
                instructions = match.group(1).strip()
                agent_instructions[agent] = instructions
            # If agent prompt is not formatted correctly take the entire prompt
            else:
                agent_instructions[agent] = prompt

        return agent_instructions

    def get_actions(
        self,
        agent_output: list[Any],
    ) -> dict[str, list[str]]:
        """Extract tools and handoffs from an OpenAI agent run.

        Parses the agent output to identify tool calls and handoff operations,
        returning them in separate lists.

        Args:
            agent_output: List of output items from agent execution. Obtained using new_items on an agents response

        Returns:
            dict: Dictionary with 'tools' and 'handoffs' keys containing lists of
                tool names and handoff target agents respectively.
        """
        tools = []
        handoffs = []

        for item in agent_output:
            if isinstance(item, items.ToolCallItem):
                if isinstance(item.raw_item, ResponseFunctionToolCall):
                    tools.append(item.raw_item.name)
            elif isinstance(item, items.HandoffOutputItem):
                output_item = cast("dict[str, Any]", item.raw_item)
                handoff_agent = ast.literal_eval(output_item.get("output", ""))
                if "assistant" in handoff_agent:
                    handoff_agent = handoff_agent["assistant"]
                    handoffs.append(handoff_agent)

                    tools.append(f"handoff_to_{handoff_agent}")

        return {"tools": tools, "handoffs": handoffs}

    def build_prompt(
        self,
        tools: list[str],
        handoffs: list[str],
        final_output: Any,
        agent_instructions: dict[str, str],
        current_agent: str,
        conversation: Any,
        start_step: str = "",
    ) -> str:
        """Build the guardrail prompt.

        Constructs a prompt for the guardrail agent that includes
        process steps, conversation history, and agent responses for evaluation.

        Args:
            tools: List of tools used by the agent.
            handoffs: List of agents that were handed off to.
            final_output: The full json response generated by the current agent (Including any additional metadata beyond user message).
            agent_instructions (dict): Dictionary mapping agent names to their instructions.
            current_agent (str): Name of the current agent (ie the starting agent).
            conversation: The conversation history.
            start_step (str, optional): Starting step information if used. Defaults to "".

        Returns:
            str: The rendered guardrail evaluation prompt.
        """
        # Build agent steps
        process_steps: str = f"{current_agent}\n{agent_instructions[current_agent]}"

        for agent in handoffs:
            process_steps += f"\n\nTransfer to {agent}\n{agent_instructions[agent]}"

        prompt: str = self.prompt_reader.render(
            self.guardrail_prompt_template,
            {
                "process_steps": process_steps,
                "conversation": conversation,
                "final_output": final_output,
                "current_agent": current_agent,
                "start_step": start_step,
                "tools": tools,
            },
        )

        return prompt

    async def run_guardrail(
        self,
        prompt: str,
    ) -> QualityOutput:
        """Execute the guardrail evaluation.

        Runs the quality agent with the provided prompt to evaluate process adherence.

        Args:
            prompt (str): The evaluation prompt generated by build_prompt().

        Returns:
            The final output from the guardrail agent evaluation as a QualityOutput item containing
            details on if a deviation occured/reasoning behind the decision
        """
        if AppConfig.QUALITY_GUARDRAIL != "ProcessAdherence":
            return QualityOutput(
                reasoning='Process adherence check is disabled. Configure QUALITY_GUARDRAIL to be "ProcessAdherence" to enable it.',
                deviation=False,
            )

        result = await Runner.run(self.quality_agent, prompt, run_config=self.run_config)

        return cast("QualityOutput", result.final_output)
