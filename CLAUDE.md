# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

Financial Companion is a multi-agent financial services system built with:

- **Core Agent**: `all_agents/financial_companion_agent.py` - Main orchestrator
- **Sub-Agents**: Products, Payments, Home Loans, Savings agents in respective subdirectories
- **Service Layer**: FastAPI service in `agent_services/financial_companion_agent_service/`
- **UI**: Gradio web interface (`gradio_fc.py`) and native app support
- **Database**: PostgreSQL for session/conversation storage
- **LLM**: AWS Bedrock Claude via gateway
- **Observability**: Langfuse tracing

### Request Flow

1. Gradio UI/Native App → FastAPI Router (port 8081) → Financial Companion Service
2. Agent REST Handler → Conversation Manager → Financial Companion Agent
3. Agent determines appropriate sub-agent and tools
4. Response with UI components flows back through layers

## Development Commands

### Setup

```bash
# Install ALL dependencies including dev tools
uv sync --group dev
```

### Code Quality

```bash
# Format code (using ruff format - preferred)
python common/scripts/format_and_check.py --fix

# Format specific directory bypassing pyproject.toml filtering
python common/scripts/format_and_check.py --dir common/ --fix

# Do not use ruff format directly as it does not take into account pyproject.toml settings

# Legacy black formatter (if needed)
black .

# Lint code
pylint --rcfile=.pylintrc <file_or_directory>

# Type checking
mypy <file_or_directory>

# Pre-commit hooks (black, pylint, trailing whitespace, etc.)
pre-commit run --all-files
```

### Testing

```bash
# Run specific test file
python -m pytest <test_file>

# Run tests in directory
python -m pytest all_agents/task_agents/savings_agent/tests/

# Run with coverage
python -m pytest --cov=<module>
```

## Key Directories

- `all_agents/` - Core agent and sub-agents
  - `tools/` - Shared tools (memory, financial APIs, schema generation)
  - `task_agents/{savings,products,payments,homeloans}_agent/` - Specialized agents
  - `prompts/` - Agent instruction prompts
- `agent_services/financial_companion_agent_service/` - FastAPI REST service
- `evals/` - Evaluation framework with synthetic customers and LLM judges
- `docs/` - Architecture documentation and agent specifications

## Commit Conventions

Follow Data Science Handbook patterns with optional `-ai` suffix (always use -ai if a coding agent is used):

- `feat[-ai]:` - New features
- `fix[-ai]:` - Bug fixes
- `docs[-ai]:` - Documentation
- `refactor[-ai]:` - Code improvements
- `test[-ai]:` - Test changes
- `style[-ai]:` - Formatting
- `chore[-ai]:` - Dependencies/tooling

## Agent Development

Each sub-agent follows the pattern:

- `{agent_name}_agent.py` - Main agent implementation
- `tools/` - Agent-specific tools and API integrations
- `prompts/` - Instruction prompts in markdown
- `tests/` - Unit tests

Common tools in `all_agents/tools/`:

- Memory management (long/short term DB handlers)
- Schema generation for UI components
- Financial service integrations
- RAG and scratchpad utilities

## Pull Requests Review Guidelines

When reviewing code changes, prioritize these areas to improve observability and code quality:

### Pre-commit Hook Compliance

All generated code, code suggestions, and PR review feedback **must conform to the project's pre-commit hooks** (`.pre-commit-config.yaml`) and tool configuration in `pyproject.toml`. Code that would fail any pre-commit check should never be suggested or approved.

The following hooks run automatically on every commit:

| Hook | What it enforces |
|------|------------------|
| `trailing-whitespace` | No trailing spaces or tabs at end of lines |
| `end-of-file-fixer` | Every file ends with exactly one newline |
| `check-yaml` | Valid YAML syntax |
| `check-json` | Valid JSON syntax |
| `markdownlint` | Markdown follows consistent style rules |
| `ruff` (linter) | Linting rules defined in `pyproject.toml` (pycodestyle, Pyflakes, isort, bugbear, bandit security, pep8-naming, pydocstyle Google convention, and more) |
| `ruff-format` | Code formatting — double quotes, space indentation, 120-char line length |
| `mypy` | Strict type checking with `disallow_untyped_defs`, `strict_equality`, and Pydantic plugin |

### Code Style

When giving code suggestions, ensure the code follows these guidelines:

- **Ruff formatting** (preferred over `black`) - 120-char line length, double quotes, space indentation, `auto` line endings
- **No trailing whitespace** - Remove any spaces or tabs at the end of lines
- **Files end with a single newline** - All files must end with exactly one empty line
- **Imports sorted by isort rules** via Ruff `I` rule set — no relative imports (enforced by `TID252`)
- **No `print()` statements** - Enforced by Ruff `T20` rule (use `logger` instead)
- **No commented-out code** - Enforced by Ruff `ERA` rule
- **Google-style docstrings** - Enforced by Ruff `D` rule set with `convention = "google"`
- **Type hints required** - All functions must include parameter and return type hints; `mypy --strict` must pass
- **Descriptive variable names** - pep8-naming (`N`) enforced by Ruff

### PR Review Rules for Code Style

- Reject code that would fail any pre-commit hook listed above
- Flag formatting issues (wrong quotes, line length > 120, trailing whitespace, missing EOF newline)
- Flag missing or incorrect type annotations
- Flag relative imports, `print()` calls, and commented-out code
- Verify imports are sorted according to isort rules
- Ensure new/modified Markdown files pass markdownlint

### Logging & Error Handling

**Already Implemented (no action needed):**

