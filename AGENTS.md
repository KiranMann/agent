# AI Agents Guide

This file provides comprehensive guidance for AI coding assistants (VS Code Copilot Chat, GitHub Copilot, Claude, etc.) when working with the Financial Companion repository.

## Project Overview

Financial Companion is a sophisticated multi-agent financial services system that helps users with banking, savings, loans, and financial planning. The system uses a modular architecture with specialized agents for different financial domains.

### Core Architecture

```text
├── financial_companion_agent/           # Main agent orchestration
│   ├── financial_companion_agent.py    # Core orchestrator
│   ├── savings_agent/                  # Savings & goals management
│   ├── products_agent/                 # Banking products & recommendations
│   ├── payments_agent/                 # Payments & transfers
│   ├── homeloans_agent/                # Home loan applications & advice
│   ├── principal_agent/                # Customer support & general queries
│   └── tools/                          # Shared utilities & integrations
├── financial_companion_agent_service/  # FastAPI REST service layer
├── gradio_fc.py                        # Web UI interface
├── api_services/                       # External API integrations
└── common/                             # Shared libraries & utilities
```

### Technology Stack

- **Backend**: Python 3.11+, FastAPI, PostgreSQL
- **AI/LLM**: AWS Bedrock (Claude), LangChain framework
- **Frontend**: Gradio web interface, native app support
- **Observability**: Langfuse tracing, structured logging
- **Infrastructure**: Docker, Docker Compose, Tilt for development

## Development Guidelines

### Setup

```bash
# Install ALL dependencies including dev tools
uv sync --group dev
```

### Code Quality Standards

When writing or suggesting code changes:

#### Pre-commit Hook Compliance

All generated code, code suggestions, and PR review feedback **must conform to the project's pre-commit hooks** (`.pre-commit-config.yaml`) and tool configuration in `pyproject.toml`. Code that would fail any pre-commit check should never be suggested or approved.

The following hooks run automatically on every commit:

| Hook                   | What it enforces                                                                                                                                         |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `trailing-whitespace`  | No trailing spaces or tabs at end of lines                                                                                                               |
| `end-of-file-fixer`    | Every file ends with exactly one newline                                                                                                                 |
| `check-yaml`           | Valid YAML syntax                                                                                                                                        |
| `check-json`           | Valid JSON syntax                                                                                                                                        |
| `markdownlint`         | Markdown follows consistent style rules                                                                                                                  |
| `ruff` (linter)        | Linting rules defined in `pyproject.toml` (pycodestyle, Pyflakes, isort, bugbear, bandit security, pep8-naming, pydocstyle Google convention, and more)  |
| `ruff-format`          | Code formatting — double quotes, space indentation, 120-char line length                                                                                 |
| `mypy`                 | Strict type checking with `disallow_untyped_defs`, `strict_equality`, and Pydantic plugin                                                                |

#### Formatting & Style

- **Ruff formatting** (preferred over `black`) - 120-char line length, double quotes, space indentation, `auto` line endings
- **No trailing whitespace** - Remove any spaces or tabs at the end of lines
- **Single newline at EOF** - All files must end with exactly one empty line
- **Imports sorted by isort rules** via Ruff `I` rule set — no relative imports (enforced by `TID252`)
- **No `print()` statements** - Enforced by Ruff `T20` rule (use `logger` instead)
- **No commented-out code** - Enforced by Ruff `ERA` rule
- **Google-style docstrings** - Enforced by Ruff `D` rule set with `convention = "google"`
- **Type hints required** - All functions must include parameter and return type hints; `mypy --strict` must pass
- **Descriptive variable names** - pep8-naming (`N`) enforced by Ruff

#### PR Review Rules for Code Style

- Reject code that would fail any pre-commit hook listed above
- Flag formatting issues (wrong quotes, line length > 120, trailing whitespace, missing EOF newline)
- Flag missing or incorrect type annotations
- Flag relative imports, `print()` calls, and commented-out code
- Verify imports are sorted according to isort rules
- Ensure new/modified Markdown files pass markdownlint

#### Sensitive Data & Privacy

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

#### Error Handling & Logging

