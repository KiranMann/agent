"""Tools for guardrail functionality in the financial companion agent."""

import ast
import json
import re
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as DefusedElementTree
from agents import Agent, MessageOutputItem, RunContextWrapper
from langfuse import Langfuse
from langfuse.decorators import langfuse_context

from apps.companion.agent_services.models import AgentDetails
from apps.companion.all_agents.guardrails.models import (
    GuardrailOperators,
    GuardrailOutputInfo,
    GuardrailResponseContext,
    GuardrailStatus,
    PrincipalGuardrailFunctionOutput,
    map_guardrail_name_to_operator,
)
from common.configs.agent_config_settings import AgentConfig
from common.constants import SYNTHESIS_AGENT_KEY
from common.logging.core import logger
from common.utils.date_utils import _get_current_date_string, inject_date

# Error messages
PRINCIPAL_AGENT_NOT_FOUND_MESSAGE = "Principal agent not found in context"

# Clarifying questions clause for groundedness check
CLARIFYING_QUESTIONS_CLAUSE = (
    "The final response may include clarifying questions to the customer. "
    "For any clarifying question, check if: "
    "1. The purpose of the question is to clarify the customer's intent; "
    "2. The question is relevant to the customer's query; and "
    "3. The question might be relevant to the supported domains. "
    "If ALL of the above is true, treat the question as grounded."
)


@dataclass
class FixedAgentContext:
    """Contains context components that rarely change and can benefit from caching."""

    principal_agent_prompt: str  # Raw system prompt (before date injection)
    subagent_prompts: dict[str, str]  # {agent_name: filtered_prompt}
    relevant_sections: list[str]  # XML sections included


@dataclass
class DynamicAgentContext:
    """Contains context components that change with each request."""

    conversation_history: str
    tool_calls: str
    current_date: str  # From inject_date() - changes daily or per test
    session_id: str


