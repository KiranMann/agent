"""AccountsEdge API Tools for Financial Companion Agent.

This module provides account context pre-loading functionality using the AccountsEdge API.
It transforms AccountsEdge API responses into a standardized format compatible with the Financial
Companion agent's account data structure.
"""

import traceback
from typing import Any

from agents import RunContextWrapper, function_tool

from apps.companion.all_agents.services.accounts_edge_service import accounts_edge_service
from common.logging.core import logger
from common.tools import ToolContext
from common.tools.product_categories import categorise_product

# Constants
ACCOUNT_MASK_DIGITS = 4  # Number of digits to show when masking account numbers

# Pictogram ID mappings for UI rendering (Currently not rendering a UI, but kept for future use. Additionally, do this in a less 'manual' way down the line.)
PICTOGRAM_MAPPINGS = {
    "ProductsBankAccounts40": [
        "DDA",
        "CDA",
        "SAV",
        "CHK",
        "FCA",
        "MSA",
        "MAS",
        "SDA",
        "TDA",
        "CMA",
        "BUS",
        "ODA",
    ],
    "ProductsCards40": [
        "MCD",
        "VCD",
        "MNS",
        "AMX",
        "DIN",
        "CRC",
        "DBC",
        "VIS",
        "MAS",
        "CCD",
        "CCA",
    ],
    "ProductsHomeLoans40": [
        "HOM",
        "LAH",
        "MTG",
        "HLN",
        "CIL",
        "CAI",
        "LIF",
        "TRV",
        "RES",
        "VAR",
        "FIX",
        "LOC",
        "REF",
    ],
    "ProductsPersonalLoans40": [
        "PLA",
        "LAL",
        "PLN",
        "CAR",
        "UPL",
        "CPL",
        "VEH",
        "BOA",
        "PLS",
    ],
    "FeaturesShares40": [
        "CSL",
        "MFX",
        "FMS",
        "CLS",
        "INV",
        "TRM",
        "STK",
        "BND",
        "ETF",
        "MAN",
    ],
    "ProductsTermDeposits40": ["TDP", "TDA", "FTD", "CTD"],
}


# =============================================================================
# UTILITY FUNCTIONS - General purpose helpers
# =============================================================================


def _mask_account_number(account_number: str | None) -> str:
    """Mask account number to show only last 4 digits.

    Args:
        account_number: Full account number

    Returns:
        Masked account number (e.g., "****9106")
    """
    if not account_number or len(account_number) < ACCOUNT_MASK_DIGITS:
        return "****"
    return f"****{account_number[-ACCOUNT_MASK_DIGITS:]}"


def _mask_sensitive_field(value: str | None) -> str | None:
    """Completely mask a sensitive field.

    Args:
        value: Sensitive value to mask

    Returns:
        Masked string or None
    """
    return "***MASKED***" if value else None


def _get_pictogram_id(product_code: str | None) -> str:
    """Map product code to pictogram ID for UI rendering.

    Args:
        product_code: Product code from AccountsEdge API

    Returns:
        Pictogram ID string for UI rendering
    """
    if not product_code:
        return "ProductsBankAccounts40"
    product_code = product_code.upper()
    for pictogram_id, codes in PICTOGRAM_MAPPINGS.items():
        if product_code in codes:
            logger.debug(f"Mapped product code '{product_code}' to pictogram '{pictogram_id}'")
            return pictogram_id
    logger.debug(f"Unknown product code '{product_code}', using default ProductsBankAccounts40")
    return "ProductsBankAccounts40"


