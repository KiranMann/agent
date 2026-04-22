import re
import sqlite3
import typing as tp

from agents import RunContextWrapper, function_tool

from common.tools import secure_sqlite_executor
from common.tools.util_langfuse import update_tool_observation


def empty_pre_lockdown_callback(_unused_conn: sqlite3.Connection) -> None:
    # We do not need to populate our db
    return


def force_real_numbers(expression: str) -> str:
    """Transform integer literals to real numbers to prevent SQLite integer division.

    This function automatically converts integer literals like '5' to '5.0' to ensure
    that division operations return proper decimal results instead of truncated integers.

    Examples:
        "5/2"                 → "5.0/2.0"           (2.5 instead of 2)
        "abs(-10)"           → "abs(-10.0)"        (preserves function calls)
        "round(3.14159, 2)"  → "round(3.14159, 2.0)" (converts precision param)
        "1e5 + 100"          → "1e5 + 100.0"       (preserves scientific notation)
        "0xFF + 10"          → "0xFF + 10.0"       (preserves hex literals)
        "3.14 + 2"           → "3.14 + 2.0"        (preserves existing decimals)

    Args:
        expression: SQLite mathematical expression string

    Returns:
        Expression with integer literals converted to real numbers
    """
    # Pattern: match standalone (optionally signed) base-10 integer literals in SQLite-ish arithmetic strings,
    # while avoiding floats, scientific notation, identifiers, and common SQLite parameter forms.
    pattern = r"(?<![\w.])(?<![eE])(?<![eE][+-])(?<![?:@$])([+-]?\d+)(?![\w.])"

    # Breakdown:
    # (?<![\w.])     - negative lookbehind (1 char): not preceded by a word char (A-Za-z0-9_) or '.'
    #                  prevents matching inside identifiers (col1), and prevents matching digits in '.5'
    # (?<![eE])      - negative lookbehind (1 char): not preceded by 'e' or 'E'
    #                  prevents matching exponent digits in '1e10' / '1E10' (blocks the '10' part)
    # (?<![eE][+-])  - negative lookbehind (2 chars): not preceded by 'e+'/'e-'/'E+'/'E-'
    #                  prevents matching exponent digits in '1e+10' / '1e-10'
    # (?<![?:@$])    - negative lookbehind (1 char): not preceded by '?', ':', '@', or '$'
    #                  avoids SQLite parameter tokens like '?1', ':p1', '@p1', '$1'
    # ([+-]?\d+)      - capture group: optional leading '+' or '-', then one or more digits (the integer literal)
    # (?![\w.])      - negative lookahead (1 char): not followed by a word char or '.'
    #                  prevents matching the coefficient in scientific notation ('2e3'),
    #                  prevents matching integers that are actually floats ('2.5', '2.'),
    #                  and prevents matching numbers glued to identifiers ('2x', '10foo')
    return re.sub(pattern, r"\1.0", expression)


@function_tool
def calculator_tool(
    wrapper: RunContextWrapper[tp.Any],  # pylint: disable=unused-argument
    calc_expr: str,
    expression_reason: str,
) -> tp.Any:
    """Calculate a mathematical expression.

    Use the SQLITE expression language to frame your calculation.
    calc_expr will be placed into a select statement, and you'll see the result.

    You must ALWAYS use this or another tool to do a calculation,
    never perform mathematics without a tool. Remember that you don't
    need to use **this** tool if another one does the calculating
    (e.g., the sql transaction tool), but AVOID doing your own maths.

    ```
    calculate('2+3') -> "SELECT 2+3 as result" -> 5
    ```

    If you get an error, try again with a modified expression, up to three times.
    The following will **not** work:
     - calculate('sum of all accounts') < BAD - calculate is not a natural language tool
     - calculate('SELECT 2+3') < BAD - calculate does this select internally, so this becomes SELECT SELECT 2+3
     - calculate('[BALANCE_SUM_FROM_ACCOUNTS_CONTEXT]') < BAD AND WRONG - the calculator cannot access other tools
    These will:
     - calculate('1+2+3') < Good
     - calculate('1+(2*3)') < Good
     - calculate('1+(2/3.0)-33+sqrt(2)') < Good

    Remember to ALWAYS use REAL numbers so that integer division does not lead to truncation.
    - calculate('5/2') < BAD - will only return 2, not 2.5 as required
    - calculate('5.0/2.0') < GOOD

    A regex pattern will be run on your input to ensure REAL numbers are used and convert where they weren't.
    This is available in the `transformed_expr` field in the output.

    To help understand the output from this tool, you must also include the reason you are calculating that expression, in `expression_reason`.
    For example: calculate('1+2+3') would have an expression_reason of "sum of bills with cost $1, $2, $3".

    Args:
        wrapper: Context passed in by decorator
        calc_expr: A string which contains the expression you wish the calculator to use
        expression_reason: The reason you are calculating this expression
    """
    # Transform integers to real numbers to prevent integer division truncation
    # While we prompt the agent to use REAL numbers, we use regex to transform an ints.
    transformed_expr = force_real_numbers(calc_expr)

    update_tool_observation(
        wrapper,
        "calculator_tool",
        {
            "calc_expr": calc_expr,
            "transformed_expr": transformed_expr,
            "expression_reason": expression_reason,
        },
    )
    try:
        # There is a race condition on the hook used to create the span and updating the span.
        # We ensure input is returned by including it in the response.
        return {
            "input": calc_expr,
            "transformed": transformed_expr,
            "reason": expression_reason,
            "result": raw_calculator_tool(transformed_expr),
        }
    except sqlite3.OperationalError as e:
        msg = (
            "Calculation failed - you may have passed invalid syntax."
            f" Remember, only pass numeric expressions, like '2+3' or '5*(2+1)'."
            f" Original: {calc_expr}, Transformed: {transformed_expr}."
            f" Does the original expression look right to you?"
        )
        raise ValueError(msg) from e


def raw_calculator_tool(calc_expr: str) -> tp.Any:
    # SECURITY NOTE: Direct string concatenation with user input normally presents
    # SQL injection risk. However, this is intentionally safe because the
    # secure_sqlite_executor operates in a sandboxed environment with no persistent data
    #
    # The alternatives would be something like:
    #  1. A bespoke calculator, but that's a lot of work and attack surface
    #  2. Repurposing an existing library, but these libs generally aren't hardened
    #  3. Something silly involving `eval`
    #
    # So instead we use the already locked down sqlite environment to run the query,
    # knowing that any crash or injection of code will be harmless.
    sql_expr = "SELECT " + calc_expr + " as result"
    raw_result = secure_sqlite_executor.execute_secure_query(
        empty_pre_lockdown_callback,
        sql_expr,
    )
    # Return the first row's 'result' entry
    return raw_result["0"]["result"]