```python
from common.logging.core import logger, log_error
from typing import Optional, Dict, Any

def process_financial_data(user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process user financial data with proper logging and error handling."""
    logger.info(f"Processing financial data for user {user_id}",
                extra={"user_id": user_id, "data_keys": list(data.keys())})

    try:
        # Business logic here
        result = perform_calculation(data)

        logger.info(f"Successfully processed data for user {user_id}",
                   extra={"user_id": user_id, "result_type": type(result).__name__})
        return result

    except ValidationError as e:
        log_error(e, context="process_financial_data", user_id=user_id, data=data)
        raise
    except Exception as e:
        log_error(e, context="process_financial_data", user_id=user_id)
        raise
```

#### Testing Requirements

- **Test coverage for new functions** - Every new function should have corresponding tests
- **Test edge cases and error conditions** - Not just happy path scenarios
- **Mock external dependencies** - Database calls, API calls, file operations
- **Test data validation** - Invalid inputs, boundary conditions, type mismatches
- **Test business logic independently** - Separate from infrastructure concerns
- **Use descriptive test names** that explain the scenario being tested
- **Follow AAA pattern** - Arrange, Act, Assert

```python
def test_savings_goal_calculation_with_valid_inputs():
    """Test that savings goal calculation returns correct monthly amount for valid inputs."""

def test_savings_goal_calculation_handles_zero_timeline():
    """Test that savings goal calculation raises appropriate error for zero timeline."""

def test_savings_goal_calculation_with_api_failure():
    """Test that savings goal calculation handles external API failures gracefully."""
```

### Feature Development Patterns

#### Feature Flags for Trunk-Based Development

Always wrap new features in feature flags to support safe merging to main:

```python
from common.configs.app_config_settings import get_feature_flag


def enhanced_savings_recommendation(user_id: str, goals: List[SavingsGoal]) -> Recommendation:
    """Generate savings recommendations with optional AI enhancement."""

    if get_feature_flag("ai_enhanced_savings", default=False):
        # New AI-powered recommendation logic
        return ai_generate_savings_plan(user_id, goals)
    else:
        # Existing stable recommendation logic
        return generate_standard_savings_plan(user_id, goals)
```

#### Agent Development Pattern

When creating or modifying agents, follow this structure:

```python
# {domain}_agent/{domain}_agent.py
from typing import List, Dict, Any, Optional
from common.agent_base import AgentBase
from common.logging.core import logger

class DomainAgent(AgentBase):
    """Agent responsible for {domain} operations and recommendations."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.tools = self._initialize_tools()

    def process_request(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process user request and return structured response."""
        logger.info(f"Processing {self.__class__.__name__} request",
                   extra={"user_input_length": len(user_input), "context_keys": list(context.keys())})

        try:
            # Agent-specific logic
            result = self._handle_domain_request(user_input, context)
            return self._format_response(result)
        except Exception as e:
            log_error(e, context=f"{self.__class__.__name__}.process_request")
            raise
```

### Database Operations

#### Always Use Connection Management

```python
from common.session import get_db_session
from common.logging.core import logger

def update_user_preferences(user_id: str, preferences: Dict[str, Any]) -> bool:
    """Update user preferences in database with proper session management."""

    with get_db_session() as session:
        try:
            logger.info(f"Updating preferences for user {user_id}",
                       extra={"user_id": user_id, "preference_count": len(preferences)})

            # Database operations
            result = session.execute(update_query, {"user_id": user_id, **preferences})
            session.commit()

            logger.info(f"Successfully updated preferences for user {user_id}",
                       extra={"user_id": user_id, "rows_affected": result.rowcount})
            return True

        except Exception as e:
            session.rollback()
            log_error(e, context="update_user_preferences", user_id=user_id)
            raise
```

### API Integration Patterns

#### External Service Calls

```python
from common.services.service_api_base import ServiceAPIBase


class FinancialDataService(ServiceAPIBase):
    """Service for interacting with external financial data APIs."""

    def get_account_balance(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve account balance from external API."""

        endpoint = f"/accounts/{account_id}/balance"

        try:
            response = self.get(endpoint, timeout=30)
            logger.info(f"Retrieved balance for account {account_id}",
                        extra={"account_id": account_id, "status_code": response.status_code})
            return response.json()

        except requests.RequestException as e:
            log_error(e, context="get_account_balance", account_id=account_id)
            return None
```

