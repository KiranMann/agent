"""This class implements automated reasoning guardrail for OpenAI-based agents."""

import asyncio
import json
import re
from functools import partial
from typing import Any, TypedDict

from agents import Agent, ModelSettings, RunConfig, Runner
from cvc5 import Kind, Solver, TermManager

from common.configs.app_config_settings import AppConfig, get_app_config
from common.logging.core import logger
from common.models.non_conversation_manager_types import ARPolicyAdherence
from common.tools.automated_reasoning.policy_evaluator import PolicyEvaluator
from common.tools.prompt_reader import Jinja2PromptReader
from common.utils.litellm_utils import get_model


class OpenAIToolCallItem(TypedDict):
    """Represents a tool call item from OpenAI agent execution."""

    type: str
    output: str  # Tool name
    content: str  # Tool result
    tool_call_id: str | None


class OpenAIHandoffItem(TypedDict):
    """Represents a handoff item for multi-agent scenarios."""

    type: str
    target_agent: str
    handoff_data: dict[str, Any]


# Create wrapper class for term operations
class TermWrapper:
    def __init__(self, term: Any, tm: TermManager) -> None:
        """Initialize a wrapped CVC5 term with its term manager.

        Stores the raw CVC5 term and associated `TermManager` so comparison and
        logical helper methods can safely construct derived CVC5 terms while
        preserving manager consistency.

        Args:
            term: The underlying CVC5 term to wrap.
            tm: The `TermManager` used to create and combine CVC5 terms.
        """
        self.term = term
        self.tm = tm

    def __eq__(self, other: Any) -> "TermWrapper":  # type: ignore[override]
        if isinstance(other, TermWrapper):
            other = other.term
        elif isinstance(other, bool):
            other = self.tm.mkBoolean(other)
        elif isinstance(other, int):
            other = self.tm.mkInteger(str(other))
        return TermWrapper(self.tm.mkTerm(Kind.EQUAL, self.term, other), self.tm)

    def __hash__(self) -> int:
        return hash(self.term)


