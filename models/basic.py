"""Shared enums for Financial Companion system.

This module contains enumeration types used across multiple services and agents
to prevent circular dependencies and promote code reuse.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Frequency(StrEnum):
    """Enumeration of frequency options for recurring financial operations."""

    WEEKLY = "Weekly"
    FORTNIGHTLY = "Fortnightly"
    MONTHLY = "Monthly"


class Money(BaseModel):
    """Represents a monetary amount with currency.

    This model is immutable and hashable to support use in sets and as dict keys.
    Supports both snake_case and CamelCase field names for API compatibility.

    Attributes:
        amount: The numeric amount
        currency: The currency code (e.g., 'AUD', 'USD')
    """

    # We make immutable so we can hash (i.e. call set() and dict key)
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    amount: float = Field(alias="Amount")
    currency: str = Field(alias="Currency")


# Schema mappings used by the GenUI tools, put in the common folder to prevent circular imports
SCHEMA_MAP: dict[str, dict[str, str]] = {
    "example_component": {
        "filename": "schema_example.json",
        "description": "An example schema for you to use.",
    },
    "text_response": {
        "filename": "text_response_schema.json",
        "description": "Use this schema only when there is no other matching schema available or when explicitly requested",
    },
    "home_buying_property_insights": {
        "filename": "home_buying_property_insights.json",
        "description": "Use when displaying property details ONLY - address, bedrooms, bathrooms, parking, estimated value, images. NO borrowing or affordability calculations included. Customer asks about property information without mentioning borrowing capacity.",
    },
    "home_buying_property_comparison": {
        "filename": "home_buying_property_comparison.json",
        "description": "Use when comparing exactly TWO properties side-by-side, including property details, valuations, and borrowing power calculations for both properties. Customer has explicitly asks to compare properties or mentions multiple properties and has also asked for borrowing power estimates.",
    },
    "home_buying_borrowing_power": {
        "filename": "home_buying_borrowing_power.json",
        "description": "Use when showing borrowing capacity and affordability analysis WITHOUT any specific property details. Customer asks 'how much can I borrow?' or wants general affordability assessment. NO property address or property-specific information included.",
    },
    "home_buying_property_with_borrowing_power": {
        "filename": "home_buying_property_with_borrowing_power.json",
        "description": "Use when showing ONE specific property combined with complete affordability analysis - property details PLUS borrowing calculations PLUS repayment calculations. Customer asks 'can I afford this property?' or wants property-specific affordability assessment.",
    },
    "home_buying_purchasing_power": {
        "filename": "home_buying_purchasing_power.json",
        "description": "Use when showing the purchasing power analysis - purchasing power calculations. Use when customer asks what is my purchasing power?",
    },
    "comparison_table": {
        "filename": "comparison_table.json",
        "description": "Comparison table - for use when comparing features, products, or scenarios side-by-side",
    },
    "action_card": {
        "filename": "action_card.json",
        "description": "Card to display info about one thing that also requires a call to action - like apply now, learn more, contact us",
    },
    "currency_bar_chart": {
        "filename": "currency_bar_chart.json",
        "description": "Currency bar chart widget for displaying budget tracking with spending vs target amounts across multiple categories - use for savings budget visualizations showing current spend against budget targets",
    },
    "home_buying_apply_online": {
        "filename": "home_buying_apply_online.json",
        "description": "Widget to surface the apply online widget",
    },
    "home_buying_speak_lender": {
        "filename": "home_buying_speak_lender.json",
        "description": "Widget to surface the speak with lender widget",
    },
    "goal_tracker": {
        "filename": "goal_tracker.json",
        "description": "For showing a financial goal with progress",
    },
    "category_insights": {
        "filename": "category_insights.json",
        "description": "To show category level insights",
    },
    "bills_payments": {
        "filename": "bills_payments.json",
        "description": "Shows bills and payments info",
    },
    "product_detail": {
        "filename": "product_detail.json",
        "description": "Schema for showing a customer's account related information like balance, account number. Only use for a customer's personal account data, not for product information or features.",
    },
    "option_select": {
        "filename": "option_select.json",
        "description": "Use for displaying a list of selectable options with a title - when customer needs to choose from multiple options",
    },
    "raw_text": {
        "filename": "raw_text.json",
        "description": "Use for displaying raw text or HTML content - when you need to render formatted text, HTML, or custom markup",
    },
    # Add more schemas here as needed
}
