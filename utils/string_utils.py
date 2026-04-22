import re

# Compile regex patterns once at module level for better performance
_MARKDOWN_PATTERNS = {
    "code": re.compile(r"```[\s\S]*?```|`([^`]+)`"),  # Combined code blocks and inline code
    "image_link": re.compile(r"!\[([^\]]*)\]\([^)]+\)|\[([^\]]+)\]\([^)]+\)"),  # Combined images and links
    "bold": re.compile(r"(\*\*|__)(.+?)\1"),  # Matches both **text** and __text__
    "italic": re.compile(r"([\*_])(.+?)\1"),  # Matches both *text* and _text_
    "horizontal_rule": re.compile(r"^(?:\-{3,}|\*{3,}|_{3,})$", re.MULTILINE),  # Horizontal rules
    "strikethrough": re.compile(r"~~([^~]+)~~"),  # Strikethrough text
    "header": re.compile(r"^(#{1,6}) (.*)$", re.MULTILINE),  # Headers (atomic, no backtracking)
}


def strip_markdown(text: str) -> str:
    """Remove markdown formatting from text for clean copy functionality.

    Handles nested formatting by processing in multiple passes using pre-compiled
    regex patterns for better performance.

    Args:
        text: Text with markdown formatting

    Returns:
        Text with markdown formatting removed
    """
    if not text:
        return text

    # Remove code blocks and inline code (1 pass)
    text = _MARKDOWN_PATTERNS["code"].sub(lambda m: m.group(1) if m.group(1) else "", text)

    # Remove images and links (1 pass)
    text = _MARKDOWN_PATTERNS["image_link"].sub(lambda m: m.group(1) or m.group(2) or "", text)

    # Remove horizontal rules, strikethrough, and headers (3 passes)
    text = _MARKDOWN_PATTERNS["horizontal_rule"].sub("", text)
    text = _MARKDOWN_PATTERNS["strikethrough"].sub(r"\1", text)
    text = _MARKDOWN_PATTERNS["header"].sub(r"\2", text)

    # Remove bold and italic - process multiple times for nested formatting
    # First pass (2 passes)
    text = _MARKDOWN_PATTERNS["bold"].sub(r"\2", text)
    text = _MARKDOWN_PATTERNS["italic"].sub(r"\2", text)

    # Second pass to catch remaining nested formatting (2 passes)
    text = _MARKDOWN_PATTERNS["bold"].sub(r"\2", text)
    text = _MARKDOWN_PATTERNS["italic"].sub(r"\2", text)

    return text