class OpenAIAutomatedReasoningGuardrailBase:
    """Policy-based automated reasoning guardrail for OpenAI agents.

    Validates agent reasoning against formal policy logic using CVC5 SMT solver.
    """

    def __init__(
        self,
        policy_json: dict[str, Any],
        run_config: RunConfig = RunConfig(tracing_disabled=True),
        system_prompt_template: str = "automated_reasoning_extraction_system_prompt.md",
        fact_extraction_prompt_template: str = "automated_reasoning_fact_extraction_prompt.md",
    ):
        """Initialize with policy logic.

        Args:
            policy_json: Policy with 'variables' and 'rules' keys
            run_config: Configuration for running the guardrail agent
            system_prompt_template: Path to system prompt template
            fact_extraction_prompt_template: Path to fact extraction prompt template
        """
        self.prompt_reader = Jinja2PromptReader()
        self.run_config = run_config
        self.policy_json = policy_json
        self.captured_items: list[OpenAIToolCallItem | OpenAIHandoffItem] = []

        # Validate policy structure
        if not self.validate_policy_json(policy_json):
            raise ValueError("Invalid policy JSON structure")

        self.system_prompt_template = self.prompt_reader.read(system_prompt_template)
        self.fact_extraction_prompt_template = self.prompt_reader.read(fact_extraction_prompt_template)

    @staticmethod
    def validate_policy_json(policy_json: dict[str, Any]) -> bool:
        """Validate that the policy JSON has the expected structure."""
        if "variables" not in policy_json or "rules" not in policy_json:
            return False

        if not isinstance(policy_json["variables"], list):
            return False

        for var in policy_json["variables"]:
            if not isinstance(var, dict):
                return False
            for key in ["name", "type", "description"]:
                if key not in var:
                    return False

        return isinstance(policy_json["rules"], str)

    def validate_facts_json(self, facts_json: dict[str, Any]) -> bool:
        """Validate that the facts JSON has values for all expected variables."""
        var_names = [v["name"] for v in self.policy_json.get("variables", [])]
        return all(name in facts_json for name in var_names)

    @staticmethod
    def _chunk_variables_by_concurrency(
        variables: list[dict[str, Any]], concurrency: int
    ) -> list[list[dict[str, Any]]]:
        """Split variables into chunks based on desired concurrency level.

        Args:
            variables: List of variable dictionaries
            concurrency: Number of chunks to create (concurrent operations)

        Returns:
            List of variable chunks
        """
        if not variables or concurrency <= 0:
            return [variables] if variables else []

        if concurrency >= len(variables):
            # If concurrency is greater than or equal to variable count,
            # create one chunk per variable
            return [[var] for var in variables]

        # Calculate chunk size to distribute variables evenly
        chunk_size = len(variables) // concurrency
        remainder = len(variables) % concurrency

        chunks = []
        start_idx = 0

        for i in range(concurrency):
            # Add one extra variable to the first 'remainder' chunks
            current_chunk_size = chunk_size + (1 if i < remainder else 0)
            end_idx = start_idx + current_chunk_size

            if start_idx < len(variables):
                chunks.append(variables[start_idx:end_idx])
                start_idx = end_idx

        return [chunk for chunk in chunks if chunk]  # Filter out empty chunks

    @staticmethod
    async def _run_fact_extraction_attempt(
        fact_agent: Agent,
        input_text: str,
        variables_chunk: list[dict[str, Any]],
        chunk_id: int,
    ) -> dict[str, Any]:
        result = await Runner.run(
            fact_agent,
            input_text,
            run_config=RunConfig(tracing_disabled=True),
        )

        if not result.final_output or not str(result.final_output).strip():
            return {v["name"]: None for v in variables_chunk}

        # Extract JSON from response, handling markdown code blocks
        response_text = str(result.final_output).strip()

        # Remove markdown code block formatting if present
        code_block_pattern = r"```(?:json_response|json|javascript|js)?\s*(.*?)```"
        match = re.search(code_block_pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            response_text = match.group(1).strip()

        chunk_facts = json.loads(response_text)

        # Simplified response unwrapping - only check for common wrapper patterns
        if isinstance(chunk_facts, dict):
            for wrapper_key in ["json_response", "parameters", "variables", "result", "data"]:
                if wrapper_key in chunk_facts and isinstance(chunk_facts[wrapper_key], dict):
                    logger.debug(
                        f"Unwrapped response in fact extraction using key '{wrapper_key}' for chunk {chunk_id}"
                    )
                    chunk_facts = chunk_facts[wrapper_key]
                    break
        else:
            raise ValueError(f"Expected dictionary, got {type(chunk_facts)}")

        # Ensure all variables in this chunk have values (even if None)
        return {v["name"]: chunk_facts.get(v["name"], None) for v in variables_chunk}

    async def _extract_facts_chunk(
        self,
        variables_chunk: list[dict[str, Any]],
        question: str,
        conversation: str = "",
        chunk_id: int = 0,
    ) -> dict[str, Any]:
        """Extract facts for a specific chunk of variables."""
        if not variables_chunk:
            return {}

        var_descriptions = "\n".join(f"'{v['name']}' (True/False/None) - {v['description']}" for v in variables_chunk)
        input_text = f"Question: {question}\n\nConversation: {conversation}" if conversation else question
        system_prompt = self.prompt_reader.render(
            self.fact_extraction_prompt_template, {"var_descriptions": var_descriptions}
        )

        try:
            fact_agent = Agent(
                name=f"FactExtractor_Chunk_{chunk_id}",
                instructions=system_prompt,
                model=get_model(),
                model_settings=ModelSettings(temperature=0),
            )

            for _ in range(2):  # Retry up to 2 times
                try:
                    return await self._run_fact_extraction_attempt(
                        fact_agent=fact_agent,
                        input_text=input_text,
                        variables_chunk=variables_chunk,
                        chunk_id=chunk_id,
                    )
                except json.JSONDecodeError as json_err:
                    logger.warning(
                        f"Chunk {chunk_id}: JSON decode error during fact extraction, retrying... Error: {json_err}"
                    )
                    # response_text lives inside the attempt function now, so keep generic logging here
                    continue  # Retry on JSON decode error

            logger.error(f"Chunk {chunk_id}: Failed to extract facts after 2 retries.")
            return {v["name"]: None for v in variables_chunk}

        except Exception as e:
            logger.error(f"Encountered unexpected error during fact extraction: {e}")
            return {v["name"]: None for v in variables_chunk}

    async def _extract_facts_parallel(self, question: str, conversation: str = "") -> dict[str, Any]:
        """Extract facts using parallel processing with configurable concurrency.

        Args:
            question: User input question
            conversation: Full conversation including agent response

        Returns:
            Dictionary mapping variable names to extracted values
        """
        config = get_app_config()
        variables = self.policy_json.get("variables", [])

        if not variables:
            return {}

        # Get concurrency level from configuration
        concurrency = config.FACT_EXTRACTION_CONCURRENCY

        # Split variables into chunks based on concurrency
        variable_chunks = self._chunk_variables_by_concurrency(variables, concurrency)

        if not variable_chunks:
            return {}

        # Process chunks concurrently
        try:
            tasks = [
                self._extract_facts_chunk(chunk, question, conversation, i) for i, chunk in enumerate(variable_chunks)
            ]

            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Merge results from all chunks
            merged_facts: dict[str, Any] = {}

            for i, result in enumerate(chunk_results):
                if isinstance(result, BaseException):
                    failed_chunk = variable_chunks[i]
                    logger.error(
                        f"Fact extraction chunk {i} failed with error: {result}. "
                        f"Affected variables: {[v['name'] for v in failed_chunk]}"  # pylint: disable=inconsistent-quotes
                    )
                    # Add None values for variables in failed chunk
                    for v in failed_chunk:
                        merged_facts[v["name"]] = None
                else:
                    merged_facts.update(result)

            # Ensure all variables have entries (even if None)
            for v in variables:
                if v["name"] not in merged_facts:
                    merged_facts[v["name"]] = None

            return merged_facts

        except Exception as e:
            logger.error(f"Error in parallel fact extraction: {e}")
            # Fallback: return None for all variables
            return {v["name"]: None for v in variables}

    async def extract_facts(self, question: str, conversation: str = "") -> dict[str, Any]:
        """Extract variable values from question and conversation using LLM.

        Uses parallel processing when FACT_EXTRACTION_PARALLEL_ENABLED is True,
        otherwise falls back to the original sequential implementation.

        Args:
            question: User input question
            conversation: Full conversation including agent response

        Returns:
            Dictionary mapping variable names to extracted values
        """
        config = get_app_config()

        # Use parallel processing if enabled
        if config.FACT_EXTRACTION_PARALLEL_ENABLED:
            return await self._extract_facts_parallel(question, conversation)

        # Original sequential implementation for backward compatibility
        variables = self.policy_json.get("variables", [])
        var_descriptions = "\n".join(
            f"'{v['name']}' (True/False/None) - {v['description']}"  # pylint: disable=inconsistent-quotes
            for v in variables
        )

        input_text = f"Question: {question}\n\nConversation: {conversation}" if conversation else question

        system_prompt = self.prompt_reader.render(
            self.fact_extraction_prompt_template, {"var_descriptions": var_descriptions}
        )

        try:
            fact_agent = Agent(
                name="FactExtractor",
                instructions=system_prompt,
                model=get_model(),
                model_settings=ModelSettings(temperature=0),
            )

            result = await Runner.run(fact_agent, input_text, run_config=RunConfig(tracing_disabled=True))

            if not result.final_output or not str(result.final_output).strip():
                return {v["name"]: None for v in variables}

            # Extract JSON from response, handling markdown code blocks
            response_text = str(result.final_output).strip()

            # Remove markdown code block formatting if present
            # Pattern to match code blocks with optional language specifiers
            code_block_pattern = r"```(?:json_response|json|javascript|js)?\s*(.*?)```"
            match = re.search(code_block_pattern, response_text, re.DOTALL | re.IGNORECASE)

            if match:
                response_text = match.group(1).strip()

            facts_dict: dict[str, Any] = json.loads(response_text)
            return facts_dict

        except json.JSONDecodeError as json_err:
            logger.error(f"Error parsing JSON after markdown cleanup: {json_err}")
            return {v["name"]: None for v in variables}
        except Exception as e:
            logger.error(f"Error extracting facts: {e}")
            return {v["name"]: None for v in variables}

    def get_items(self, agent_output: dict[str, Any]) -> list[OpenAIToolCallItem | OpenAIHandoffItem]:
        """Extract tool calls and handoff items from OpenAI agent output.

        Args:
            agent_output: Dictionary containing agent execution results

        Returns:
            List of items representing tool calls and handoffs
        """
        items: list[OpenAIToolCallItem | OpenAIHandoffItem] = []

        # Extract tool calls from agent output
        if "tool_calls" in agent_output:
            for tool_call in agent_output["tool_calls"]:
                tool_item: OpenAIToolCallItem = {
                    "type": "tool_call",
                    "output": tool_call.get("name", ""),
                    "content": tool_call.get("result", ""),
                    "tool_call_id": tool_call.get("id"),
                }
                items.append(tool_item)

        self.captured_items = items
        return items

    # Add logical operators
    @staticmethod
    def _and_func(*args: Any, tm: TermManager) -> TermWrapper:
        unwrapped = [arg.term if isinstance(arg, TermWrapper) else arg for arg in args]
        return TermWrapper(tm.mkTerm(Kind.AND, *unwrapped), tm)

    @staticmethod
    def _or_func(*args: Any, tm: TermManager) -> TermWrapper:
        unwrapped = [arg.term if isinstance(arg, TermWrapper) else arg for arg in args]
        return TermWrapper(tm.mkTerm(Kind.OR, *unwrapped), tm)

    @staticmethod
    def _implies_func(a: Any, b: Any, tm: TermManager) -> TermWrapper:
        a_term = a.term if isinstance(a, TermWrapper) else a
        b_term = b.term if isinstance(b, TermWrapper) else b
        return TermWrapper(tm.mkTerm(Kind.IMPLIES, a_term, b_term), tm)

    @staticmethod
    def _not_func(a: Any, tm: TermManager) -> TermWrapper:
        a_term = a.term if isinstance(a, TermWrapper) else a
        return TermWrapper(tm.mkTerm(Kind.NOT, a_term), tm)

    def _create_cvcs_variables(self, individual_sort: Any, tm: TermManager) -> dict[str, Any]:
        """Create CVC5 variable terms from policy variable definitions.

        Builds a context dictionary keyed by policy variable name, where each value is
        a CVC5 constant created using the variable's declared type in
        `self.policy_json["variables"]`.

        Supported policy types:
        - `bool` -> Boolean sort
        - `int` -> Integer sort
        - `real` -> Real sort
        - `individual` / `string` -> `individual_sort` uninterpreted sort

        Args:
            individual_sort: Uninterpreted sort used for `individual` and `string` variables.
            tm: CVC5 `TermManager` used to create constants and sorts.

        Returns:
            A dictionary mapping variable names to CVC5 constant terms.

        Raises:
            ValueError: If a policy variable has an unsupported type.
        """
        cvc_ctx = {}
        for v in self.policy_json["variables"]:
            t = v["type"].lower() if isinstance(v["type"], str) else v["type"]

            if t == "bool":
                cvc_ctx[v["name"]] = tm.mkConst(tm.getBooleanSort(), v["name"])
            elif t == "int":
                cvc_ctx[v["name"]] = tm.mkConst(tm.getIntegerSort(), v["name"])
            elif t == "real":
                cvc_ctx[v["name"]] = tm.mkConst(tm.getRealSort(), v["name"])
            elif t in ["individual", "string"]:
                cvc_ctx[v["name"]] = tm.mkConst(individual_sort, v["name"])
            else:
                raise ValueError(f"Unsupported type: {t}")

        return cvc_ctx

    def check_satisfiability(self, facts_json: dict[str, Any]) -> dict[str, Any]:
        """Check policy satisfiability using CVC5 SMT solver.

        Args:
            facts_json: Dictionary mapping variable names to extracted values

        Returns:
            Dictionary with solver verdict and details
        """
        try:
            # Initialize CVC5
            tm = TermManager()
            slv = Solver(tm)
            slv.setOption("tlimit", "5000")

            # Create base sorts
            individual_sort = tm.mkUninterpretedSort("Individual")

            # Create CVC5 variables
            cvc_ctx = self._create_cvcs_variables(individual_sort, tm)

            # Create evaluation scope
            scope: dict[str, Any] = {}
            for name, var in cvc_ctx.items():
                scope[name] = TermWrapper(var, tm)

            scope.update(
                {
                    "And": partial(OpenAIAutomatedReasoningGuardrailBase._and_func, tm=tm),
                    "Or": partial(OpenAIAutomatedReasoningGuardrailBase._or_func, tm=tm),
                    "Implies": partial(OpenAIAutomatedReasoningGuardrailBase._implies_func, tm=tm),
                    "Not": partial(OpenAIAutomatedReasoningGuardrailBase._not_func, tm=tm),
                }
            )

            # Parse and assert rule expression
            rule_expr = eval(self.policy_json["rules"], scope)  # pylint: disable=eval-used # noqa: S307
            rule_term = rule_expr.term if isinstance(rule_expr, TermWrapper) else rule_expr
            slv.assertFormula(rule_term)

            # Add concrete facts
            for name, value in facts_json.items():
                if value is None or name not in cvc_ctx:
                    continue

                var = cvc_ctx[name]

                if var.getSort().isBoolean():
                    slv.assertFormula(tm.mkTerm(Kind.EQUAL, var, tm.mkBoolean(bool(value))))
                elif var.getSort().isInteger():
                    slv.assertFormula(tm.mkTerm(Kind.EQUAL, var, tm.mkInteger(str(value))))
                elif var.getSort().isReal():
                    slv.assertFormula(tm.mkTerm(Kind.EQUAL, var, tm.mkReal(str(value))))
                else:
                    const_val = tm.mkConst(var.getSort(), str(value))
                    slv.assertFormula(tm.mkTerm(Kind.EQUAL, var, const_val))

            # Check satisfiability
            verdict = slv.checkSat()

            return {
                "verdict": str(verdict),
                "is_sat": verdict.isSat(),
                "is_unsat": verdict.isUnsat(),
                "is_unknown": verdict.isUnknown(),
            }

        except Exception as e:
            return {
                "verdict": "error",
                "error": str(e),
                "is_sat": False,
                "is_unsat": False,
                "is_unknown": True,
            }

    async def run_guardrail(
        self,
        input_question: str,
        conversation: str = "",
    ) -> ARPolicyAdherence:
        """Run the automated reasoning guardrail.

        Args:
            input_question: User's input question
            conversation: Conversation history

        Returns:
            ARPolicyAdherence with reasoning and deviation flag
        """
        if AppConfig.QUALITY_GUARDRAIL != "AutomatedReasoning":
            return ARPolicyAdherence(
                reasoning='Automated reasoning check is disabled. Configure QUALITY_GUARDRAIL to be "AutomatedReasoning" to enable it.',
                policy_variables={},
                deviation=False,
            )

        # Step 1: Extract facts from the question and conversation
        facts = await self.extract_facts(input_question, conversation)

        # Step 2: Validate facts
        if not self.validate_facts_json(facts):
            return ARPolicyAdherence(
                reasoning="Invalid facts extracted from question",
                policy_variables={},
                deviation=True,
            )

        # Step 3: Check satisfiability using CVC5
        solver_result = self.check_satisfiability(facts)

        # Determine if there's a policy deviation
        deviation = solver_result.get("is_unsat", False)

        # Initialize AR policy evaluator
        policy_evaluator = PolicyEvaluator(self.policy_json)

        # Identify failing variables if there's a deviation
        failed_policy_variables = []
        if deviation:
            failed_policy_variables = policy_evaluator.identify_all_failing_variables(facts)

        # format failed variables for reasoning message
        failed_policy_variables_str = "\n\n".join(
            f"**{var.get('name')}** \n - value: {var.get('value')}\n - description: {var.get('description')}"
            for var in failed_policy_variables
        )

        # Generate a simple reasoning message based on deviation
        reasoning = (
            "Response complies with policy."
            if not deviation
            else f"Guardrail detected policy deviation. Failing variables:\n {failed_policy_variables_str}"
        )

        # Return the result without using LLM for final evaluation
        return ARPolicyAdherence(
            reasoning=reasoning,
            policy_variables=facts,
            deviation=deviation,
        )
