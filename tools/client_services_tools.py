"""Principal Agent Client Services Tools for Financial Companion Agent.

This module provides account context pre-loading functionality using the Client Services API,
eliminating the need for redundant API calls across sub-agents by loading account data
once and sharing it through the context.

# NOTE: Being replaced by accounts_edge_tools.py using Accounts Edge API for joint accounts.
    This module has been deprecated, but will be removed in future releases.
"""

import asyncio
import traceback
import uuid
from datetime import datetime
from typing import Any, cast

from agents import RunContextWrapper, function_tool

# Import API services directly
from apps.companion.all_agents.services import commbank_client_service
from common.logging.core import logger
from common.tools import ToolContext
from common.tools.product_categories import categorise_product
from common.tools.util_langfuse import update_tool_observation

# Pictogram ID mappings for UI rendering (same as account_services_tool.py)
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


def _get_pictogram_id(product_code: str | None) -> str:
    """Map product code to pictogram ID for UI rendering."""
    if not product_code:
        return "ProductsBankAccounts40"
    product_code = product_code.upper()
    for pictogram_id, codes in PICTOGRAM_MAPPINGS.items():
        if product_code in codes:
            logger.debug(f"Mapped product code '{product_code}' to pictogram '{pictogram_id}'")
            return pictogram_id
    logger.debug(f"Unknown product code '{product_code}', using default ProductsBankAccounts40")
    return "ProductsBankAccounts40"


# Role filters (Used to filter single vs co owners etc.)
# From this confluence page: https://commbank.atlassian.net/wiki/spaces/DEX/pages/1519009101/Roles+used+in+CAR+Entitlements
ROLE_FILTERS = [
    "Account_HOLD",  # Sole Owner
    "Card_HOLD",  # Primary (Card Holder)
    "Service_CO_HOLD",  # Co-Owner
    "Fund_HOLD",  # Holder of funds
    "Service_HOLD",  # Owner of funds
]

# Inactive statuses for filtering out accounts
INACTIVE_STATUSES = {
    "Written Off",
    "Lost",
    "Closed",
    "Suspended",
    "Cancelled",
    "Dormant",
}

# Account number parsing constant
BSB_LENGTH = 6  # Australian BSB is always 6 digits
ACCOUNT_MASK_DIGITS = 4  # Number of digits to show when masking account numbers


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


