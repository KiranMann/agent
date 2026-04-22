"""Product categorization framework for mapping CommBank product codes to high-level categories.

This module provides a framework for categorizing financial products based on:
- productCode: Primary product identifier
- productSubCode: Sub-category identifier
- productName: Human-readable product name

The mapping includes a limited number of entries and needs to be validated and expanded.

Reference for Transaction/Savings Split:
https://github.com/CBA-CommBank/Api.CashFlow/blob/master/src/app/Api.CashFlow/Constants.cs#L65
"""

import logging

logger = logging.getLogger(__name__)

# Maximum length for product codes and sub-codes (usually 3 digits, but setting as 5 just in case - this is just for validation of inputs)
MAX_PRODUCT_CODE_LENGTH = 5

# Product code to category mappings
# Format: (product_code, product_sub_code) -> category
PRODUCT_CATEGORY_MAP = {
    # DDA Transaction Accounts
    ("DDA", "54"): "transaction_account",
    ("DDA", "56"): "transaction_account",
    ("DDA", "C8"): "transaction_account",
    ("DDA", "28"): "transaction_account",
    ("DDA", "48"): "transaction_account",
    # DDA Savings Accounts
    ("DDA", "45"): "savings_account",
    ("DDA", "46"): "savings_account",
    ("DDA", "66"): "savings_account",
}

# Category to product codes mapping (Using some pictogram categories in account_service_tools)
CATEGORY_TO_CODES = {
    "business_account": ["BUS"],
    "credit_card": ["MCD", "VCD", "MNS", "AMX", "DIN", "CRC", "VIS", "CCD", "CCA"],
    "debit_card": ["DBC"],
    "home_loan": [
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
    "personal_loan": ["PLA", "LAL", "PLN", "CAR", "UPL", "CPL", "VEH", "BOA", "PLS"],
    "investment": ["CSL", "CLS", "INV", "TRM", "STK", "BND", "ETF", "MAN"],
    "superannuation": ["MFX", "FMS"],
    "term_deposit": ["TDP", "TDA", "FTD", "CTD"],
}

# Product code only mappings (when sub-code doesn't matter or isn't available)
# Generated from CATEGORY_TO_CODES for efficient lookup
PRODUCT_CODE_ONLY_MAP = {code: category for category, codes in CATEGORY_TO_CODES.items() for code in codes}


def categorise_product(
    product_code: str | None,
    product_sub_code: str | None,
) -> str | None:
    """Returns a high-level productCategory for a given product.

    Args:
        product_code: Primary product code (e.g., "DDA", "FMS", "CCA")
        product_sub_code: Optional sub-code (e.g., "66", "33", "10")

    Returns:
        Category string (e.g., "savings_account", "transaction_account", "superannuation")
        or None if no mapping exists

    Examples:
        >>> categorise_product("DDA", "66")
        'savings_account'
        >>> categorise_product("DDA", "10")
        'transaction_account'
        >>> categorise_product("FMS", "33")
        'superannuation'
    """
    # Validate input types and handle None/empty inputs
    if not isinstance(product_code, str) or not product_code:
        logger.warning(f"Empty product_code: {product_code}")
        return None

    # Normalize inputs
    product_code = product_code.upper().strip()
    product_sub_code = product_sub_code.strip() if product_sub_code else None

    # Validate normalized inputs - only allow alphanumeric characters
    if not product_code.isalnum():
        logger.warning(f"Invalid product_code format: {product_code}")
        return None

    if product_sub_code and not product_sub_code.isalnum():
        logger.warning(f"Invalid product_sub_code format: {product_sub_code}")
        return None

    # Validate length constraints (reasonable limits for product codes)
    if len(product_code) > MAX_PRODUCT_CODE_LENGTH:
        logger.warning(f"product_code exceeds maximum length: {product_code}")
        return None

    if product_sub_code and len(product_sub_code) > MAX_PRODUCT_CODE_LENGTH:
        logger.warning(f"product_sub_code exceeds maximum length: {product_sub_code}")
        return None

    # Try exact match with product code and sub-code first
    if product_sub_code:
        category = PRODUCT_CATEGORY_MAP.get((product_code, product_sub_code))
        if category:
            return category

    # Fall back to product code only mapping
    category = PRODUCT_CODE_ONLY_MAP.get(product_code)
    if category:
        return category

    # Log unknown combinations for future mapping
    logger.debug(f"No category mapping for product_code='{product_code}', product_sub_code='{product_sub_code}'")

    return None
