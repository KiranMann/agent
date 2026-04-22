"""Expression node classes for the rule evaluator.

This module provides a hierarchy of expression node classes that represent
different parts of a logical expression tree. These nodes can be used to
build and evaluate complex logical expressions.
"""

from abc import ABC, abstractmethod
from typing import Any, cast


class ExpressionNode(ABC):
    """Base class for all expression tree nodes."""

    @abstractmethod
    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Boolean result of evaluating this node
        """
        pass

    @abstractmethod
    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this node with the given variable values and track failing variables.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean result of evaluating this node
                - Set of variable names that contributed to failure (if the node evaluates to False)
        """
        pass

    @abstractmethod
    def get_variables(self) -> list[str]:
        """Get all variables used in this expression.

        Returns:
            List of variable names used in this expression
        """
        pass

    @abstractmethod
    def to_string(self, indent: int = 0) -> str:
        """Convert this node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this node
        """
        pass


class VariableNode(ExpressionNode):
    """Leaf node representing a policy variable."""

    def __init__(self, variable_name: str):
        """Initialize a variable node.

        Args:
            variable_name: Name of the variable
        """
        self.variable_name = variable_name

    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this variable node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Boolean value of the variable, or False if not found
        """
        if variable_values is None:
            return False
        return bool(variable_values.get(self.variable_name, False))

    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this variable node and track if it fails.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean value of the variable
                - Set containing the variable name if it evaluates to False, empty set otherwise
        """
        if variable_values is None:
            return False, {self.variable_name}
        result = bool(variable_values.get(self.variable_name, False))
        failing_vars = set() if result else {self.variable_name}
        return result, failing_vars

    def get_variables(self) -> list[str]:
        """Get the variable name used in this node.

        Returns:
            List containing the variable name
        """
        return [self.variable_name]

    def to_string(self, indent: int = 0) -> str:
        """Convert this variable node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this variable node
        """
        return f"{' ' * indent}Variable({self.variable_name})"