def _filter_active_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter accounts to include only active ones."""
    # Convert both status and inactive statuses to uppercase for case-insensitive comparison
    inactive_statuses_upper = {status.upper() for status in INACTIVE_STATUSES}
    return [account for account in accounts if account.get("status", "").upper() not in inactive_statuses_upper]


def _filter_accounts_by_roles(accounts: list[dict[str, Any]], valid_roles: list[str]) -> list[dict[str, Any]]:
    """Filter accounts to include only those with valid customer roles."""
    if not valid_roles:
        return accounts

    valid_roles_upper = {role.upper() for role in valid_roles}

    filtered_accounts = []
    for account in accounts:
        customers = account.get("Customers", [])
        has_valid_role = False

        for customer in customers:
            roles = customer.get("Roles", [])
            if any(role.upper() in valid_roles_upper for role in roles):
                has_valid_role = True
                break

        if has_valid_role:
            filtered_accounts.append(account)

    return filtered_accounts


def _create_account_from_role_data(account: dict[str, Any]) -> dict[str, Any]:
    """Create account dictionary from role endpoint data."""
    account_number = account.get("Number")
    role_bsb = account.get("Bsb", "")

    # Extract customer roles
    customers = account.get("Customers", [])
    all_roles = []
    for customer in customers:
        all_roles.extend(customer.get("Roles", []))

    return {
        "accountNumber": account_number,
        "bsb": role_bsb if role_bsb else "N/A",
        "fullAccountNumber": "",
        "productCode": "N/A",
        "productName": account.get("ProductName", "N/A"),
        "productSubCode": "N/A",
        "balance": {},
        "availableFunds": {},
        "status": "N/A",
        "customerRoles": all_roles,
        "customers": customers,
        "data_source": "role_only",
        "has_bsb": bool(role_bsb),
    }


def _update_account_with_balance_data(account_data: dict[str, Any], balance_account: dict[str, Any]) -> None:
    """Update account data with balance endpoint information."""
    # Extract balance and funds arrays (API returns arrays, take first element)
    balance_array = balance_account.get("Balance", [])
    balance = balance_array[0] if balance_array else {}

    funds_array = balance_account.get("AvailableFunds", [])
    available_funds = funds_array[0] if funds_array else {}

    account_data.update(
        {
            "fullAccountNumber": balance_account.get("Number"),
            "productCode": balance_account.get("ProductCode", "N/A"),
            "productSubCode": balance_account.get("ProductSubCode", "N/A"),
            "balance": balance,
            "availableFunds": available_funds,
            "status": balance_account.get("Status", "N/A"),
            "data_source": "combined",
        }
    )


def _match_balance_with_role_account(full_account_number: str, role_account_number: str, has_bsb: bool) -> bool:
    """Check if balance account matches role account using appropriate strategy."""
    if has_bsb:
        # Role account has BSB - check if full account ends with role account number
        return len(
            full_account_number
        ) >= BSB_LENGTH + 1 and full_account_number.endswith(  # Safety check: BSB + at least 1 account digit
            role_account_number
        )
    else:
        # No BSB in role view - but balance view might have BSB prefix for loans
        # Try direct match first, then try matching if balance account ends with role account
        # This handles personal loans where balance view can show "BSB+AccountNumber" but role view shows just "AccountNumber"
        return full_account_number == role_account_number or (
            len(full_account_number) > len(role_account_number) and full_account_number.endswith(role_account_number)
        )


def _merge_account_data(
    balance_accounts: list[dict[str, Any]], role_accounts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge account data from balance and role endpoints using smart matching.

    Strategy: Start with role accounts (definitive BSB info) and match balance accounts.
    """
    logger.info(f"Merging accounts: {len(balance_accounts)} balance + {len(role_accounts)} role accounts")

    account_map = {}

    # Process role accounts first - they have definitive BSB information
    for account in role_accounts:
        account_number = account.get("Number")
        if account_number:
            account_map[account_number] = _create_account_from_role_data(account)

    # Match balance accounts with role accounts
    matched_count = 0
    for balance_account in balance_accounts:
        full_account_number = balance_account.get("Number")
        if not full_account_number:
            continue

        # Try to match with existing role accounts
        matched = False
        for role_account_number, role_data in account_map.items():
            if _match_balance_with_role_account(full_account_number, role_account_number, role_data["has_bsb"]):
                _update_account_with_balance_data(role_data, balance_account)
                matched = True
                matched_count += 1
                break

        if not matched:
            logger.warning(
                f"Balance account {_mask_account_number(full_account_number)} not found in role accounts. "
                f"This may indicate access control restrictions."
            )

    # Clean up and return sorted results
    combined_accounts = []
    for account_data in account_map.values():
        account_data.pop("has_bsb", None)  # Remove temporary field
        combined_accounts.append(account_data)

    combined_accounts.sort(key=lambda x: x.get("accountNumber", ""))
    logger.info(f"Account merge completed: {len(combined_accounts)} unique accounts ({matched_count} matched)")

    return combined_accounts