## Agent-Specific Guidelines

### Savings Agent (`savings_agent/`)

- Focus on goal-based savings, budgeting, and financial wellness
- Integrate with savings goals API and transaction analysis
- Provide actionable recommendations with timeline and progress tracking

### Products Agent (`products_agent/`)

- Handle banking product recommendations (accounts, cards, investments)
- Use customer profile and financial behavior for personalization
- Include eligibility checks and feature comparisons

### Payments Agent (`payments_agent/`)

- Manage transfers, bill payments, and payment scheduling
- Implement strong validation and fraud detection
- Support both domestic and international payment flows

### Home Loans Agent (`homeloans_agent/`)

- Guide users through home loan applications and pre-approvals
- Calculate affordability and provide market insights
- Integrate with property data and lending criteria APIs

### Principal Agent (`principal_agent/`)

- Handle general customer service and account inquiries
- Route complex requests to specialized agents
- Provide account summaries and basic troubleshooting

## Testing Strategy

### Unit Tests

```python
import pytest
from unittest.mock import Mock, patch
from financial_companion_agent.savings_agent.savings_agent import SavingsAgent

class TestSavingsAgent:
    """Test suite for SavingsAgent functionality."""

    @pytest.fixture
    def savings_agent(self):
        """Create SavingsAgent instance for testing."""
        config = {"environment": "test", "debug": True}
        return SavingsAgent(config)

    @patch('api_services.savings_goals_service.get_user_goals')
    def test_calculate_monthly_savings_valid_goal(self, mock_get_goals, savings_agent):
        """Test monthly savings calculation with valid goal parameters."""
        # Arrange
        mock_get_goals.return_value = [{"target": 10000, "timeline_months": 12}]

        # Act
        result = savings_agent.calculate_monthly_savings("user123")

        # Assert
        assert result["monthly_amount"] == 833.33
        mock_get_goals.assert_called_once_with("user123")
```

### Integration Tests

- Test complete request flows from API to response
- Use test database with realistic financial data
- Validate UI component generation and agent handoffs

## Development Workflow

### Pre-commit Checklist

Before committing code, ensure:

- [ ] `black .` - Code formatting applied
- [ ] `pylint --rcfile=.pylintrc .` - Linting passes
- [ ] `mypy .` - Type checking passes
- [ ] `pytest` - All tests pass
- [ ] Feature flags used for incomplete features
- [ ] Logging added for business logic
- [ ] Unit tests written for new functions
- [ ] No sensitive data in logs or code

### Commit Message Format

```text
feat: Add savings goal progress tracking
feat-ai: Implement AI-powered investment recommendations
fix: Resolve home loan eligibility calculation error
test: Add comprehensive savings agent test coverage
docs: Update agent development guidelines
```

### Development Commands

```bash
# Start development environment
docker-compose up

# Format and lint code
black .
pylint --rcfile=.pylintrc <file_or_directory>
mypy <file_or_directory>

# Run tests
python -m pytest <test_file>
python -m pytest --cov=<module>

# Pre-commit hooks
pre-commit run --all-files

# Start with observability
tilt up
```

## Common Patterns & Anti-Patterns

### ✅ Do This

- Use feature flags for new functionality
- Include comprehensive logging with context
- Write tests before implementing features
- Handle errors gracefully with user-friendly messages
- Use type hints and meaningful variable names
- Follow the single responsibility principle

### ❌ Avoid This

- Hardcoding configuration values
- Logging sensitive financial information
- Implementing business logic in API route handlers
- Skipping error handling for external API calls
- Writing functions without corresponding tests
- Using generic exception handling without logging

## Security Considerations

- **Never log sensitive data** - PII, account numbers, balances
- **Validate all inputs** - Especially financial amounts and user IDs
- **Use parameterized queries** - Prevent SQL injection
- **Implement rate limiting** - For external API calls
- **Sanitize user inputs** - Before processing or storage

This guide should help you write high-quality, maintainable code that follows Financial Companion's established patterns and best practices.
