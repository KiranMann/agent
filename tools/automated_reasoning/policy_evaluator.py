"""Policy evaluator for evaluating policies using expression trees.

This module provides functionality to evaluate policies using expression trees
and identify which variables are causing a policy to fail.
"""

from typing import Any

from common.tools.automated_reasoning.rule_parser import RuleParser


class PolicyEvaluator:
    """Evaluates policies using expression trees and identifies failing variables."""

    def __init__(self, policy_json: dict[str, Any]):
        """Initialize a policy evaluator.

        Args:
            policy_json: The policy JSON containing rules and variables
        """
        self.policy_json = policy_json
        self.rule_tree = RuleParser.parse(policy_json.get("rules", ""))
        self.variables = policy_json.get("variables", [])
        self.variable_map: dict[str, dict[str, Any]] = {var["name"]: var for var in self.variables}

    def evaluate(self, facts: dict[str, Any]) -> bool:
        """Evaluate if the facts satisfy the policy rules.

        Args:
            facts: Dictionary of facts to evaluate against the policy

        Returns:
            True if the policy is satisfied, False otherwise
        """
        return self.rule_tree.evaluate(facts)

    def identify_all_failing_variables(self, facts: dict[str, Any]) -> list[dict[str, Any]]:
        """Identify ALL variables that are contributing to the policy failure.

        This method uses tree traversal to find all variables in a state that
        contributes to the policy failure, rather than just finding a minimal set.

        Args:
            facts: Dictionary of facts to evaluate against the policy

        Returns:
            List of variable dictionaries that are contributing to the policy failure
        """
        # If the policy passes, there are no failing variables
        if self.evaluate(facts):
            return []

        # Use the new evaluate_with_tracking method to get all failing variables
        _, failing_var_names = self.rule_tree.evaluate_with_tracking(facts)

        # Convert variable names to variable dictionaries
        result = []
        for var_name in failing_var_names:
            var_info = self.variable_map.get(var_name, {})
            if var_info and facts.get(var_name) is not None and var_info.get("include_in_reasoning", True):
                result.append(
                    {
                        "name": var_info.get("name", var_name),
                        "value": facts.get(var_name),
                        "description": var_info.get("description", f"Unknown variable: {var_name}"),
                    }
                )
            elif var_name in facts:
                # if var_name is in facts, but it is None, we do not include in the failing variables
                continue
            else:
                # If variable info not found, create a basic entry
                result.append(
                    {
                        "name": var_name,
                        "value": facts.get(var_name),
                        "description": f"Unknown variable: {var_name}",
                    }
                )

        return result