async def get_client_accounts(cif_code: str, netbank_id: str) -> dict[str, Any]:
    """Get customer accounts using client services API with product categorization.

    Returns two versions of account data:
    - agent_response: Filtered data for LLM (essential fields only)
    - logging_response: Complete data for observability (all fields masked)

    Args:
        cif_code: Customer identification code
        netbank_id: NetBank ID

    Returns:
        Dict with 'agent_response' and 'logging_response' keys, each containing account data
    """
    try:
        logger.info("Loading accounts via client services API")
        correlation_id = str(uuid.uuid4())

        # Call both API endpoints in parallel
        balance_task = asyncio.create_task(
            commbank_client_service.get_accounts_balance_view(
                cif=cif_code,
                client_ip_address="127.0.0.1",
                netbank_id=netbank_id,
                correlation_id=correlation_id,
                product_codes=None,
                channel_name="FinancialCompanion",
            )
        )

        role_task = asyncio.create_task(
            commbank_client_service.get_accounts_customer_role_view(
                cif=cif_code,
                client_ip_address="127.0.0.1",
                netbank_id=netbank_id,
                correlation_id=correlation_id,
                channel_name="FinancialCompanion",
                filter_roles=ROLE_FILTERS,
            )
        )

        # Wait for both API calls to complete
        balance_response, role_response = await asyncio.gather(balance_task, role_task)

        # Extract account data from API responses
        balance_accounts = []
        role_accounts = []

        # Extract balance accounts if successful
        if balance_response.get("result", False):
            balance_data = balance_response.get("data", {})
            if isinstance(balance_data, dict):
                balance_accounts = balance_data.get("Data", [])

        # Extract role accounts if successful and apply role filtering
        if role_response.get("result", False):
            role_data = role_response.get("data", {})
            if isinstance(role_data, dict):
                role_accounts = role_data.get("Data", [])
                role_accounts = _filter_accounts_by_roles(role_accounts, ROLE_FILTERS)

        # Check if we got any data at all
        if not balance_accounts and not role_accounts:
            logger.error("Both API calls returned no data")
            return {
                "agent_response": {"accounts": [], "total_accounts": 0},
                "logging_response": {"accounts": [], "total_accounts": 0},
            }

        # Merge and filter account data
        combined_accounts = _merge_account_data(balance_accounts, role_accounts)

        # Apply active account filtering
        pre_filter_count = len(combined_accounts)
        combined_accounts = _filter_active_accounts(combined_accounts)
        filtered_out = pre_filter_count - len(combined_accounts)
        if filtered_out > 0:
            logger.info(f"Filtered out {filtered_out} inactive accounts")

        # Add product categorization and pictogram to each account
        for account in combined_accounts:
            product_code = account.get("productCode")
            product_sub_code = account.get("productSubCode")
            account["productCategory"] = categorise_product(product_code, product_sub_code)
            account["pictogramId"] = _get_pictogram_id(product_code)

        # Build agent response - filtered fields with UNMASKED account numbers (what the LLM sees)
        # Account numbers are kept unmasked here so sub-agents can use them for API calls
        agent_accounts = []
        for account in combined_accounts:
            agent_account = {
                "productName": account.get("productName"),
                "productCategory": account.get("productCategory"),
                "pictogramId": account.get("pictogramId"),
                "accountNumber": account.get("accountNumber"),  # UNMASKED for API calls
                "productCode": account.get(
                    "productCode"
                ),  # Included for sub-agent product-based filtering (e.g., mortgage_loan_tools filters by MORTGAGE_LOAN_PRODUCT_CODES)
                "balance": account.get("balance"),
                "availableFunds": account.get("availableFunds"),
            }
            agent_accounts.append(agent_account)

        agent_response = {
            "accounts": agent_accounts,
            "total_accounts": len(agent_accounts),
            "metadata": {
                "ownership_filter": "primary_only",
                "status_filter": "active_only",
            },
        }

        # Build logging response - complete but all sensitive fields masked (for Langfuse/observability)
        logging_accounts = []
        for account in combined_accounts:
            logging_account = {
                **account,  # Include all fields
                "accountNumber": _mask_account_number(account.get("accountNumber")),
                "fullAccountNumber": _mask_account_number(account.get("fullAccountNumber")),
            }

            # Mask CifId in customers array
            if "customers" in logging_account:
                logging_account["customers"] = [
                    {**customer, "CifId": _mask_sensitive_field(customer.get("CifId"))}
                    for customer in logging_account["customers"]
                ]

            logging_accounts.append(logging_account)

        logging_response = {
            "accounts": logging_accounts,
            "total_accounts": len(logging_accounts),
            "metadata": {
                "ownership_filter": "primary_only",
                "status_filter": "active_only",
                "cif_code": _mask_sensitive_field(cif_code),
                "netbank_id": _mask_sensitive_field(netbank_id),
                "service_used": "client_services",
            },
        }

        return {"agent_response": agent_response, "logging_response": logging_response}

    except (ValueError, ConnectionError, TimeoutError, KeyError) as e:
        logger.error(f"Failed to get customer accounts via client services: {e!s}")
        return {
            "agent_response": {"accounts": [], "total_accounts": 0},
            "logging_response": {"accounts": [], "total_accounts": 0},
        }