- ✅ **FastAPI routes** - All HTTP requests/responses logged via `LoggingMiddleware`
- ✅ **External API calls** - All service calls logged via `ServiceAPIBase` (GET/POST/PUT/DELETE)
- ✅ **Request tracing** - Correlation IDs automatically added to all logs
- ✅ **Performance metrics** - Request duration automatically logged
- ✅ **Error handling** - Route-level errors handled in `BaseRestHandler`

### Sensitive Data & Privacy

When generating or reviewing code, **never log, print, store in plain text, or expose any Personally Identifiable Information (PII) or Sensitive Personal Information (SPI)**. This includes but is not limited to:

- Customer names, email addresses, phone numbers, dates of birth
- Account numbers, BSBs, card numbers, CVVs
- Account balances, transaction amounts, salary/income figures
- Tax file numbers, Medicare numbers, government IDs
- Passwords, tokens, API keys, secrets
- Physical addresses, IP addresses used for identification

**Code generation rules:**

- Use opaque identifiers (e.g., `user_id`, `session_id`) in log messages instead of real customer data
- Never interpolate PII/SPI into f-strings, format strings, or log statements
- When logging request/response payloads, redact or exclude sensitive fields
- Avoid writing sensitive data to temporary files, caches, or debug outputs

**PR review rules:**

- Flag any log statement, print call, or error message that includes or could include PII/SPI
- Reject code that passes sensitive data into `extra={}` logging context without redaction
- Verify that exception handlers do not leak sensitive data in stack traces or error responses
- Ensure test fixtures and test data do not contain real customer information

**Focus areas for new/enhanced logging:**

- **Business logic operations** - Log key decision points, calculations, and state changes
- **Database operations** - Log complex queries, bulk operations, and transaction boundaries
- **Agent interactions** - Log tool usage, agent decisions, and workflow progression
- **Data transformations** - Log significant data processing and validation steps
- **Background jobs/async operations** - Operations not covered by request middleware

Examples for business logic logging:

```python
from common.logging.core import logger, log_error

def calculate_savings_goal(user_id: str, target_amount: float, timeline_months: int):
    logger.info(f"Calculating savings goal for user {user_id}: ${target_amount} over {timeline_months} months")

    try:
        monthly_required = target_amount / timeline_months
        user_profile = get_user_financial_profile(user_id)

        logger.debug(f"Monthly savings required: ${monthly_required}",
                    extra={"user_id": user_id, "monthly_required": monthly_required})

        if monthly_required > user_profile.disposable_income * 0.5:
            logger.warning(f"High savings rate required for user {user_id}: {monthly_required/user_profile.disposable_income:.1%}",
                          extra={"user_id": user_id, "savings_rate": monthly_required/user_profile.disposable_income})

        recommendation = build_savings_strategy(monthly_required, user_profile)
        logger.info(f"Savings strategy generated for user {user_id}",
                   extra={"user_id": user_id, "strategy_type": recommendation.type})

        return recommendation

    except ValidationError as e:
        log_error(e, context="calculate_savings_goal", user_id=user_id, target_amount=target_amount)
        raise
    except Exception as e:
        log_error(e, context="calculate_savings_goal", user_id=user_id)
        raise
```

### Unit Testing

- **Test coverage for new functions** - Every new function should have corresponding tests
- **Test edge cases and error conditions** - Not just happy path scenarios
- **Mock external dependencies** - Database calls, API calls, file operations
- **Test data validation** - Invalid inputs, boundary conditions, type mismatches
- **Test business logic independently** - Separate from infrastructure concerns
- **Use descriptive test names** that explain the scenario being tested
- **Follow AAA pattern** - Arrange, Act, Assert

Required test scenarios:

```python
def test_calculate_savings_goal_valid_input():
    """Test savings calculation with valid parameters"""

def test_calculate_savings_goal_zero_amount():
    """Test savings calculation handles zero amount gracefully"""

def test_calculate_savings_goal_negative_timeline():
    """Test savings calculation raises error for negative timeline"""

def test_calculate_savings_goal_api_failure():
    """Test savings calculation handles API failures appropriately"""
```

### Feature Flagging & Trunk-Based Development

To support trunk-based development and ensure main branch remains pristine:

- **Use feature flags for incomplete features** - Wrap new functionality in feature flags to allow safe merging
- **Default flags to disabled** - New features should be disabled by default in production
- **Environment-based flag configuration** - Flags should be configurable per environment (dev/test/prod)
- **Clean flag removal** - Remove flags promptly after feature rollout completion
- **Flag testing** - Test both enabled and disabled states of feature flags
- **Backwards compatibility** - Ensure code works with flags in any state

Example feature flag implementation:

```python
from common.configs.app_config_settings import get_feature_flag


def enhanced_savings_calculation(user_id: str, target_amount: float):
  if get_feature_flag("enhanced_savings_v2", default=False):
    # New enhanced calculation logic
    return calculate_savings_with_ai_insights(user_id, target_amount)
  else:
    # Existing stable calculation
    return calculate_savings_goal(user_id, target_amount)
```

### Code Review Checklist

- [ ] New functions have corresponding unit tests
- [ ] Error handling includes appropriate logging
- [ ] External calls are wrapped in try/except blocks
- [ ] Log messages include sufficient context for debugging
- [ ] Tests cover both success and failure scenarios
- [ ] Mocks are used for external dependencies
- [ ] No sensitive information is logged
- [ ] **Feature flags used for incomplete features** - New functionality wrapped in flags
- [ ] **Feature flags default to disabled** - Safe defaults for production deployment
- [ ] **Flag states tested** - Both enabled and disabled paths covered by tests
- [ ] **Backwards compatibility maintained** - Code works regardless of flag state
