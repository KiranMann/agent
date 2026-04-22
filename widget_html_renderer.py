"""Widget HTML renderer for converting UI components to bare-bones HTML.

This module converts UI component dictionaries into minimal HTML strings for inclusion
in dialogue monitoring payloads. The output is intentionally limited to plain HTML
with no CSS or JavaScript so it renders consistently in any viewing context.
"""

import html
import json
from typing import Any

from common.logging.core import logger


def _esc(value: Any) -> str:
    """HTML-escape a value for safe embedding in an HTML document."""
    return html.escape(str(value) if value is not None else "")


def _fmt_money(amount_dict: Any) -> str:
    """Format a money dict ``{amount, currency}`` as a human-readable dollar string.

    Args:
        amount_dict: A dict with ``amount`` (numeric) and ``currency`` (str) keys,
            or any fallback value that will be stringified.

    Returns:
        A formatted string such as ``$1,234`` or ``$1,234.56``.
    """
    if not isinstance(amount_dict, dict):
        return _esc(amount_dict)
    amount = amount_dict.get("amount", 0)
    try:
        amt = float(amount)
        formatted = f"{amt:,.0f}" if amt == int(amt) else f"{amt:,.2f}"
        return f"${formatted}"
    except (ValueError, TypeError):
        return f"${amount}"


def _render_action_card(raw_content: dict[str, Any]) -> str:
    """Render an action_card widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from an ``action_card`` component.

    Returns:
        An HTML string representing the action card.
    """
    summary = raw_content.get("action_summary", "")
    actions: list[dict[str, Any]] = raw_content.get("actions") or []

    rows = "".join(
        f'<li><a href="{_esc(a.get("actionLink", "#"))}">{_esc(a.get("actionLabel", ""))}</a></li>' for a in actions
    )
    actions_html = f"<ul>{rows}</ul>" if rows else ""

    return f"<h2>Actions</h2><p>{_esc(summary)}</p>{actions_html}"


def _render_bills_payments(raw_content: dict[str, Any]) -> str:
    """Render a bills_payments widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``bills_payments`` component.

    Returns:
        An HTML string representing the bills and payments list.
    """
    response_message = raw_content.get("response_message", "")
    outgoings: list[dict[str, Any]] = raw_content.get("outgoings") or []

    rows = ""
    for item in outgoings:
        title = _esc(item.get("title", ""))
        description = _esc(item.get("description") or "")
        min_amt = _fmt_money(item.get("minAmount"))
        max_amt = _fmt_money(item.get("maxAmount"))
        rows += f"<tr><td>{title}</td><td>{description}</td><td>{min_amt}</td><td>{max_amt}</td></tr>"

    table = (
        f'<table border="1"><thead><tr>'
        f"<th>Bill</th><th>Description</th><th>Min Amount</th><th>Max Amount</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
        if rows
        else ""
    )

    return f"<h2>Bills &amp; Payments</h2><p>{_esc(response_message)}</p>{table}"


def _render_comparison_table(raw_content: dict[str, Any]) -> str:
    """Render a comparison_table widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``comparison_table`` component.

    Returns:
        An HTML string containing a ``<table>`` representing the comparison.
    """
    title: str = raw_content.get("title", "")
    headers: list[str] = raw_content.get("headers") or []
    rows: list[list[str]] = raw_content.get("rows") or []

    # Use "Comparison" as default title when title is empty
    display_title = title if title else "Comparison"

    header_cells = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body_rows = "".join(f"<tr>{''.join(f'<td>{_esc(cell)}</td>' for cell in row)}</tr>" for row in rows)

    return f'<h2>{_esc(display_title)}</h2><table border="1"><thead><tr>{header_cells}</tr></thead><tbody>{body_rows}</tbody></table>'