def _extract_monetary_value(
    values: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Extract monetary value (balance or available funds) from AccountsEdge array.

    Args:
        values: List of monetary value objects from AccountsEdge API

    Returns:
        Dict with 'amount' and 'currency' keys, or empty dict if data is missing/incomplete
    """
    if not values or not isinstance(values, list):
        return {}

    # Take first entry (AccountsEdge returns array)
    value = values[0]

    # Require both amount and currency to be present - don't mask missing data with defaults
    if "amount" not in value or "currency" not in value:
        logger.warning(
            f"Incomplete balance data from AccountsEdge API - missing required fields. "
            f"Available fields: {list(value.keys())}"
        )
        return {}

    return {
        "amount": value["amount"],
        "currency": value["currency"],
    }


def _strip_bsb_from_account_number(full_number: str, bsb: str | None) -> str:
    """Strip BSB prefix from full account number if present.

    Args:
        full_number: Full account number that may include BSB prefix
        bsb: BSB code to strip from the account number

    Returns:
        Account number with BSB stripped, or original number if BSB not found
    """
    if not bsb:
        return full_number

    bsb_str = str(bsb).strip()
    full_number_str = full_number.strip()

    if full_number_str.startswith(bsb_str):
        account_part = full_number_str[len(bsb_str) :].lstrip()
        if account_part:  # Ensure we have something left after stripping BSB
            return account_part

    return full_number_str


def _extract_account_number(account: dict[str, Any]) -> str:
    """Extract account number from AccountsEdge account data.

    AccountsEdge provides multiple account number formats:
    - numberWithoutBsb: Account number without BSB (preferred for consistency)
    - number: Full account number with BSB
    - formattedAccountNumber: Formatted display version

    Args:
        account: AccountsEdge account object

    Returns:
        Account number string (without BSB for consistency with Client Services format)

    Raises:
        ValueError: If no valid account number can be extracted
    """
    # Prefer numberWithoutBsb for consistency with Client Services API format
    account_number = account.get("numberWithoutBsb")
    if account_number:
        return str(account_number)

    # Fallback: extract account number from full number by removing BSB prefix
    full_number = account.get("number")
    if full_number:
        return _strip_bsb_from_account_number(str(full_number), account.get("bsb"))

    # If no valid account number found
    account_id = account.get("id", "unknown")
    logger.error(
        f"Cannot extract account number for account ID {account_id}. "
        f"Missing both 'numberWithoutBsb' and 'number' fields."
    )
    raise ValueError(f"No valid account number found for account ID {account_id}")


def _extract_bsb(account: dict[str, Any]) -> str | None:
    """Extract BSB from AccountsEdge account data.

    Args:
        account: AccountsEdge account object

    Returns:
        BSB string or None if not available
    """
    return account.get("bsb")


def _determine_account_status(account: dict[str, Any]) -> str:
    """Determine account status from AccountsEdge account data.

    AccountsEdge doesn't provide explicit status field, so we infer from:
    - isHidden flag: Account is hidden from customer view
    - errorCodes array: Account has errors (e.g., balance unavailable)

    Args:
        account: AccountsEdge account object

    Returns:
        Status string ("Active", "Hidden", or "Error")
    """
    if account.get("isHidden", False):
        return "Hidden"

    error_codes = account.get("errorCodes", [])
    if error_codes and len(error_codes) > 0:
        return "Error"

    return "Active"


# =============================================================================
# PARSE ACCOUNTS EDGE RESPONSE - Main parser and helper
# =============================================================================


def _build_parsed_account(account: dict[str, Any]) -> dict[str, Any]:
    """Build a single parsed account dictionary from AccountsEdge data.

    Args:
        account: Raw account data from AccountsEdge API

    Returns:
        Standardized account dictionary
    """
    return {
        # Core identifiers
        "accountId": account.get("id"),
        "accountNumber": _extract_account_number(account),
        "bsb": _extract_bsb(account),
        "fullAccountNumber": account.get("number", ""),
        # Product information
        "productCode": account.get("productCode", "N/A"),
        "productSubCode": account.get("productSubCode", "N/A"),
        "productName": account.get("productName") or account.get("accountName", "N/A"),
        # Financial data
        "balance": _extract_monetary_value(account.get("balances")),
        "availableFunds": _extract_monetary_value(account.get("availableFunds")),
        # Status and metadata
        "status": _determine_account_status(account),
        "pictogramId": _get_pictogram_id(account.get("productCode")),
        # AccountsEdge-specific fields
        "formattedAccountNumber": account.get("formattedAccountNumber"),
        "formattedMaskedAccountNumber": account.get("formattedMaskedAccountNumber"),
        "actionsAllowed": account.get("actionsAllowed", []),
        "accountTypes": account.get("accountTypes", []),
        "isHidden": account.get("isHidden", False),
        "errorCodes": account.get("errorCodes", []),
        "salesProductId": account.get("salesProductId"),
        # Data source tracking
        "data_source": "accounts_edge",
    }


def parse_accounts_edge_response(
    api_response: dict[str, Any],
) -> list[dict[str, Any]]:
    """Parse AccountsEdge API response into standardized account format.

    Transforms AccountsEdge account data into the same format used by Client Services
    API parser, enabling consistent account handling across different data sources.

    Field Mappings:
        AccountsEdge -> Standardized Format
        - id -> accountId (preserved for reference)
        - numberWithoutBsb/number -> accountNumber
        - bsb -> bsb
        - productCode -> productCode
        - productSubCode -> productSubCode
        - productName/accountName -> productName
        - balances[0] -> balance {amount, currency}
        - availableFunds[0] -> availableFunds {amount, currency}
        - isHidden/errorCodes -> status
        - actionsAllowed -> actionsAllowed (preserved)
        - accountTypes -> accountTypes (preserved)

    Args:
        api_response: Raw response from AccountsEdge API containing 'accounts' array

    Returns:
        List of standardized account dictionaries

    Example:
        >>> response = {"accounts": [{"id": "123", "bsb": "066179", ...}]}
        >>> accounts = parse_accounts_edge_response(response)
        >>> print(accounts[0]["accountNumber"])
        "10257796"
    """
    if not api_response or not isinstance(api_response, dict):
        logger.warning("Invalid AccountsEdge API response: not a dictionary")
        return []

    accounts_array = api_response.get("accounts", [])
    if not accounts_array or not isinstance(accounts_array, list):
        logger.warning("No accounts array found in AccountsEdge API response")
        return []

    logger.info(f"Parsing {len(accounts_array)} accounts from AccountsEdge API")

    parsed_accounts = []
    for account in accounts_array:
        try:
            parsed_account = _build_parsed_account(account)
            parsed_accounts.append(parsed_account)
            logger.debug(f"Parsed account: {parsed_account.get('productName')} ({parsed_account.get('accountNumber')})")

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing AccountsEdge account {account.get('id', 'unknown')}: {e!s}")
            continue

    logger.info(f"Successfully parsed {len(parsed_accounts)} accounts from AccountsEdge API")
    return parsed_accounts


# =============================================================================
# GET ACCOUNTS EDGE ACCOUNTS - Main function and helpers
# =============================================================================


def _get_empty_accounts_response() -> dict[str, Any]:
    """Return empty accounts response structure."""
    return {
        "agent_response": {"accounts": [], "total_accounts": 0},
        "logging_response": {"accounts": [], "total_accounts": 0},
    }


def _filter_inactive_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out hidden and error accounts.

    Args:
        accounts: List of parsed accounts

    Returns:
        Filtered list of active accounts
    """
    pre_filter_count = len(accounts)
    filtered = []
    for account in accounts:
        error_codes = account.get("errorCodes", [])
        if not account.get("isHidden", False) and (not error_codes or len(error_codes) == 0):
            filtered.append(account)

    filtered_out = pre_filter_count - len(filtered)
    if filtered_out > 0:
        logger.info(f"Filtered out {filtered_out} hidden/error accounts")
    return filtered


def _add_product_categories(accounts: list[dict[str, Any]]) -> None:
    """Add product categorization to accounts in-place.

    Args:
        accounts: List of parsed accounts to categorize
    """
    for account in accounts:
        product_code = account.get("productCode")
        product_sub_code = account.get("productSubCode")
        account["productCategory"] = categorise_product(product_code, product_sub_code)


def _build_agent_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build agent response with filtered fields and unmasked account numbers.

    Args:
        accounts: List of parsed accounts

    Returns:
        List of agent-formatted accounts
    """
    return [
        {
            "productName": account.get("productName"),
            "productCategory": account.get("productCategory"),
            "pictogramId": account.get("pictogramId"),
            "accountNumber": account.get("accountNumber"),
            "bsb": account.get("bsb"),
            "productCode": account.get("productCode"),
            "balance": account.get("balance"),
            "availableFunds": account.get("availableFunds"),
        }
        for account in accounts
    ]


def _build_logging_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build logging response with all fields but masked sensitive data.

    Args:
        accounts: List of parsed accounts

    Returns:
        List of logging-formatted accounts with masked sensitive fields
    """
    return [
        {
            **account,
            "accountNumber": _mask_account_number(account.get("accountNumber")),
            "fullAccountNumber": _mask_account_number(account.get("fullAccountNumber")),
            "accountId": _mask_sensitive_field(account.get("accountId")),
        }
        for account in accounts
    ]


def _validate_api_response(response: dict[str, Any]) -> dict[str, Any] | None:
    """Validate AccountsEdge API response.

    Args:
        response: Raw API response

    Returns:
        Error dict if validation fails, None if successful
    """
    if not response.get("result", False):
        error_data = response.get("data", {})
        error_msg = error_data.get("error", "Unknown error") if isinstance(error_data, dict) else "Unknown error"
        logger.error(f"AccountsEdge API call failed: {error_msg}")
        return _get_empty_accounts_response()
    return None


def _validate_api_data(api_data: Any) -> dict[str, Any] | None:
    """Validate API data is a dictionary.

    Args:
        api_data: Data from API response

    Returns:
        Error dict if validation fails, None if successful
    """
    if not isinstance(api_data, dict):
        logger.error(f"AccountsEdge API returned non-dict data type: {type(api_data)}")
        return _get_empty_accounts_response()
    return None


def _process_parsed_accounts(
    parsed_accounts: list[dict[str, Any]], filter_inactive: bool
) -> list[dict[str, Any]] | None:
    """Process and filter parsed accounts.

    Args:
        parsed_accounts: List of parsed accounts
        filter_inactive: Whether to filter inactive accounts

    Returns:
        Processed accounts list, or None if no accounts remain
    """
    if not parsed_accounts:
        logger.warning("No accounts found after parsing")
        return None

    # Apply filtering if enabled
    if filter_inactive:
        parsed_accounts = _filter_inactive_accounts(parsed_accounts)
        if not parsed_accounts:
            logger.warning("No active accounts remaining after filtering")
            return None

    # Add product categorization
    _add_product_categories(parsed_accounts)
    return parsed_accounts


def _build_accounts_response(parsed_accounts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build final accounts response with agent and logging versions.

    Args:
        parsed_accounts: List of processed accounts

    Returns:
        Dict with agent_response and logging_response
    """
    agent_accounts = _build_agent_accounts(parsed_accounts)
    logging_accounts = _build_logging_accounts(parsed_accounts)

    return {
        "agent_response": {
            "accounts": agent_accounts,
            "total_accounts": len(agent_accounts),
        },
        "logging_response": {
            "accounts": logging_accounts,
            "total_accounts": len(logging_accounts),
            "metadata": {"service_used": "accounts_edge"},
        },
    }


async def get_accounts_edge_accounts(
    customer_details: dict[str, Any], user_agent: str, filter_inactive: bool = False
) -> dict[str, Any]:
    """Get customer accounts using AccountsEdge API with product categorization.

    Returns two versions of account data:
    - agent_response: Filtered data for LLM (essential fields only)
    - logging_response: Complete data for observability (all fields masked)

    Args:
        customer_details: Customer details containing dptoken for authentication
        user_agent: User-agent string for API request
        filter_inactive: If True, filters out hidden and error accounts (default: False)

    Returns:
        Dict with 'agent_response' and 'logging_response' keys, each containing account data
    """
    try:
        logger.info("Loading accounts via AccountsEdge API")

        # Call AccountsEdge API
        response = await accounts_edge_service.get_accounts(
            customer_details=customer_details,
            user_agent=user_agent,
        )

        # Validate API response
        error = _validate_api_response(response)
        if error:
            return error

        # Extract and validate account data
        api_data = response.get("data", {})
        error = _validate_api_data(api_data)
        if error:
            return error

        # Type assertion after validation - known it's a dict
        assert isinstance(api_data, dict)

        # Parse accounts
        parsed_accounts = parse_accounts_edge_response(api_data)

        # Process and filter accounts
        processed_accounts = _process_parsed_accounts(parsed_accounts, filter_inactive)
        if processed_accounts is None:
            return _get_empty_accounts_response()

        # Build and return response
        return _build_accounts_response(processed_accounts)

    except (ValueError, ConnectionError, TimeoutError, KeyError) as e:
        logger.error(f"Failed to get customer accounts via AccountsEdge: {e!s}")
        return _get_empty_accounts_response()


# =============================================================================
# LOAD CUSTOMER ACCOUNT CONTEXT - Main function and helpers
# =============================================================================


def _validate_customer_identifiers(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any] | None:
    """Validate customer identifiers are available.

    Args:
        wrapper: Context wrapper with customer identifiers

    Returns:
        Error dict if validation fails, None if successful
    """
    if not wrapper.context.cif_code or not wrapper.context.netbank_id:
        return {
            "error": True,
            "message": "Customer identifiers (CIF code and NetBank ID) not available in context",
        }
    return None


def _check_already_loaded(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any] | None:
    """Check if account context is already loaded.

    Args:
        wrapper: Context wrapper

    Returns:
        Success dict if already loaded, None if not loaded
    """
    if wrapper.context.account_context_loaded:
        logger.info("Account context already loaded, skipping reload")
        return {
            "error": False,
            "message": f"Account context already loaded with {wrapper.context.get_accounts_count()} accounts",
            "accounts_count": wrapper.context.get_accounts_count(),
            "service_used": wrapper.context.account_service_used,
        }
    return None


def _build_customer_details(wrapper: RunContextWrapper[ToolContext]) -> dict[str, Any]:
    """Build customer details dict for AccountsEdge API.

    Args:
        wrapper: Context wrapper with customer data

    Returns:
        Customer details dictionary
    """
    return {
        "cif_code": wrapper.context.cif_code,
        "netbank_id": wrapper.context.netbank_id,
        "dptoken": wrapper.context.dptoken,
    }


def _validate_dptoken(customer_details: dict[str, Any]) -> dict[str, Any] | None:
    """Validate dptoken is available.

    Args:
        customer_details: Customer details dictionary

    Returns:
        Error dict if validation fails, None if successful
    """
    if not customer_details["dptoken"]:
        logger.error("DP token not available in context for AccountsEdge API")
        return {
            "error": True,
            "message": "DP token not available in context. AccountsEdge API requires authentication.",
        }
    return None


def _cache_accounts_in_context(wrapper: RunContextWrapper[ToolContext], agent_accounts: list[dict[str, Any]]) -> None:
    """Cache account data in context.

    Args:
        wrapper: Context wrapper
        agent_accounts: List of agent-formatted accounts
    """
    wrapper.context.customer_accounts = agent_accounts
    wrapper.context.account_context_loaded = True
    wrapper.context.account_service_used = "accounts_edge"


async def load_customer_account_context(
    wrapper: RunContextWrapper[ToolContext],
    filter_inactive: bool = False,
) -> dict[str, Any]:
    """Load customer account context using AccountsEdge API for optimal performance.

    This tool pre-loads all customer account information once and caches it in the
    context for use by all sub-agents, eliminating redundant API calls and reducing
    response latency.

    Args:
        wrapper: The context wrapper for maintaining state
        filter_inactive: If True, filters out hidden and error accounts (default: False)

    Returns:
        Dict containing loading status and summary information in clean JSON format

    Raises:
        ValueError: If customer details are not available in context
        ConnectionError: If AccountsEdge service is unavailable
        TimeoutError: If service requests time out
    """
    # Validate customer identifiers
    error = _validate_customer_identifiers(wrapper)
    if error:
        return error

    # Check if already loaded
    result = _check_already_loaded(wrapper)
    if result:
        return result

    try:
        logger.info("Loading account context for customer via AccountsEdge")

        # Build and validate customer details
        customer_details = _build_customer_details(wrapper)
        error = _validate_dptoken(customer_details)
        if error:
            return error

        # Load accounts from AccountsEdge API
        accounts_data = await get_accounts_edge_accounts(
            customer_details, "FinancialCompanion", filter_inactive=filter_inactive
        )

        # Extract and cache agent response
        agent_response = accounts_data.get("agent_response", {})
        agent_accounts = agent_response.get("accounts", [])
        _cache_accounts_in_context(wrapper, agent_accounts)

        logger.info(f"Account context loaded successfully: {len(agent_accounts)} accounts")

        # Return agent response
        return {
            "accounts": agent_accounts,
            "total_accounts": len(agent_accounts),
            "metadata": {"service_used": "accounts_edge"},
        }

    except (ValueError, ConnectionError, TimeoutError, KeyError, AttributeError) as e:
        logger.error(f"Failed to load account context: {traceback.format_exc()}")
        return {
            "error": True,
            "message": f"Failed to load account context: {e!s}",
        }


# =============================================================================
# GET ACCOUNT HOLDINGS AND BALANCES - Agent-facing tool
# =============================================================================


@function_tool
async def get_account_holdings_and_balances(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any]:
    """Get customer's account holdings and balances.

    Returns summary information for all customer accounts including:
    - Bank accounts (savings, transaction accounts)
    - Credit cards
    - Home loans/mortgages
    - Personal/consumer loans
    - Term deposits
    - Investment accounts

    This tool provides account identifiers (account numbers, BSB) and basic balance information.
    For detailed loan information (rates, repayment schedules, terms, etc.), the account identifiers
    from this tool are required to call mortgage_loan_tools or consumer_loan_tools.

    ACCOUNT FILTERING:
    Returns accounts based on the filter_inactive setting used during context loading.
    If set as true (set as false by default), excludes hidden and error accounts.

    UNDERSTANDING BALANCE vs AVAILABLE FUNDS:
    - Bank Accounts: balance = current balance, availableFunds = amount available to withdraw
    - Credit Cards: balance = current debt owed, availableFunds = credit limit
    - Loans (Home Loans/Mortgages, Personal Loans): balance = remaining balance owed (shown as NEGATIVE number), availableFunds = redraw available (if applicable)

    IMPORTANT - INTERPRETING LOAN BALANCES:
    For home loans and personal loans, the balance.amount field will be NEGATIVE (e.g., -450000.00).
    This negative value represents the remaining loan balance that the customer owes.
    When communicating with customers, always present this as a positive amount (e.g., "$450,000 remaining balance").

    IMPORTANT: When aggregating balances, NEVER mix currencies. Each balance has "amount" and "currency" fields.

    Args:
        wrapper: The context wrapper containing cached account data

    Returns:
        Dict with accounts list, total_accounts count, and metadata
    """
    # If account context not loaded, load it first
    if not wrapper.context.has_account_context():
        logger.info("Account context not loaded, loading now via AccountsEdge API")
        load_result: dict[str, Any] = await load_customer_account_context(wrapper)

        # Check if loading failed
        if load_result.get("error"):
            return load_result

        # Loading succeeded, continue to return the accounts
        logger.info("Account context loaded successfully")

    # Return cached account data
    accounts = wrapper.context.get_customer_accounts()

    # Return filtered data to agent
    return {
        "accounts": accounts,
        "total_accounts": len(accounts),
        "metadata": {
            "data_source": "cached_context",
            "service_used": wrapper.context.account_service_used,
        },
    }