class NotNode(ExpressionNode):
    """Node representing a logical NOT operation."""

    def __init__(self, child: ExpressionNode):
        """Initialize a NOT node.

        Args:
            child: Child node to negate
        """
        self.child = child

    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this NOT node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Negation of the child node's evaluation
        """
        return not self.child.evaluate(variable_values)

    def _handle_or_child_failure(self, variable_values: dict[str, Any] | None) -> set[str]:
        """Handle the case where a NOT node fails and the child is an OrNode.

        For an OR child that's True, we need variables from branches that evaluated to True.
        We'll collect variables from each True branch.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Set of variable names that contributed to failure
        """
        if not isinstance(self.child, OrNode):
            raise ValueError("Expected child to be an OrNode for this failure handler.")

        failing_vars: set[Any] = set()
        for branch in self.child.children:
            if branch.evaluate(variable_values):
                # This branch contributes to the OR being True
                # Get all variables in this branch that are True in variable_values
                branch_vars = branch.get_variables()
                if variable_values is None:
                    failing_vars.update(branch_vars)
                    continue
                for var in branch_vars:
                    if bool(variable_values.get(var, False)):
                        failing_vars.add(var)
        return failing_vars

    def _handle_and_child_failure(self, variable_values: dict[str, Any] | None) -> set[str]:
        """Handle the case where a NOT node fails and the child is an AndNode.

        For an AND child that's True, all branches must be True.
        All True variables in the AND contribute to failure.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Set of variable names that contributed to failure
        """
        failing_vars = set()
        child_vars = cast("AndNode", self.child).get_variables()
        if variable_values is None:
            failing_vars.update(child_vars)
            return failing_vars
        for var in child_vars:
            if bool(variable_values.get(var, False)):
                failing_vars.add(var)
        return failing_vars

    def _handle_variable_child_failure(self) -> set[str]:
        """Handle the case where a NOT node fails and the child is a VariableNode.

        For a variable child, it's simply the variable itself.

        Returns:
            Set containing the variable name
        """
        return {self.child.variable_name} if isinstance(self.child, VariableNode) else set()

    def _handle_not_child_failure(self, variable_values: dict[str, Any] | None) -> set[str]:
        """Handle the case where a NOT node fails and the child is a NotNode.

        For a NOT child, we need to handle recursively.
        If NOT(NOT(x)) fails, then x is False, so we need variables that made x False.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Set of variable names that contributed to failure
        """
        if not isinstance(self.child, NotNode):
            raise ValueError("Expected child to be a NotNode for this failure handler.")
        _, grandchild_failing_vars = self.child.child.evaluate_with_tracking(variable_values)
        return grandchild_failing_vars

    def _handle_default_child_failure(self, variable_values: dict[str, Any] | None) -> set[str]:
        """Default handler for when a NOT node fails with an unspecified child type.

        Fallback to the current approach for other node types.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Set of variable names that contributed to failure
        """
        failing_vars = set()
        child_vars = self.child.get_variables()
        if variable_values is None:
            failing_vars.update(child_vars)
            return failing_vars
        for var in child_vars:
            if bool(variable_values.get(var, False)):
                failing_vars.add(var)
        return failing_vars

    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this NOT node and track failing variables.

        For NOT nodes, if the result is False, it means the child evaluated to True.
        We need to identify which variables contributed to making the child True.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean result of the NOT operation
                - Set of variable names that contributed to failure
        """
        child_result, _ = self.child.evaluate_with_tracking(variable_values)
        result = not child_result

        # If the NOT node fails (result is False), the child evaluated to True
        if not result:
            # For a NOT node, we need to identify variables that made the child True
            # This depends on the type of the child node
            if isinstance(self.child, OrNode):
                return result, self._handle_or_child_failure(variable_values)
            elif isinstance(self.child, AndNode):
                return result, self._handle_and_child_failure(variable_values)
            elif isinstance(self.child, VariableNode):
                return result, self._handle_variable_child_failure()
            elif isinstance(self.child, NotNode):
                return result, self._handle_not_child_failure(variable_values)
            else:
                return result, self._handle_default_child_failure(variable_values)

        # If the NOT node passes (result is True), no failing variables
        return result, set()

    def get_variables(self) -> list[str]:
        """Get all variables used in this NOT node.

        Returns:
            List of variable names used in the child node
        """
        return self.child.get_variables()

    def to_string(self, indent: int = 0) -> str:
        """Convert this NOT node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this NOT node
        """
        result = f"{' ' * indent}NOT\n"
        result += self.child.to_string(indent + 2)
        return result


class AndNode(ExpressionNode):
    """Node representing a logical AND operation."""

    def __init__(self, children: list[ExpressionNode]):
        """Initialize an AND node.

        Args:
            children: List of child nodes to AND together
        """
        self.children = children

    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this AND node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Boolean result of ANDing all child nodes
        """
        # If variable_values is None, we'll pass None to child evaluations
        return all(child.evaluate(variable_values) for child in self.children)

    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this AND node and track failing variables.

        For AND nodes, if any child fails, those variables contribute to the failure.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean result of the AND operation
                - Set of variable names that contributed to failure
        """
        # If variable_values is None, we'll pass None to child evaluations
        all_pass = True
        failing_vars = set()

        # Evaluate all children, collecting failing variables
        for child in self.children:
            child_result, child_failing_vars = child.evaluate_with_tracking(variable_values)
            if not child_result:
                all_pass = False
                failing_vars.update(child_failing_vars)

        return all_pass, failing_vars

    def get_variables(self) -> list[str]:
        """Get all variables used in this AND node.

        Returns:
            List of variable names used in all child nodes
        """
        variables: set[str] = set()
        for child in self.children:
            variables.update(child.get_variables())
        return list(variables)

    def to_string(self, indent: int = 0) -> str:
        """Convert this AND node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this AND node
        """
        result = f"{' ' * indent}AND\n"
        for child in self.children:
            result += child.to_string(indent + 2) + "\n"
        return result.rstrip()


