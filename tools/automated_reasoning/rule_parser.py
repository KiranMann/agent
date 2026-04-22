"""Rule parser for converting policy rule strings into expression trees.

This module provides functionality to parse policy rule strings into
expression trees that can be evaluated against a set of facts.
"""

# Use relative imports for local testing
from common.tools.automated_reasoning.expression_nodes import (
    AndNode,
    ExpressionNode,
    ImpliesNode,
    NotNode,
    OrNode,
    VariableNode,
)

# Constants
IMPLIES_FUNCTION_ARG_COUNT = 2


class RuleParsingError(Exception):
    """Base exception for rule parsing errors."""

    pass


class MissingParenthesisError(RuleParsingError):
    """Exception raised when a parenthesis is missing."""

    pass


class InvalidArgumentError(RuleParsingError):
    """Exception raised when an argument is invalid."""

    pass


class EmptyExpressionError(RuleParsingError):
    """Exception raised when an expression is empty."""

    pass


class RuleParser:
    """Parser for converting policy rule strings into expression trees."""

    @staticmethod
    def _preprocess_rule_string(rule_string: str) -> str:
        """Remove comments and normalize whitespace.

        Args:
            rule_string: The rule string to preprocess.

        Returns:
            The preprocessed rule string.
        """
        # Remove comments (lines starting with #)
        lines = []
        for line in rule_string.split("\n"):
            clean_line = line[: line.index("#")] if "#" in line else line
            if clean_line.strip():  # Only add non-empty lines
                lines.append(clean_line)

        rule_string = " ".join(lines)
        # Normalize whitespace
        rule_string = " ".join(rule_string.split())
        return rule_string

    @staticmethod
    def parse(rule_str: str) -> ExpressionNode:
        """Parse a rule string into an expression tree.

        Args:
            rule_str: The rule string to parse

        Returns:
            The root node of the expression tree

        Raises:
            EmptyExpressionError: If the rule string is empty after preprocessing
            MissingParenthesisError: If there are unmatched parentheses
            InvalidArgumentError: If an argument is invalid
            RuleParsingError: For other parsing errors
        """
        if not rule_str or rule_str.strip() == "":
            # Return a default "true" node (represented as an AND with no children)
            return AndNode([])

        try:
            # Preprocess the rule string to remove comments and normalize whitespace
            rule_str = RuleParser._preprocess_rule_string(rule_str)

            # Parse the expression
            return RuleParser._parse_expression(rule_str)
        except ValueError as e:
            # Convert ValueError to appropriate custom exception
            error_msg = str(e)
            if "Empty expression" in error_msg or "Empty variable name" in error_msg:
                raise EmptyExpressionError(f"Empty expression or variable: {error_msg}") from e
            elif "Unmatched opening parenthesis" in error_msg:
                raise MissingParenthesisError(f"Missing closing parenthesis: {error_msg}") from e
            elif "No arguments" in error_msg or "expects 2 arguments" in error_msg:
                raise InvalidArgumentError(f"Invalid arguments: {error_msg}") from e
            else:
                raise RuleParsingError(f"Error parsing rule: {error_msg}") from e
        except Exception as e:
            # Catch any other exceptions and wrap them
            raise RuleParsingError(f"Unexpected error parsing rule: {e!s}") from e

    @staticmethod
    def _parse_expression(expr_string: str) -> ExpressionNode:
        """Parse an expression string into an expression tree.

        Args:
            expr_string: The expression string to parse.

        Returns:
            The root node of the expression tree.

        Raises:
            EmptyExpressionError: If the expression string is empty
            MissingParenthesisError: If there are unmatched parentheses
            InvalidArgumentError: If an argument is invalid
        """
        expr_string = expr_string.strip()
        if not expr_string:
            raise EmptyExpressionError("Empty expression string")

        try:
            if expr_string.startswith("And("):
                return RuleParser._parse_and_node(expr_string)
            if expr_string.startswith("Or("):
                return RuleParser._parse_or_node(expr_string)
            if expr_string.startswith("Not("):
                return RuleParser._parse_not_node(expr_string)
            if expr_string.startswith("Implies("):
                return RuleParser._parse_implies_node(expr_string)
            var_name = expr_string.strip()
            if not var_name:
                raise EmptyExpressionError("Empty variable name")
            return VariableNode(var_name)
        except (MissingParenthesisError, InvalidArgumentError, EmptyExpressionError):
            raise
        except Exception as e:
            if not isinstance(e, RuleParsingError):
                raise RuleParsingError(f"Unexpected error parsing expression '{expr_string}': {e!s}") from e
            raise

    @staticmethod
    def _parse_nary_args(node_name: str, expr_string: str, paren_open_index: int) -> list[ExpressionNode]:
        """Parse arguments of an n-ary node (And/Or) into a list of child ExpressionNodes.

        Args:
            node_name: Name of the node for error messages (e.g. "And").
            expr_string: Full expression string starting with node_name + "(".
            paren_open_index: Index of the opening parenthesis in expr_string.

        Returns:
            List of parsed child ExpressionNodes.

        Raises:
            MissingParenthesisError: If the closing parenthesis is missing.
            InvalidArgumentError: If no arguments are provided.
        """
        closing_paren_index = RuleParser._find_matching_paren(expr_string, paren_open_index)
        if closing_paren_index == -1:
            raise MissingParenthesisError(f"Unmatched opening parenthesis in {node_name} expression: '{expr_string}'")
        args = RuleParser._split_arguments(expr_string[paren_open_index + 1 : closing_paren_index])
        if not args:
            raise InvalidArgumentError(f"No arguments in {node_name} expression: '{expr_string}'")
        children = []
        for i, arg in enumerate(args):
            try:
                children.append(RuleParser._parse_expression(arg))
            except RuleParsingError as e:
                raise RuleParsingError(f"Error in argument {i + 1} of {node_name} expression: {e!s}") from e
        return children

    @staticmethod
    def _parse_and_node(expr_string: str) -> AndNode:
        """Parse an And(...) expression into an AndNode.

        Args:
            expr_string: Expression string starting with "And(".

        Returns:
            AndNode with parsed children.
        """
        return AndNode(RuleParser._parse_nary_args("And", expr_string, 3))

    @staticmethod
    def _parse_or_node(expr_string: str) -> OrNode:
        """Parse an Or(...) expression into an OrNode.

        Args:
            expr_string: Expression string starting with "Or(".

        Returns:
            OrNode with parsed children.
        """
        return OrNode(RuleParser._parse_nary_args("Or", expr_string, 2))

    @staticmethod
    def _parse_not_node(expr_string: str) -> NotNode:
        """Parse a Not(...) expression into a NotNode.

        Args:
            expr_string: Expression string starting with "Not(".

        Returns:
            NotNode wrapping the parsed child.

        Raises:
            MissingParenthesisError: If the closing parenthesis is missing.
            EmptyExpressionError: If the argument is empty.
        """
        closing_paren_index = RuleParser._find_matching_paren(expr_string, 3)
        if closing_paren_index == -1:
            raise MissingParenthesisError(f"Unmatched opening parenthesis in Not expression: '{expr_string}'")
        arg_string = expr_string[4:closing_paren_index]
        if not arg_string.strip():
            raise EmptyExpressionError(f"Empty argument in Not expression: '{expr_string}'")
        try:
            child = RuleParser._parse_expression(arg_string)
        except RuleParsingError as e:
            raise RuleParsingError(f"Error in argument of Not expression: {e!s}") from e
        return NotNode(child)

    @staticmethod
    def _parse_implies_node(expr_string: str) -> ImpliesNode:
        """Parse an Implies(...) expression into an ImpliesNode.

        Args:
            expr_string: Expression string starting with "Implies(".

        Returns:
            ImpliesNode with parsed antecedent and consequent.

        Raises:
            MissingParenthesisError: If the closing parenthesis is missing.
            InvalidArgumentError: If the argument count is not exactly 2.
        """
        closing_paren_index = RuleParser._find_matching_paren(expr_string, 7)
        if closing_paren_index == -1:
            raise MissingParenthesisError(f"Unmatched opening parenthesis in Implies expression: '{expr_string}'")
        args = RuleParser._split_arguments(expr_string[8:closing_paren_index])
        if len(args) != IMPLIES_FUNCTION_ARG_COUNT:
            raise InvalidArgumentError(
                f"Implies function expects {IMPLIES_FUNCTION_ARG_COUNT} arguments, got {len(args)}: '{expr_string}'"
            )
        try:
            antecedent = RuleParser._parse_expression(args[0])
        except RuleParsingError as e:
            raise RuleParsingError(f"Error in antecedent (first argument) of Implies expression: {e!s}") from e
        try:
            consequent = RuleParser._parse_expression(args[1])
        except RuleParsingError as e:
            raise RuleParsingError(f"Error in consequent (second argument) of Implies expression: {e!s}") from e
        return ImpliesNode(antecedent, consequent)

    @staticmethod
    def _find_matching_paren(s: str, start_index: int) -> int:
        """Find the index of the matching closing parenthesis.

        Args:
            s: The string to search.
            start_index: The index of the opening parenthesis.

        Returns:
            The index of the matching closing parenthesis, or -1 if not found.

        Raises:
            IndexError: If start_index is out of bounds
        """
        if start_index < 0 or start_index >= len(s):
            raise IndexError(f"Start index {start_index} is out of bounds for string of length {len(s)}")

        count = 1  # We start with one opening parenthesis
        for i in range(start_index + 1, len(s)):
            if s[i] == "(":
                count += 1
            elif s[i] == ")":
                count -= 1
                if count == 0:
                    return i
        return -1

    @staticmethod
    def _split_arguments(args_string: str) -> list[str]:
        """Split a comma-separated list of arguments, handling nested parentheses.

        Args:
            args_string: The string containing comma-separated arguments.

        Returns:
            A list of argument strings.

        Raises:
            InvalidArgumentError: If there are unbalanced parentheses in the arguments
        """
        args = []
        current_arg = ""
        paren_count = 0

        for i, char in enumerate(args_string):
            if char == "," and paren_count == 0:
                # End of argument
                if stripped_arg := current_arg.strip():  # Only add non-empty arguments
                    args.append(stripped_arg)
                current_arg = ""
                continue

            current_arg += char
            if char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1
                # Check for unbalanced parentheses
                if paren_count < 0:
                    raise InvalidArgumentError(f"Unbalanced parentheses in arguments at position {i}: '{args_string}'")

        # Check if we have unbalanced parentheses at the end
        if paren_count > 0:
            raise InvalidArgumentError(
                f"Unbalanced parentheses in arguments (missing {paren_count} closing parentheses): '{args_string}'"
            )

        # Add the last argument
        if current_arg.strip():  # Only add non-empty arguments
            args.append(current_arg.strip())

        return args