def _resolve_customer_identifiers(context: ToolContext) -> tuple[str, str]:
    """Resolve customer identifiers from ToolContext.

    Args:
        context: ToolContext with customer identifiers

    Returns:
        tuple: (cif_code, netbank_id)

    Raises:
        ValueError: If identifiers are not available
    """
    if not context.cif_code:
        raise ValueError("CIF code not available in context")
    if not context.netbank_id:
        raise ValueError("NBID not available in context")
    return context.cif_code, context.netbank_id


@function_tool
async def load_customer_account_context(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any]:
    """Load customer account context using client services API for optimal performance.

    This tool pre-loads all customer account information once and caches it in the
    context for use by all sub-agents, eliminating redundant API calls and reducing
    response latency by 200-500ms per account-related query.

    Args:
        wrapper: The context wrapper for maintaining state

    Returns:
        Dict containing loading status and summary information in clean JSON format

    Raises:
        ValueError: If customer identifiers are not available in context
        ConnectionError: If client services are unavailable
        TimeoutError: If service requests time out
    """
    # Validate customer identifiers
    if not wrapper.context.cif_code or not wrapper.context.netbank_id:
        return {
            "error": True,
            "message": "Customer identifiers (CIF code and NetBank ID) not available in context",
        }

    # Skip if already loaded (avoid redundant loading)
    if wrapper.context.account_context_loaded:
        logger.info("Account context already loaded, skipping reload")
        return {
            "error": False,
            "message": f"Account context already loaded with {wrapper.context.get_accounts_count()} accounts",
            "accounts_count": wrapper.context.get_accounts_count(),
            "service_used": wrapper.context.account_service_used,
        }

    # Update tool observation for monitoring (with masked PII)
    update_tool_observation(
        wrapper,
        "load_customer_account_context",
        {
            "cif_code": _mask_sensitive_field(wrapper.context.cif_code),
            "netbank_id": _mask_sensitive_field(wrapper.context.netbank_id),
            "service": "client_services",
        },
    )

    try:
        logger.info("Loading account context for customer via client services")
        start_time = datetime.now()

        # Get customer identifiers
        cif_code, netbank_id = _resolve_customer_identifiers(wrapper.context)

        # Load accounts from client services API (returns both agent and logging versions)
        accounts_data = await get_client_accounts(cif_code, netbank_id)

        # Extract agent response for caching (unmasked, filtered data for agent use)
        agent_response = accounts_data.get("agent_response", {})
        agent_accounts = agent_response.get("accounts", [])

        # Cache agent response in context for instant access by sub-agents
        wrapper.context.customer_accounts = agent_accounts
        wrapper.context.account_context_loaded = True
        wrapper.context.account_service_used = "client_services"

        load_time = (datetime.now() - start_time).total_seconds() * 1000  # Convert to milliseconds

        logger.info(f"Account context loaded successfully in {load_time:.0f}ms: {len(agent_accounts)} accounts")

        # Update tool observation with masked logging response
        logging_response = accounts_data.get("logging_response", {})
        update_tool_observation(
            wrapper,
            "load_customer_account_context",
            {
                **logging_response,
                "load_time_ms": round(load_time),
            },
        )

        # Return agent response
        return {
            "accounts": agent_accounts,
            "total_accounts": len(agent_accounts),
            "metadata": {
                "ownership_filter": "primary_only",
                "status_filter": "active_only",
                "service_used": "client_services",
                "load_time_ms": round(load_time),
            },
        }

    except (ValueError, ConnectionError, TimeoutError, KeyError, AttributeError) as e:
        logger.error(f"Failed to load account context: {traceback.format_exc()}")
        return {
            "error": True,
            "message": f"Failed to load account context: {e!s}",
        }