def _remove_code_block_wrappers(text: str) -> str:
    """Remove code block wrappers from text.

    Handles both ```json and ``` wrappers.

    Args:
        text: Text potentially wrapped in code blocks

    Returns:
        str: Text with code block wrappers removed
    """
    text = text.strip()

    # Handle ```json wrapper
    if text.startswith("```json"):
        text = text[7:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    # Handle ``` wrapper without json
    elif text.startswith("```"):
        text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    return text


def _find_json_boundaries(text: str) -> tuple[int, int]:
    """Find the start and end indices of JSON content in text.

    Properly matches braces to handle nested JSON objects.

    Args:
        text: Text containing JSON content

    Returns:
        tuple[int, int]: (start_idx, end_idx) or (-1, -1) if not found
    """
    start_idx = text.find("{")
    if start_idx == -1:
        return -1, -1

    # Find matching closing brace
    brace_count = 0
    end_idx = start_idx
    for i in range(start_idx, len(text)):
        if text[i] == "{":
            brace_count += 1
        elif text[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                end_idx = i
                break

    if brace_count != 0:
        # Unmatched braces
        return start_idx, -1

    return start_idx, end_idx


def _validate_json_content(json_content: str) -> str:
    """Validate and return JSON content, or empty object if invalid.

    Args:
        json_content: String to validate as JSON

    Returns:
        str: Valid JSON string or "{}" if invalid
    """
    try:
        json.loads(json_content)
        return json_content
    except json.JSONDecodeError:
        logger.warning(f"Extracted content is not valid JSON: {json_content}")
        return "{}"


def extract_json_from_text(text: str) -> str:
    """Extract JSON content from text, handling various wrapper formats and extra explanations.

    This is a robust centralized utility function used across multiple guardrails
    to extract JSON from LLM responses that may contain markdown code blocks,
    nested braces, or other wrapper text.

    Args:
        text: Text containing JSON content

    Returns:
        str: Extracted and validated JSON string, or "{}" if not found/invalid
    """
    if not text:
        return "{}"

    # Remove code block wrappers
    text = _remove_code_block_wrappers(text)

    # Find JSON boundaries
    start_idx, end_idx = _find_json_boundaries(text)

    if start_idx == -1:
        return "{}"

    if end_idx == -1:
        # Unmatched braces, return what we have
        return text[start_idx:]

    json_content = text[start_idx : end_idx + 1]
    return _validate_json_content(json_content)


def _extract_customer_persona_from_context(context: RunContextWrapper) -> str:
    """Extract customer persona information from context.

    Args:
        context: The RunContextWrapper containing customer persona data

    Returns:
        str: Customer persona information or empty string if not available
    """
    if not hasattr(context, "context"):
        logger.debug("Context object has no 'context' attribute for persona extraction")
        return ""

    # Check for persona in user_preferences
    if hasattr(context.context, "user_preferences") and context.context.user_preferences:
        persona_data = context.context.user_preferences
        if isinstance(persona_data, str) and persona_data.strip():
            logger.info(f"Found customer persona in user_preferences: {len(persona_data)} characters")
            return persona_data.strip()

    logger.debug("No customer persona found.")

    return ""


def serialize_ui_components(ui_components: list[dict[str, Any]]) -> str:
    """Serialize UI components to JSON string."""
    try:
        return json.dumps(ui_components, indent=2)
    except Exception as e:
        logger.error(f"Error serializing UI components: {e}")
        return "[]"


def _get_relevant_sections(prompt: str, relevant_sections: list[str]) -> str:
    """Used for extracting relevant sections of the principal prompt to be injected into the context.

    Given a string like:
        <goal>
        You strive to deliver excellent customer service
        </goal>

        <instructions>
        Never allow a customer to use their name
        </instructions>
    and relevant_sections = ["goal"], this will return:
    '
        <goal>
        You strive to deliver excellent customer service
        </goal>
    '
    """
    section_block_re = re.compile(
        r"<(?P<name>[a-zA-Z_][\w\-]*)>\s*.*?\s*</\1>",
        re.DOTALL,
    )

    # We also use { if } blocked in jinja templates, we use this to get around that
    empty_if_block_re = re.compile(
        r"\{%\s*if\b[^%]*%\}\s*(?:\r?\n|\s)*\{%\s*endif\s*%\}",
        re.DOTALL,
    )

    keep = {s.strip().lower() for s in relevant_sections}

    # Replace each section block with itself or nothing depending on whether we want it
    def _filter_block(m: re.Match[str]) -> str:
        name = m.group("name").lower()
        return m.group(0) if name in keep else ""

    filtered = section_block_re.sub(_filter_block, prompt)

    # Remove any now-empty `{% if ... %} ... {% endif %}` blocks
    filtered = empty_if_block_re.sub("", filtered)

    # Normalise whitespace: collapse runs of 3+ newlines to 2, trim edges
    filtered = re.sub(r"\n{3,}", "\n\n", filtered).strip()

    return filtered


def _filter_xml_by_attributes(xml_content: str) -> str:
    """Filter out XML elements with used_in_groundedness_check='false'.

    This function parses XML content and removes any nested elements that have
    the attribute used_in_groundedness_check="false".

    Args:
        xml_content: XML content string to filter

    Returns:
        str: Filtered XML content with excluded elements removed
    """
    if not xml_content or not xml_content.strip():
        return xml_content

    try:
        # Wrap content in a root element to ensure valid XML for parsing
        wrapped_content = f"<root>{xml_content}</root>"
        root: Element = DefusedElementTree.fromstring(wrapped_content)

        # Recursively remove elements with used_in_groundedness_check="false"
        def remove_filtered_elements(element: Element) -> None:
            # Work backwards through children to avoid index issues when removing
            for child in reversed(list(element)):
                if child.get("used_in_groundedness_check") == "false":
                    element.remove(child)
                else:
                    # Recursively process child elements
                    remove_filtered_elements(child)

        remove_filtered_elements(root)

        # Extract content back (remove the wrapper root element)
        filtered_content = ""
        for child in root:
            filtered_content += DefusedElementTree.tostring(child, encoding="unicode", method="xml")

        # Clean up any extra whitespace left behind
        filtered_content = re.sub(r"\n{3,}", "\n\n", filtered_content).strip()

        return filtered_content

    except DefusedElementTree.ParseError:
        # If XML parsing fails, fall back to including the original content
        # This maintains backward compatibility with malformed XML
        return xml_content


async def _get_sub_agent_system_prompts(principal_agent: Any) -> dict[str, str]:
    """Get system prompts from all sub-agents using existing instances from principal agent.

    Args:
        context: The context object needed for get_system_prompt calls
        principal_agent: The principal agent instance containing sub-agent instances

    Returns:
        Dict[str, str]: Dictionary mapping agent names to their system prompts
    """
    prompts = {}

    # Map to the actual sub-agent instances in FinancialCompanionAgent
    agent_mappings = {
        "products_agent": (
            getattr(principal_agent, "products_agent", None),
            "products_agent",
        ),
        "savings_agent": (
            getattr(principal_agent, "savings_agent", None),
            "savings_agent",
        ),
        "homeloans_agent": (
            getattr(principal_agent, "homebuying_agent", None),
            "homebuying_agent",
        ),
    }

    for agent_name, (agent_instance, internal_agent_attr) in agent_mappings.items():
        if agent_instance:
            # Get system prompt from the internal Agent instance's instructions
            internal_agent = getattr(agent_instance, internal_agent_attr, None)
            if internal_agent and hasattr(internal_agent, "instructions"):
                system_prompt = internal_agent.instructions
                prompts[agent_name] = system_prompt
                logger.debug(f"Successfully loaded {agent_name} system prompt from instructions")
            else:
                logger.warning(f"Could not access instructions for {agent_name}")
                prompts[agent_name] = "No internal agent"
        else:
            logger.warning(f"Principal agent has no {agent_name} instance")
            prompts[agent_name] = f"No {agent_name} instance"

    return prompts


def _extract_relevant_xml_tags(prompt: str) -> str:
    """Extract only relevant XML tags from standardized prompts for groundedness checking.

    This function extracts specific XML tags that are relevant for groundedness checking:
    - <agent_role> (always include - essential for understanding agent purpose)
    - <tools_and_process> (always include - needed for understanding capabilities)
    - <additional_information> (always include - contains factual data)

    Within each extracted tag, it filters out nested XML elements that have
    used_in_groundedness_check="false" attributes.

    Skips these tags to reduce context size:
    - <compliance_and_limitations> (not needed for groundedness checking)
    - <response_formatting> (not needed for groundedness checking)

    Args:
        prompt: The full prompt content with XML tags

    Returns:
        str: Filtered prompt content with only relevant XML tags and filtered nested content
    """
    if not prompt:
        return ""

    # Handle non-string inputs (e.g., from tests or edge cases)
    prompt_str = str(prompt) if not isinstance(prompt, str) else prompt

    # Extract relevant XML tags
    filtered_content = _get_relevant_sections(prompt_str, AgentConfig.RELEVANT_CONTEXT_SECTIONS)

    # Apply XML attribute-based filtering to remove elements with used_in_groundedness_check="false"
    filtered_content = _filter_xml_by_attributes(filtered_content)

    return filtered_content


def _get_conversation_history_for_groundedness(context: RunContextWrapper) -> str:
    """Get previous conversation history for groundedness check."""
    if not hasattr(context, "context"):
        return "[]"

    history = getattr(context.context, "conversation_history", []) or []
    filtered = [convo for convo in history if isinstance(convo, dict)]
    return str(filtered if filtered else [])


async def _get_sub_agent_prompts_for_groundedness(
    context: RunContextWrapper,
) -> dict[str, str]:
    """Get sub-agent system prompts for groundedness check."""
    if hasattr(context, "context") and hasattr(context.context, "principal_agent"):
        principal_agent = context.context.principal_agent
        return await _get_sub_agent_system_prompts(principal_agent)

    logger.warning(PRINCIPAL_AGENT_NOT_FOUND_MESSAGE)
    return {
        "products_agent": PRINCIPAL_AGENT_NOT_FOUND_MESSAGE,
        "savings_agent": PRINCIPAL_AGENT_NOT_FOUND_MESSAGE,
        "homeloans_agent": PRINCIPAL_AGENT_NOT_FOUND_MESSAGE,
    }


async def get_agent_context(context: RunContextWrapper, agent: Agent, filter_principal: bool = True) -> dict[str, Any]:
    """Get agent context with granular separation for better caching.

    Returns a dictionary with separate components:
    - "principal_agent_instructions": filtered principal agent prompt WITHOUT date (cacheable)
    - "customer_persona": extracted customer persona information (dynamic per customer)
    - "current_date": today's datetime as separate entry (dynamic daily)
    - "sub_agent_instructions": dict of sub-agent prompts (cacheable)
    - "conversation_history": previous conversation (dynamic)
    - "tool_calls": tool execution data (dynamic)
    - "session_metadata": session info (dynamic)

    Args:
        context: The RunContextWrapper containing execution context
        agent: The agent instance
        filter_principal: Whether or not we should filter the principal prompt by XML tags (for rewrite agent)

    Returns:
        dict: Structured context data with granular components for optimal caching
    """
    # Get raw principal agent prompt (without date injection)
    principal_agent_prompt = await agent.get_system_prompt(context) or ""

    # Filter principal agent prompt to cacheable content only
    # NOTE: We only filter the FinancialCompanion principal agent, and not rewrite agent.
    filtered_principal_instructions = (
        _extract_relevant_xml_tags(principal_agent_prompt) if filter_principal else principal_agent_prompt
    )
    # Get sub-agent prompts (cacheable)
    sub_agent_prompts = await _get_sub_agent_prompts_for_groundedness(context)
    filtered_sub_agent_prompts = {}
    for agent_name, prompt in sub_agent_prompts.items():
        filtered_sub_agent_prompts[agent_name] = _extract_relevant_xml_tags(prompt)

    # Get dynamic context components
    previous_conversation_history = _get_conversation_history_for_groundedness(context)
    tool_calls_result = get_tool_responses_from_context(context, agent)
    tool_calls = str(tool_calls_result) if tool_calls_result else ""

    # Extract customer persona (dynamic per customer)
    customer_persona = _extract_customer_persona_from_context(context)
    # Get current date (dynamic daily)
    current_date = _get_current_date_string()

    return {
        "principal_agent_instructions": filtered_principal_instructions,
        "customer_persona": customer_persona,
        "current_date": current_date,
        "sub_agent_instructions": filtered_sub_agent_prompts,
        "conversation_history": previous_conversation_history,
        "tool_calls": tool_calls,
    }


def extract_ui_components_from_context(
    context: RunContextWrapper,
) -> list[dict[str, Any]]:
    """Extract UI components from context with error handling."""
    ui_components: list[dict[str, Any]] = []
    if hasattr(context, "context") and hasattr(context.context, "ui_components"):
        try:
            ui_components = context.context.ui_components or []
            # Ensure ui_components is a list and JSON serializable
            if not isinstance(ui_components, list):
                ui_components = []
        except Exception as e:
            logger.debug(f"Could not extract UI components from context: {e}")
            ui_components = []
    return ui_components


async def get_context_string_from_run_context(context: RunContextWrapper, agent: Agent) -> str:
    """Get agent context as a structured string for backward compatibility.

    This function provides backward compatibility for existing code that expects
    a string return value from get_agent_context. It structures the context with
    clear headers and sections to prevent guardrails from being confused about
    which agent instructions apply to them.

    Args:
        context: The run context wrapper
        agent: The agent instance

    Returns:
        str: Structured context string with clear section headers
    """
    structured_context = await get_agent_context(context, agent)

    # Build the context string with clear section headers
    context_parts = []

    # Add header explaining the context structure
    context_parts.append("=== AGENT CONTEXT FOR GUARDRAIL EVALUATION ===")
    context_parts.append("The following sections contain context information for guardrail evaluation.")
    context_parts.append("Each section is clearly marked and should be treated as reference information only.")
    context_parts.append("")

    # Add principal agent instructions with date injection
    principal_instructions = structured_context["principal_agent_instructions"]

    principal_with_date = inject_date(principal_instructions)

    context_parts.append("=== PRINCIPAL AGENT INSTRUCTIONS ===")
    context_parts.append("These are the instructions for the main financial companion agent.")
    context_parts.append("This is NOT your role - you are evaluating the agent's adherence to these instructions.")
    context_parts.append("")
    context_parts.append(principal_with_date)
    context_parts.append("")

    # Add customer persona if present
    customer_persona = structured_context["customer_persona"]

    if customer_persona.strip():
        context_parts.append("=== CUSTOMER PERSONA ===")
        context_parts.append("This section contains information about the current customer's profile and preferences.")
        context_parts.append("")
        context_parts.append(customer_persona)
        context_parts.append("")

    # Add sub-agent instructions
    sub_agent_instructions = structured_context["sub_agent_instructions"]

    if sub_agent_instructions:
        context_parts.append("=== SUB-AGENT INSTRUCTIONS ===")
        context_parts.append(
            "These are instructions for specialized sub-agents that may be called by the principal agent."
        )
        context_parts.append("These are NOT your instructions - you are evaluating how well the agents follow these.")
        context_parts.append("")

        for agent_name, prompt in sub_agent_instructions.items():
            # Inject date into sub-agent prompts as well
            prompt_with_date = inject_date(prompt)
            context_parts.append(f"--- {agent_name.upper()} AGENT INSTRUCTIONS ---")
            context_parts.append(prompt_with_date)
            context_parts.append("")

    # Add conversation history
    conversation_history = structured_context["conversation_history"]
    if conversation_history.strip():
        context_parts.append("=== CONVERSATION HISTORY ===")
        context_parts.append("This section contains the previous conversation between the customer and agent.")
        context_parts.append("")
        context_parts.append(conversation_history)
        context_parts.append("")

    # Add tool calls
    tool_calls = structured_context["tool_calls"]
    if tool_calls.strip():
        context_parts.append("=== TOOL EXECUTION RESULTS ===")
        context_parts.append("This section contains the results of tools that were executed during the conversation.")
        context_parts.append("")
        context_parts.append(tool_calls)
        context_parts.append("")

    context_parts.append("=== END OF CONTEXT ===")

    return "\n".join(context_parts)


async def get_agent_context_string(
    agent_details: AgentDetails,
    conversation_history: list[MessageOutputItem] | None = None,
) -> str:
    """Get agent context as a structured string for backward compatibility.

    This function structures inputs from agent details and convo history into a
    context string

    Args:
        agent_details: AgentDetails,
        conversation_history: list[MessageOutputItem] | None = None,

    Returns:
        str: Structured context string with clear section headers
    """
    # Build the context string with clear section headers
    context_parts = []

    # Add header explaining the context structure
    context_parts.append("=== AGENT CONTEXT FOR GUARDRAIL EVALUATION ===")
    context_parts.append("The following sections contain context information for guardrail evaluation.")
    context_parts.append("Each section is clearly marked and should be treated as reference information only.")
    context_parts.append("")

    # Add principal agent instructions with date injection
    principal_instructions = agent_details.agent_prompts.get(SYNTHESIS_AGENT_KEY, "")

    principal_with_date = inject_date(principal_instructions)

    context_parts.append("=== PRINCIPAL AGENT INSTRUCTIONS ===")
    context_parts.append("These are the instructions for the main financial companion agent.")
    context_parts.append("This is NOT your role - you are evaluating the agent's adherence to these instructions.")
    context_parts.append("")
    context_parts.append(principal_with_date)
    context_parts.append("")

    # Add customer persona if present
    customer_persona = agent_details.persona
    if customer_persona.strip():
        context_parts.append("=== CUSTOMER PERSONA ===")
        context_parts.append("This section contains information about the current customer's profile and preferences.")
        context_parts.append("")
        context_parts.append(customer_persona)
        context_parts.append("")

    # Add sub-agent instructions
    sub_agent_instructions = {
        agent_name: prompt
        for agent_name, prompt in agent_details.agent_prompts.items()
        if agent_name != SYNTHESIS_AGENT_KEY
    }
    if sub_agent_instructions:
        context_parts.append("=== SUB-AGENT INSTRUCTIONS ===")
        context_parts.append(
            "These are instructions for specialized sub-agents that may be called by the principal agent."
        )
        context_parts.append("These are NOT your instructions - you are evaluating how well the agents follow these.")
        context_parts.append("")

        for agent_name, prompt in sub_agent_instructions.items():
            # Inject date into sub-agent prompts as well
            context_parts.append(f"--- {agent_name.upper()} AGENT INSTRUCTIONS ---")
            context_parts.append(prompt)
            context_parts.append("")

    # Add conversation history
    context_parts.append("=== CONVERSATION HISTORY ===")
    context_parts.append("This section contains the previous conversation between the customer and agent.")
    context_parts.append("")
    context_parts.append(str(conversation_history))
    context_parts.append("")

    # Add tool calls
    tool_calls_inputs = agent_details.tool_input_parameters
    tool_call_input_types = agent_details.tool_input_types
    tool_calls = agent_details.tool_call_outputs
    context_parts.append("=== TOOL CALL DESCRIPTIONS ===")
    context_parts.append("")
    context_parts.append(str(tool_calls_inputs))
    context_parts.append("")
    context_parts.append("=== TOOL CALL INPUTS ===")
    context_parts.append("")
    context_parts.append(str(tool_call_input_types))
    context_parts.append("")
    context_parts.append("=== TOOL EXECUTION RESULTS ===")
    context_parts.append("")
    context_parts.append(str(tool_calls))
    context_parts.append("")

    _add_conversational_clauses(context_parts)
    _add_clarifying_questions_clause(context_parts)

    context_parts.append("=== END OF CONTEXT ===")

    return "\n".join(context_parts)


def _add_conversational_clauses(context_parts: list[str]) -> None:
    """Add special treatment to some conversational sentences, e.g. greetings.

    Add clauses that explains how to treat parts of response
    used for the purpose of maintaining a natural conversation.

    Args:
        context_parts: List of context string parts to append to.
    """
    context_parts.append("=== GREETINGS ===")
    context_parts.append("")
    context_parts.append(
        "Greetings (e.g., Hi Alice, G'day Bob, etc.) are grounded if they match the name of the persona."
    )
    context_parts.append("")


def _add_clarifying_questions_clause(context_parts: list[str]) -> None:
    """Add clarifying questions clause to context parts.

    Appends a section explaining how to handle clarifying questions in groundedness checks.

    Args:
        context_parts: List of context string parts to append to.
    """
    context_parts.append("=== CLARIFYING QUESTIONS ===")
    context_parts.append("")
    context_parts.append(CLARIFYING_QUESTIONS_CLAUSE)
    context_parts.append("")


def get_tool_call_by_id(tool_calls: list[dict[str, Any]], id_: str) -> dict[str, Any] | None:
    """Gets the tool call object from a list of tool calls by its ID."""
    for tool_call_obj in tool_calls:
        if tool_call_obj.get("id") == id_:
            return tool_call_obj
    return None


def extract_failed_guardrail_names(
    guardrail_result: GuardrailOutputInfo | PrincipalGuardrailFunctionOutput,
) -> list[str]:
    """Extract names of failed guardrails from guardrail result.

    Args:
        guardrail_result: The guardrail result object containing failure information.
                         Can be either GuardrailOutputInfo or PrincipalGuardrailFunctionOutput.

    Returns:
        list[str]: List of guardrail names that failed
    """
    failed_names: list[str] = []

    try:
        # Handle case where we receive a PrincipalGuardrailFunctionOutput object
        # instead of GuardrailOutputInfo directly
        if isinstance(guardrail_result, PrincipalGuardrailFunctionOutput):
            # Extract the GuardrailOutputInfo from PrincipalGuardrailFunctionOutput
            guardrail_data = guardrail_result.output_info
        else:
            # Direct GuardrailOutputInfo object (TypedDict)
            guardrail_data = guardrail_result

        guardrail_name = guardrail_data.get("name", "unknown_guardrail")

        # Handle parallel execution summary format
        if guardrail_name.startswith("parallel_") and isinstance(guardrail_data.get("response"), list):
            response_data = guardrail_data.get("response")
            if response_data is not None:
                summary_data = extract_parallel_execution_summary(response_data)
                if summary_data:
                    failed_names = extract_failed_results_from_summary(summary_data)

        # Handle single guardrail format
        elif guardrail_data.get("name") and guardrail_data.get("status"):
            status = guardrail_data.get("status")
            # Handle both enum values and string values for compatibility
            failed_statuses = [
                "FAILED",
                "ERROR",
                GuardrailStatus.FAILED,
                GuardrailStatus.ERROR,
            ]
            if status in failed_statuses:
                guardrail_name = guardrail_data.get("name", "unknown_guardrail")
                # Map to GuardrailOperators enum value
                mapped_name = map_guardrail_name_to_operator(guardrail_name)
                failed_names.append(mapped_name)

    except Exception as e:
        logger.error(f"Error extracting failed guardrail names: {e}")
        failed_names.append("unknown_guardrail")

    return failed_names


def extract_jailbreak_flag(guardrail_output: PrincipalGuardrailFunctionOutput) -> bool:
    """Extract jailbreak_failed_or_errored flag from guardrail execution output.

    Args:
        guardrail_output: The guardrail output to analyze

    Returns:
        bool: True if jailbreak guardrail failed or errored, False otherwise
    """
    try:
        # Check if this is a jailbreak-related failure
        failed_guardrails = extract_failed_guardrail_names(guardrail_output)
        # Check for both the mapped enum value and the internal name for backward compatibility
        return GuardrailOperators.JAILBREAK in failed_guardrails or "jailbreak_check" in failed_guardrails
    except Exception as e:
        logger.error(f"Error extracting jailbreak flag: {e}")
        # Default to True for safety if we can't determine the failure type
        return True


def extract_parallel_execution_summary(
    response_array: list[Any],
) -> dict[str, Any] | None:
    """Extract and parse parallel execution summary from response array."""
    for item in response_array:
        # Check if this item has the expected structure: {'key': 'parallel_execution_summary', 'value': '...'}
        if isinstance(item, dict) and item.get("key") == "parallel_execution_summary":
            try:
                # Extract and parse the JSON value
                json_value = item.get("value", "{}")
                parsed_data = json.loads(json_value)

                # Check if the parsed data has all_results and is a dict
                if isinstance(parsed_data, dict) and "all_results" in parsed_data:
                    return parsed_data

            except Exception as e:
                logger.error(f"Error parsing parallel execution summary JSON: {e}")

    return None


def extract_failed_results_from_summary(summary_data: dict[str, Any]) -> list[str]:
    """Extract failed guardrail names from parallel execution summary.

    Maps internal guardrail names to GuardrailOperators enum values for
    consistency with dialogue monitoring expectations.
    """
    failed_names: list[str] = []
    all_results = summary_data.get("all_results", [])

    for result in all_results:
        if isinstance(result, dict):
            status = result.get("status")
            if status in ["FAILED", "ERROR"]:
                guardrail_name = result.get("name", "unknown_guardrail")
                # Map to GuardrailOperators enum value
                mapped_name = map_guardrail_name_to_operator(guardrail_name)
                failed_names.append(mapped_name)
    return failed_names


def _fetch_and_validate_trace(langfuse_client: Langfuse) -> tuple[Any, str | None]:
    """Fetch and validate trace from Langfuse.

    Args:
        langfuse_client: The Langfuse client instance

    Returns:
        Tuple of (trace object or None if invalid, trace_id)
    """
    current_trace_id = langfuse_context.get_current_trace_id()
    if not current_trace_id:
        return None, None
    trace = langfuse_client.fetch_trace(current_trace_id)

    if not trace:
        logger.error(f"No trace found for trace ID {current_trace_id}")
        return None, current_trace_id

    if not hasattr(trace, "data"):
        logger.error(f"Invalid trace response format for trace ID {current_trace_id}: missing 'data' attribute")
        return None, current_trace_id

    return trace, current_trace_id


def apply_whitespace_padding(
    context: GuardrailResponseContext,
    attempt: int,
    original_agent_response: str | None,
    original_user_query: str | None,
) -> None:
    """Apply whitespace padding to context for retry attempts."""
    if attempt == 0:
        return
    whitespace_padding = " " * attempt
    if original_agent_response:
        context.agent_response = whitespace_padding + original_agent_response + whitespace_padding
    if original_user_query:
        context.user_query = whitespace_padding + original_user_query + whitespace_padding
    logger.debug(
        f"Retry attempt {attempt + 1} for {context.guardrail_name}: added {attempt} whitespace(s) at beginning and end"
    )


def _parse_extra_body(extra_body_str: str) -> dict[str, Any]:
    """Parse extra_body string into dictionary.

    Args:
        extra_body_str: The extra_body string to parse

    Returns:
        Parsed dictionary or empty dict if parsing fails
    """
    try:
        result = ast.literal_eval(extra_body_str)
        if isinstance(result, dict):
            return result
        else:
            logger.warning(f"extra_body parsed to non-dict type: {type(result)}")
            return {}
    except (ValueError, SyntaxError) as e:
        logger.warning(f"Failed to parse extra_body: {e}")
        return {}


def _parse_tool_call_arguments(arguments_str: str) -> dict[str, Any]:
    """Parse tool call arguments JSON string.

    Args:
        arguments_str: The arguments string to parse

    Returns:
        Parsed arguments dictionary or empty dict if parsing fails
    """
    try:
        result = json.loads(arguments_str)
        if isinstance(result, dict):
            return result
        else:
            logger.warning(f"Tool call arguments parsed to non-dict type: {type(result)}")
            return {}
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse tool call arguments: {e}")
        return {}


def _create_assistant_tool_call(tool_call: dict[str, Any], agent_name: str) -> dict[str, Any] | None:
    """Create assistant tool call object from tool call data.

    Args:
        tool_call: The tool call data
        agent_name: Name of the agent making the call

    Returns:
        Tool call object or None if invalid
    """
    tool_call_id = tool_call.get("id")
    if not tool_call_id:
        return None

    tool_call_func = tool_call.get("function", {})
    name = tool_call_func.get("name", "unknown_tool")
    inputs = _parse_tool_call_arguments(tool_call_func.get("arguments", "{}"))

    return {
        "id": tool_call_id,
        "name": name,
        "caller": agent_name,
        "inputs": inputs,
        "outputs": None,  # Will be filled by tool messages
    }


def _process_assistant_message(
    message: dict[str, Any], agent_name: str, tool_calls_extracted: list[dict[str, Any]]
) -> None:
    """Process assistant message to extract tool calls.

    Args:
        message: The message to process
        agent_name: Name of the agent
        tool_calls_extracted: List to append extracted tool calls to
    """
    tool_calls = message.get("tool_calls", [])

    for tool_call in tool_calls:
        # Check that it is not a duplicate
        tool_call_id = tool_call.get("id")
        if not tool_call_id:
            continue

        existing_tool_call = get_tool_call_by_id(tool_calls_extracted, tool_call_id)
        if existing_tool_call is None:
            assistant_tool_call_obj = _create_assistant_tool_call(tool_call, agent_name)
            if assistant_tool_call_obj:
                tool_calls_extracted.append(assistant_tool_call_obj)


def _process_tool_message(message: dict[str, Any], tool_calls_extracted: list[dict[str, Any]]) -> None:
    """Process tool message to add outputs to existing tool calls.

    Args:
        message: The tool message to process
        tool_calls_extracted: List of extracted tool calls to update
    """
    tool_call_id = message.get("tool_call_id")
    if not tool_call_id:
        return

    tool_call_obj = get_tool_call_by_id(tool_calls_extracted, tool_call_id)
    if tool_call_obj is not None and tool_call_obj.get("outputs") is None:
        tool_call_obj["outputs"] = message.get("content", "")


def _process_internal_messages(
    internal_messages: list[dict[str, Any]],
    agent_name: str,
    tool_calls_extracted: list[dict[str, Any]],
) -> None:
    """Process internal messages to extract tool calls and outputs.

    Args:
        internal_messages: List of messages to process
        agent_name: Name of the agent
        tool_calls_extracted: List to append extracted tool calls to
    """
    for message in internal_messages:
        role = message.get("role")

        if role == "assistant" and message.get("tool_calls"):
            _process_assistant_message(message, agent_name, tool_calls_extracted)
        elif role == "tool":
            _process_tool_message(message, tool_calls_extracted)


def _process_generation_observation(observation: Any, tool_calls_extracted: list[dict[str, Any]]) -> None:
    """Process a GENERATION type observation to extract tool calls.

    Args:
        observation: The observation to process
        tool_calls_extracted: List to append extracted tool calls to
    """
    agent_name = observation.metadata.get("agent_name", "unknown_agent")
    if not hasattr(observation, "model_parameters") or not observation.model_parameters:
        return

    extra_body_str = observation.model_parameters.get("extra_body", "{}")
    extra_body = _parse_extra_body(extra_body_str)

    if not extra_body:
        return

    internal_messages = extra_body.get("messages", [])
    _process_internal_messages(internal_messages, agent_name, tool_calls_extracted)


def _is_langfuse_actual_tool_call(tool_call: dict[str, Any]) -> bool:
    """Check if this is an actual tool call and not a subagent response for Langfuse.

    Args:
        tool_call: The tool call dictionary to check

    Returns:
        bool: True if this is an actual tool call
    """
    name = tool_call.get("name", "").lower()

    # Exclude subagent calls - these typically contain "agent" in the name
    subagent_patterns = [
        "agent",
        "sub_agent",
        "subagent",
        "call_agent",
        "invoke_agent",
    ]

    # Check if this looks like a subagent call
    for pattern in subagent_patterns:
        if pattern in name:
            return False

    # Only include if it has both inputs and outputs
    return tool_call.get("outputs") is not None


## TODO: guardrails response (rewrite) is still using this, which may subject to Langfuse update delay issue, should be replaced by getting tool response from contexts
def get_tool_context_from_langfuse(langfuse_client: Langfuse) -> list[dict[str, Any]]:
    """Extracts actual tool call outputs from a Langfuse session for use in groundedness checking.

    Excludes subagent responses and only includes real tool/function calls.

    Args:
        langfuse_client: The Langfuse client instance.

    Returns:
        List[Dict[str, Any]]: A list of actual tool call dictionaries with complete information.
        Each dictionary contains: id, name, caller, inputs, outputs
        Excludes subagent calls (tools with "agent" in the name).
    """
    trace, current_trace_id = _fetch_and_validate_trace(langfuse_client)
    if not trace:
        return []

    tool_calls_extracted: list[dict[str, Any]] = []

    try:
        for observation in trace.data.observations:
            if observation.type == "GENERATION":
                _process_generation_observation(observation, tool_calls_extracted)

    except Exception as e:
        logger.error(f"Failed to extract tool calls from trace {trace.data.id}: {e}")
        return []

    # Filter to only include actual tool calls (not subagent responses)
    complete_tool_calls = [tool_call for tool_call in tool_calls_extracted if _is_langfuse_actual_tool_call(tool_call)]

    logger.info(
        f"Extracted {len(complete_tool_calls)} actual tool calls (excluding subagent responses) from trace {current_trace_id}"
    )
    return complete_tool_calls


def _has_tool_execution_data(context: RunContextWrapper) -> bool:
    """Check if context has tool execution data available.

    Args:
        context: The RunContextWrapper to check

    Returns:
        bool: True if tool execution data is available
    """
    return hasattr(context, "context") and hasattr(context.context, "tool_execution_data")


def _extract_tool_execution_data(context: RunContextWrapper) -> list[dict[str, Any]]:
    """Extract and validate tool execution data from context.

    Args:
        context: The RunContextWrapper containing tool execution data

    Returns:
        List of validated tool call dictionaries
    """
    tool_calls_extracted: list[dict[str, Any]] = []

    if not _has_tool_execution_data(context):
        logger.warning("Context object has no tool_execution_data - enhanced hooks may not be configured")
        return tool_calls_extracted

    tool_execution_data = context.context.tool_execution_data
    logger.info(f"Found tool_execution_data in context with {len(tool_execution_data)} tool calls")

    if not isinstance(tool_execution_data, list):
        logger.warning(f"tool_execution_data is not a list: {type(tool_execution_data)}")
        return tool_calls_extracted

    for tool_call in tool_execution_data:
        if _is_valid_tool_call_format(tool_call):
            tool_calls_extracted.append(tool_call)
        else:
            logger.warning(f"Invalid tool call format in tool_execution_data: {tool_call}")

    logger.info(f"Successfully loaded {len(tool_calls_extracted)} tool calls from tool_execution_data")
    return tool_calls_extracted


def _is_valid_tool_call_format(tool_call: Any) -> bool:
    """Validate that a tool call has the required format.

    Args:
        tool_call: The tool call object to validate

    Returns:
        bool: True if the tool call has valid format
    """
    return isinstance(tool_call, dict) and all(key in tool_call for key in ["id", "name", "outputs"])


def _is_subagent_pattern_match(name: str) -> bool:
    """Check if tool name matches subagent patterns.

    Args:
        name: The tool name to check

    Returns:
        bool: True if name matches subagent patterns
    """
    subagent_patterns = [
        "agent",
        "sub_agent",
        "subagent",
        "call_agent",
        "invoke_agent",
    ]

    return any(pattern in name for pattern in subagent_patterns)


def _is_subagent_handler(name: str) -> bool:
    """Check if tool name is a specific subagent handler.

    Args:
        name: The tool name to check

    Returns:
        bool: True if name is a subagent handler
    """
    subagent_handlers = [
        "handle_products_request",
        "handle_savings_request",
        "handle_homebuying_request",
        "handle_homeloans_request",
    ]

    return name in subagent_handlers


def _is_actual_tool_call(tool_call: dict[str, Any]) -> bool:
    """Check if this is an actual tool call and not a subagent response.

    Args:
        tool_call: The tool call dictionary to check

    Returns:
        bool: True if this is an actual tool call
    """
    name = tool_call.get("name", "").lower()

    # Exclude subagent calls and handlers
    if _is_subagent_pattern_match(name) or _is_subagent_handler(name):
        return False

    # Include if it has outputs
    outputs = tool_call.get("outputs")
    return outputs is not None and outputs != ""


def _add_docstrings_to_tool_calls(agent: Any, tool_calls: list[dict[str, Any]]) -> None:
    """Add docstrings to tool calls by extracting them from the agent's tools.

    Args:
        agent: The agent instance containing the tools
        tool_calls: List of tool call dictionaries to enhance with docstrings
    """
    try:
        # Get agent tools via SDK
        if not hasattr(agent, "tools") or not agent.tools:
            logger.warning(f"Agent {type(agent).__name__} does not have tools to extract docstrings from.")
            return
        agent_tools = agent.tools

        # Create a mapping of tool name to docstring
        tool_docs = {}
        for tool in agent_tools:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                tool_name = tool.name
                # Use the existing extraction function
                docstring = tool.description
                if docstring:
                    tool_docs[tool_name] = docstring.strip()

        # Add docstrings to matching tool calls
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            if tool_name and tool_name in tool_docs:
                tool_call["tool_description"] = tool_docs[tool_name]

    except Exception as e:
        logger.warning(f"Failed to extract tool docstrings: {e}")


def get_tool_responses_from_context(context: RunContextWrapper, agent: Any = None) -> list[dict[str, Any]]:
    """Extracts actual tool responses from the context and includes tool docstrings for called tools.

    This function gets tool execution data from the enhanced agent hooks that capture
    tool responses directly in the context during execution, and enriches each tool call
    with its documentation.

    Args:
        context: The RunContextWrapper containing tool execution data
        agent: Optional agent instance to extract tool documentation from

    Returns:
        List[Dict[str, Any]]: A list of tool response dictionaries.
        Each dictionary contains: id, name, outputs, docstring (if agent provided)
        Excludes subagent calls (tools with "agent" in the name).
    """
    try:
        logger.debug(f"Context object type: {type(context)}")

        # Extract and validate tool execution data
        tool_calls_extracted = _extract_tool_execution_data(context)

        # Filter to only include actual tool calls (not subagent responses)
        complete_tool_calls = [tool_call for tool_call in tool_calls_extracted if _is_actual_tool_call(tool_call)]

        # Add docstrings to tool calls if agent is provided
        if agent and complete_tool_calls:
            _add_docstrings_to_tool_calls(agent, complete_tool_calls)

        logger.info(
            f"Extracted {len(complete_tool_calls)} actual tool calls from context (total extracted: {len(tool_calls_extracted)})"
        )
        return complete_tool_calls

    except Exception as e:
        logger.error(f"Failed to extract tool calls from context: {e}")
        return []


def get_tool_context_from_response(response: Any) -> list[dict[str, Any]]:
    """Legacy function - now just logs that response is a string and returns empty list.

    Tool data should be extracted from context instead using get_tool_context_from_context.
    """
    logger.debug(f"get_tool_context_from_response called with {type(response)} - this should use context instead")
    return []