class OrNode(ExpressionNode):
    """Node representing a logical OR operation."""

    def __init__(self, children: list[ExpressionNode]):
        """Initialize an OR node.

        Args:
            children: List of child nodes to OR together
        """
        self.children = children

    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this OR node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Boolean result of ORing all child nodes
        """
        # If variable_values is None, we'll pass None to child evaluations
        return any(child.evaluate(variable_values) for child in self.children)

    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this OR node and track failing variables.

        For OR nodes, if all children fail, all their failing variables contribute to the failure.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean result of the OR operation
                - Set of variable names that contributed to failure
        """
        # If variable_values is None, we'll pass None to child evaluations
        any_pass = False
        all_failing_vars = set()

        # Evaluate all children
        for child in self.children:
            child_result, child_failing_vars = child.evaluate_with_tracking(variable_values)
            if child_result:
                any_pass = True
            else:
                all_failing_vars.update(child_failing_vars)

        # If no child passed, return all failing variables
        # If any child passed, the OR node passes, so return empty set
        return any_pass, set() if any_pass else all_failing_vars

    def get_variables(self) -> list[str]:
        """Get all variables used in this OR node.

        Returns:
            List of variable names used in all child nodes
        """
        variables: set[str] = set()
        for child in self.children:
            variables.update(child.get_variables())
        return list(variables)

    def to_string(self, indent: int = 0) -> str:
        """Convert this OR node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this OR node
        """
        result = f"{' ' * indent}OR\n"
        for child in self.children:
            result += child.to_string(indent + 2) + "\n"
        return result.rstrip()


class ImpliesNode(ExpressionNode):
    """Node representing a logical IMPLIES operation (if A then B)."""

    def __init__(self, antecedent: ExpressionNode, consequent: ExpressionNode):
        """Initialize an IMPLIES node.

        Args:
            antecedent: The "if" part of the implication
            consequent: The "then" part of the implication
        """
        self.antecedent = antecedent
        self.consequent = consequent

    def evaluate(self, variable_values: dict[str, Any] | None) -> bool:
        """Evaluate this IMPLIES node with the given variable values.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Boolean result of the implication (not A or B)
        """
        # If variable_values is None, we'll pass None to child evaluations
        # A → B is equivalent to ¬A OR B
        antecedent_value = self.antecedent.evaluate(variable_values)
        if not antecedent_value:
            return True  # If antecedent is false, implication is true
        return self.consequent.evaluate(variable_values)

    def evaluate_with_tracking(self, variable_values: dict[str, Any] | None) -> tuple[bool, set[str]]:
        """Evaluate this IMPLIES node and track failing variables.

        For IMPLIES nodes (A → B), it fails only when A is True and B is False.
        In this case, the failing variables come from B.

        Args:
            variable_values: Dictionary mapping variable names to their values

        Returns:
            Tuple containing:
                - Boolean result of the IMPLIES operation
                - Set of variable names that contributed to failure
        """
        # If variable_values is None, we'll pass None to child evaluations
        antecedent_result, _ = self.antecedent.evaluate_with_tracking(variable_values)
        consequent_result, consequent_failing_vars = self.consequent.evaluate_with_tracking(variable_values)

        # A → B is equivalent to ¬A OR B
        # It fails only when A is True and B is False
        result = (not antecedent_result) or consequent_result

        # If the implication fails, it's because the antecedent is True and the consequent is False
        # In this case, the failing variables come from the consequent
        failing_vars = set()
        if not result:
            failing_vars.update(consequent_failing_vars)

        return result, failing_vars

    def get_variables(self) -> list[str]:
        """Get all variables used in this IMPLIES node.

        Returns:
            List of variable names used in both antecedent and consequent
        """
        variables: set[str] = set()
        variables.update(self.antecedent.get_variables())
        variables.update(self.consequent.get_variables())
        return list(variables)

    def to_string(self, indent: int = 0) -> str:
        """Convert this IMPLIES node to a string representation.

        Args:
            indent: Indentation level for pretty printing

        Returns:
            String representation of this IMPLIES node
        """
        result = f"{' ' * indent}IMPLIES\n"
        result += f"{' ' * (indent + 2)}IF\n"
        result += self.antecedent.to_string(indent + 4) + "\n"
        result += f"{' ' * (indent + 2)}THEN\n"
        result += self.consequent.to_string(indent + 4)
        return result