def _render_currency_bar_chart(raw_content: dict[str, Any]) -> str:
    """Render a currency_bar_chart widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``currency_bar_chart`` component.

    Returns:
        An HTML string containing a table with a ``<progress>`` element per budget category.
    """
    title = raw_content.get("title", "Budget Tracking")
    response_message = raw_content.get("response_message", "")
    bar_content: list[dict[str, Any]] = raw_content.get("bar_content") or []

    rows = ""
    for item in bar_content:
        label = _esc(item.get("item_label", ""))
        spend_dict = item.get("spend") or {}
        target_dict = item.get("target") or {}

        try:
            spend_amt = float(spend_dict.get("amount", 0))
        except (ValueError, TypeError):
            spend_amt = 0.0
        try:
            target_amt = float(target_dict.get("amount", 0))
        except (ValueError, TypeError):
            target_amt = 0.0

        remaining = max(target_amt - spend_amt, 0)

        spend_str = f"${spend_amt:,.0f}" if spend_amt == int(spend_amt) else f"${spend_amt:,.2f}"
        target_str = f"${target_amt:,.0f}" if target_amt == int(target_amt) else f"${target_amt:,.2f}"
        remaining_str = f"${remaining:,.0f}" if remaining == int(remaining) else f"${remaining:,.2f}"

        progress = f'<progress value="{int(spend_amt)}" max="{int(target_amt)}"></progress>'

        rows += (
            f"<tr><td>{label}</td><td>{spend_str}</td><td>{target_str}</td>"
            f"<td>{progress}</td><td>{remaining_str}</td></tr>"
        )

    table = (
        f'<table border="1"><thead><tr>'
        f"<th>Category</th><th>Spent</th><th>Budget</th><th>Progress</th><th>Remaining</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )

    return f"<h1>{_esc(title)}</h1><p>{_esc(response_message)}</p><hr>{table}"


def _render_goal_tracker(raw_content: dict[str, Any]) -> str:
    """Render a goal_tracker widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``goal_tracker`` component.

    Returns:
        An HTML string with goal progress including a ``<progress>`` element.
    """
    title = raw_content.get("title", "")
    description = raw_content.get("description", "")
    response_message = raw_content.get("response_message", "")
    goal: dict[str, Any] = raw_content.get("goal") or {}
    saved_dict = goal.get("saved") or {}
    target_dict = goal.get("target") or {}

    try:
        saved_amt = float(saved_dict.get("amount", 0))
    except (ValueError, TypeError):
        saved_amt = 0.0
    try:
        target_amt = float(target_dict.get("amount", 0))
    except (ValueError, TypeError):
        target_amt = 0.0

    saved_str = _fmt_money(saved_dict)
    target_str = _fmt_money(target_dict)
    progress = f'<progress value="{int(saved_amt)}" max="{int(target_amt)}"></progress>'

    return (
        f"<h2>{_esc(title)}</h2>"
        f"<p>{_esc(description)}</p>"
        f"<p>Saved: {saved_str} of {target_str}</p>"
        f"{progress}"
        f"<p>{_esc(response_message)}</p>"
    )


def _render_product_detail(raw_content: dict[str, Any]) -> str:
    """Render a product_detail widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``product_detail`` component.

    Returns:
        An HTML string with product title, subtitle, and a key-value table of fields.
    """
    title = raw_content.get("title", "")
    subtitle = raw_content.get("subtitle", "")
    fields: list[dict[str, Any]] = raw_content.get("fields") or []

    rows = "".join(
        f"<tr><th>{_esc(f.get('fieldName', ''))}</th><td>{_esc(f.get('fieldValue', ''))}</td></tr>" for f in fields
    )

    table = f'<table border="1"><tbody>{rows}</tbody></table>' if rows else ""

    return f"<h2>{_esc(title)}</h2><p>{_esc(subtitle)}</p>{table}"


def _render_option_select(raw_content: dict[str, Any]) -> str:
    """Render an option_select widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from an ``option_select`` component.

    Returns:
        An HTML string with the option title and a list of selectable options.
    """
    option_title = raw_content.get("option_title", "")
    option_body = raw_content.get("option_body") or ""

    # Support both legacy ``option_labels`` list and new ``options`` list of dicts
    option_labels: list[str] = raw_content.get("option_labels") or []
    options: list[dict[str, str]] = raw_content.get("options") or []

    items: list[str] = []
    if options:
        items = [_esc(opt.get("label", "")) for opt in options]
    elif option_labels:
        items = [_esc(label) for label in option_labels]

    list_html = f"<ul>{''.join(f'<li>{item}</li>' for item in items)}</ul>" if items else ""
    body_html = f"<p>{_esc(option_body)}</p>" if option_body else ""

    return f"<h2>{_esc(option_title)}</h2>{body_html}{list_html}"


def _render_single_option_selection(raw_content: dict[str, Any]) -> str:
    """Render a single_option_selection widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``single_option_selection`` component.

    Returns:
        An HTML string with a question title, list of options, and confirm action.
    """
    title = raw_content.get("title", "")
    options: list[dict[str, Any]] = raw_content.get("options") or []
    confirm_action: dict[str, Any] = raw_content.get("confirm_action") or {}

    items = ""
    for opt in options:
        label = _esc(opt.get("label", ""))
        description = _esc(opt.get("description") or "")
        desc_html = f" &ndash; {description}" if description else ""
        items += f"<li><strong>{label}</strong>{desc_html}</li>"

    confirm_label = _esc(confirm_action.get("label", ""))
    confirm_html = f"<p>Confirm: <strong>{confirm_label}</strong></p>" if confirm_label else ""

    return f"<h2>{_esc(title)}</h2><ul>{items}</ul>{confirm_html}"


def _render_bills_payment_summary(raw_content: dict[str, Any]) -> str:
    """Render a bills_payment_summary widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``bills_payment_summary`` component.

    Returns:
        An HTML string summarising the payment details and optional confirmation actions.
    """
    title = raw_content.get("title", "")
    details: list[dict[str, Any]] = raw_content.get("details") or []
    information = raw_content.get("information") or ""
    confirmation: dict[str, Any] = raw_content.get("confirmation") or {}

    rows = "".join(
        f"<tr><th>{_esc(d.get('label', ''))}</th>"
        f"<td>{_esc(d.get('value', ''))}</td>"
        f"<td>{_esc(d.get('description', ''))}</td></tr>"
        for d in details
    )
    table = (
        f'<table border="1"><thead><tr><th>Item</th><th>Value</th><th>Details</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
        if rows
        else ""
    )

    info_html = f"<p>{_esc(information)}</p>" if information else ""

    confirm_html = ""
    if confirmation:
        header = _esc(confirmation.get("header", ""))
        primary: dict[str, Any] = confirmation.get("primary_action") or {}
        secondary: dict[str, Any] = confirmation.get("secondary_action") or {}
        primary_html = f"<p>{_esc(primary.get('label', ''))}</p>" if primary else ""
        secondary_html = f"<p>{_esc(secondary.get('label', ''))}</p>" if secondary else ""
        confirm_html = f"<h3>{header}</h3>{primary_html}{secondary_html}"

    return f"<h2>{_esc(title)}</h2>{table}{info_html}{confirm_html}"


def _render_raw_text(raw_content: dict[str, Any]) -> str:
    """Render a raw_text widget to HTML.

    For ``raw_text`` components the serialised ``raw_content`` dict contains the
    full widget payload including the ``raw_text`` key.

    Args:
        raw_content: The ``raw_content`` dict from a ``raw_text`` component
            (which is the entire widget dict when serialised).

    Returns:
        The raw HTML string stored in the component.
    """
    return str(raw_content.get("raw_text", ""))


def _render_home_buying_borrowing_power(raw_content: dict[str, Any]) -> str:
    """Render a home_buying_borrowing_power widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``home_buying_borrowing_power`` component.

    Returns:
        An HTML string showing borrowing power and repayment details.
    """
    title = raw_content.get("title", "Borrowing Power")
    borrowing_power = raw_content.get("borrowingPower", "")
    repayment_amount = raw_content.get("repaymentAmount", "")
    repayment_schedule = raw_content.get("repaymentSchedule", "")
    repayment_desc = raw_content.get("repaymentDesc", "")
    interest_rate = raw_content.get("interestRate", "")
    comparison_rate = raw_content.get("comparisonRate", "")
    disclaimer = raw_content.get("loanDisclaimer", "")

    rows = (
        f"<tr><th>Borrowing Power</th><td>{_esc(borrowing_power)}</td></tr>"
        f"<tr><th>Repayment</th><td>{_esc(repayment_amount)} ({_esc(repayment_schedule)})</td></tr>"
        f"<tr><th>Repayment Type</th><td>{_esc(repayment_desc)}</td></tr>"
        f"<tr><th>Interest Rate</th><td>{_esc(interest_rate)}</td></tr>"
        f"<tr><th>Comparison Rate</th><td>{_esc(comparison_rate)}</td></tr>"
    )

    return f'<h2>{_esc(title)}</h2><table border="1"><tbody>{rows}</tbody></table><p>{_esc(disclaimer)}</p>'


def _render_home_buying_affordability(raw_content: dict[str, Any]) -> str:
    """Render a home_buying_affordability widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``home_buying_affordability`` component.

    Returns:
        An HTML string showing home affordability details.
    """
    title = raw_content.get("title", "Affordability")
    property_price = raw_content.get("propertyPrice", "")
    estimated_loan = raw_content.get("borrowingPower", "")  # Field name stays borrowingPower for compatibility
    deposit = raw_content.get("deposit", "")
    upfront_costs = raw_content.get("upfrontCosts", "")
    interest_rate = raw_content.get("interestRate", "")
    comparison_rate = raw_content.get("comparisonRate", "")
    disclaimer = raw_content.get("loanDisclaimer", "")

    rows = (
        f"<tr><th>Property Price</th><td>{_esc(property_price)}</td></tr>"
        f"<tr><th>Estimated loan amount</th><td>{_esc(estimated_loan)}</td></tr>"
        f"<tr><th>Deposit</th><td>{_esc(deposit)}</td></tr>"
        f"<tr><th>Upfront Costs</th><td>{_esc(upfront_costs)}</td></tr>"
        f"<tr><th>Interest Rate</th><td>{_esc(interest_rate)}</td></tr>"
        f"<tr><th>Comparison Rate</th><td>{_esc(comparison_rate)}</td></tr>"
    )

    return f'<h2>{_esc(title)}</h2><table border="1"><tbody>{rows}</tbody></table><p>{_esc(disclaimer)}</p>'


def _render_home_buying_property_insights(raw_content: dict[str, Any]) -> str:
    """Render a home_buying_property_insights widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``home_buying_property_insights`` component.

    Returns:
        An HTML string showing property details and estimated value.
    """
    address = raw_content.get("address", "")
    property_type = raw_content.get("propertyType", "")
    bedrooms = raw_content.get("bedrooms", "")
    bathrooms = raw_content.get("bathrooms", "")
    parking = raw_content.get("parking", "")
    estimated_value = raw_content.get("estimatedValue", "")
    lower_price = raw_content.get("lowerPriceRange") or ""
    upper_price = raw_content.get("upperPriceRange") or ""
    updated_date = raw_content.get("updatedDate") or ""

    rows = (
        f"<tr><th>Type</th><td>{_esc(property_type)}</td></tr>"
        f"<tr><th>Bedrooms</th><td>{_esc(bedrooms)}</td></tr>"
        f"<tr><th>Bathrooms</th><td>{_esc(bathrooms)}</td></tr>"
        f"<tr><th>Parking</th><td>{_esc(parking)}</td></tr>"
        f"<tr><th>Estimated Value</th><td>{_esc(estimated_value)}</td></tr>"
    )
    if lower_price and upper_price:
        rows += f"<tr><th>Price Range</th><td>{_esc(lower_price)} &ndash; {_esc(upper_price)}</td></tr>"
    if updated_date:
        rows += f"<tr><th>Last Updated</th><td>{_esc(updated_date)}</td></tr>"

    return f'<h2>Property Insights</h2><h3>{_esc(address)}</h3><table border="1"><tbody>{rows}</tbody></table>'


def _render_home_buying_property_comparison(raw_content: dict[str, Any]) -> str:
    """Render a home_buying_property_comparison widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a ``home_buying_property_comparison`` component.

    Returns:
        An HTML string with a side-by-side property comparison table.
    """
    properties: list[dict[str, Any]] = raw_content.get("properties") or []
    metrics: dict[str, Any] = raw_content.get("comparisonMetrics") or {}
    show_purchasing_power = metrics.get("showPurchasingPower", True)
    show_repayments = metrics.get("showMonthlyRepayments", True)
    show_details = metrics.get("showPropertyDetails", False)

    # Build header row - one column per property
    prop_headers = "".join(f"<th>Property {i + 1}</th>" for i in range(len(properties)))
    header_row = f"<tr><th></th>{prop_headers}</tr>"

    def _prop_row(label: str, values: list[str]) -> str:
        cells = "".join(f"<td>{v}</td>" for v in values)
        return f"<tr><th>{label}</th>{cells}</tr>"

    body = _prop_row("Address", [_esc(p.get("address", "")) for p in properties])
    body += _prop_row("Estimate", [_esc(p.get("commBankEstimate", "")) for p in properties])

    if show_purchasing_power:
        body += _prop_row("Purchasing Power", [_esc(p.get("purchasingPower", "")) for p in properties])

    if show_repayments:
        repayments = [
            f"{_esc(p.get('repaymentAmount', ''))} {_esc(p.get('repaymentSchedule', ''))}".strip() for p in properties
        ]
        body += _prop_row("Repayments", repayments)

    if show_details:
        body += _prop_row("Type", [_esc(p.get("propertyType") or "") for p in properties])
        body += _prop_row("Bedrooms", [_esc(p.get("bedrooms") or "") for p in properties])
        body += _prop_row("Bathrooms", [_esc(p.get("bathrooms") or "") for p in properties])
        body += _prop_row("Car Spaces", [_esc(p.get("carSpaces") or "") for p in properties])

    return f'<h2>Property Comparison</h2><table border="1"><thead>{header_row}</thead><tbody>{body}</tbody></table>'


def _render_home_buying_property_with_borrowing_power(raw_content: dict[str, Any]) -> str:
    """Render a home_buying_property_with_borrowing_power widget to HTML.

    Args:
        raw_content: The ``raw_content`` dict from a
            ``home_buying_property_with_borrowing_power`` component.

    Returns:
        An HTML string combining property details with borrowing power information.
    """
    address = raw_content.get("address", "")
    property_type = raw_content.get("propertyType") or ""
    bedrooms = raw_content.get("bedrooms")
    bathrooms = raw_content.get("bathrooms")
    car_spaces = raw_content.get("carSpaces")
    comm_bank_estimate = raw_content.get("commBankEstimate", "")
    borrowing_power = raw_content.get("borrowingPower", "")
    deposit = raw_content.get("deposit", "")
    upfront_costs = raw_content.get("upfrontCosts", "")
    repayment_amount = raw_content.get("repaymentAmount", "")
    repayment_schedule = raw_content.get("repaymentSchedule", "")
    repayment_desc = raw_content.get("repaymentDesc", "")
    interest_rate = raw_content.get("interestRate", "")
    comparison_rate = raw_content.get("comparisonRate", "")
    disclaimer = raw_content.get("loanDisclaimer", "")

    rows = f"<tr><th>Estimate</th><td>{_esc(comm_bank_estimate)}</td></tr>"
    if property_type:
        rows += f"<tr><th>Type</th><td>{_esc(property_type)}</td></tr>"
    if bedrooms is not None:
        rows += f"<tr><th>Bedrooms</th><td>{_esc(bedrooms)}</td></tr>"
    if bathrooms is not None:
        rows += f"<tr><th>Bathrooms</th><td>{_esc(bathrooms)}</td></tr>"
    if car_spaces is not None:
        rows += f"<tr><th>Car Spaces</th><td>{_esc(car_spaces)}</td></tr>"
    rows += (
        f"<tr><th>Borrowing Power</th><td>{_esc(borrowing_power)}</td></tr>"
        f"<tr><th>Deposit</th><td>{_esc(deposit)}</td></tr>"
        f"<tr><th>Upfront Costs</th><td>{_esc(upfront_costs)}</td></tr>"
        f"<tr><th>Repayment</th><td>{_esc(repayment_amount)} ({_esc(repayment_schedule)})</td></tr>"
        f"<tr><th>Repayment Type</th><td>{_esc(repayment_desc)}</td></tr>"
        f"<tr><th>Interest Rate</th><td>{_esc(interest_rate)}</td></tr>"
        f"<tr><th>Comparison Rate</th><td>{_esc(comparison_rate)}</td></tr>"
    )

    return f'<h2>{_esc(address)}</h2><table border="1"><tbody>{rows}</tbody></table><p>{_esc(disclaimer)}</p>'


# Map widget_type strings to their renderer functions
_RENDERERS = {
    "action_card": _render_action_card,
    "bills_payments": _render_bills_payments,
    "comparison_table": _render_comparison_table,
    "currency_bar_chart": _render_currency_bar_chart,
    "goal_tracker": _render_goal_tracker,
    "product_detail": _render_product_detail,
    "option_select": _render_option_select,
    "single_option_selection": _render_single_option_selection,
    "bills_payment_summary": _render_bills_payment_summary,
    "raw_text": _render_raw_text,
    "home_buying_borrowing_power": _render_home_buying_borrowing_power,
    "home_buying_affordability": _render_home_buying_affordability,
    "home_buying_property_insights": _render_home_buying_property_insights,
    "home_buying_property_comparison": _render_home_buying_property_comparison,
    "home_buying_property_with_borrowing_power": _render_home_buying_property_with_borrowing_power,
}


def render_ui_components_to_html(components: list[dict[str, Any]]) -> str:
    """Convert a list of serialised UI component dicts to a concatenated HTML string.

    Components with ``widget_type`` of ``plain_text`` are skipped as they are
    represented by the surrounding message text.  Unknown widget types fall back
    to rendering their ``fallback_content`` as a plain paragraph.

    Args:
        components: A list of dicts produced by serialising ``UIComponent`` objects
            (via ``model_dump(mode="json")``).

    Returns:
        A single HTML string containing the rendered output of all components.
        Returns an empty string when the input list is empty or all components
        are of type ``plain_text``.
    """
    parts: list[str] = []

    for comp in components:
        widget_type: str = comp.get("widget_type", "")

        if widget_type == "plain_text":
            continue

        # raw_content for most widgets is a nested dict.
        # For raw_text the entire widget dict is stored as raw_content (see handler).
        raw_content = comp.get("raw_content") or {}
        if isinstance(raw_content, str):
            try:
                raw_content = json.loads(raw_content)
            except ValueError:
                raw_content = {}

        renderer = _RENDERERS.get(widget_type)
        if renderer is not None:
            try:
                parts.append(renderer(raw_content))
            except Exception as e:
                # Fall back to plain fallback_content so a single bad widget
                # does not blank out the entire ui_html field.
                logger.warning(
                    f"Failed to render widget type {widget_type} error: {e!s}",
                )

                fallback = _esc(comp.get("fallback_content", ""))
                parts.append(f"<p>{fallback}</p>")
        else:
            # Unknown widget type - emit fallback_content
            fallback = _esc(comp.get("fallback_content", ""))
            parts.append(f"<p>{fallback}</p>")

    return "".join(parts)