@function_tool
async def get_account_holdings_and_balances(
    wrapper: RunContextWrapper[ToolContext],
) -> dict[str, Any]:
    """Get customer's OWN account holdings and balances.

    Returns summary information for all ACTIVE customer accounts including:
    - Bank accounts (savings, transaction accounts)
    - Credit cards
    - Customer's OWN home loans/mortgages
    - Customer's OWN personal/consumer loans
    - Term deposits
    - Investment accounts

    This tool provides account identifiers (account numbers) and basic balance information.
    For detailed loan information (rates, repayment schedules, terms, etc.), the account identifiers (which may already be stored in the cache)
    from this tool are required to call mortgage_loan_tools or consumer_loan_tools.

    ACCOUNT FILTERING:
    Only returns active accounts where customer is primary holder. Excludes:
    - Inactive accounts (Closed, Cancelled, Suspended, Dormant, Lost, Written Off)
    - Accounts where the customer is a Designated Authority

    UNDERSTANDING BALANCE vs AVAILABLE FUNDS:
    - Bank Accounts: balance = current balance, availableFunds = amount available to withdraw
    - Credit Cards: balance = current debt owed, availableFunds = credit limit
    - Loans (Home Loans/Mortgages, Personal Loans, Car Loans): balance = remaining balance owed (shown as NEGATIVE number), availableFunds = redraw available (if applicable)

    IMPORTANT - INTERPRETING LOAN BALANCES:
    For home loans and personal loans, the balance.amount field will be NEGATIVE (e.g., -450000.00).
    This negative value represents the remaining loan balance that the customer owes.
    When communicating with customers, always present this as a positive amount (e.g., "$450,000 remaining balance").

    When customer mentions credit card "balance" or "debt", clarify which value is needed.

    IMPORTANT: When aggregating balances, NEVER mix currencies. Each balance has "amount" and "currency" fields.

    Args:
        wrapper: The context wrapper containing cached account data

    Returns:
        Dict with accounts list, total_accounts count, and metadata
    """
    if not wrapper.context.has_account_context():
        logger.error(
            f"Account context check failed - account_context_loaded: {wrapper.context.account_context_loaded}, customer_accounts count: {len(wrapper.context.customer_accounts) if wrapper.context.customer_accounts else 0}"
        )
        return {
            "error": True,
            "message": "No account context available. Account data should be automatically pre-loaded by principal agent.",
        }

    # Return cached account data (unmasked for agent use - enables API calls)
    accounts = wrapper.context.get_customer_accounts()

    update_tool_observation(
        wrapper,
        "get_account_holdings_and_balances",
    )

    # Return filtered data to agent
    return {
        "accounts": accounts,
        "total_accounts": len(accounts),
        "metadata": {
            "data_source": "cached_context",
            "service_used": wrapper.context.account_service_used,
        },
    }


@function_tool
async def refresh_account_context(
    wrapper: RunContextWrapper[ToolContext], force_refresh: bool = False
) -> dict[str, Any]:
    """Refresh cached account context if needed or forced.

    Args:
        wrapper: The context wrapper for maintaining state
        force_refresh: Force refresh even if context is recent

    Returns:
        Dict containing refresh status and information
    """
    if not force_refresh and wrapper.context.account_context_loaded:
        return {
            "error": False,
            "message": "Account context already loaded, skipping refresh (use force_refresh=True to override)",
            "refreshed": False,
        }

    # Clear existing context to force reload
    wrapper.context.account_context_loaded = False
    wrapper.context.customer_accounts = None

    # Reload context by calling the load function directly
    return cast("dict[str, Any]", await load_customer_account_context(wrapper))
