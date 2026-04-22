"""Security redactor for sensitive information in logs.

This module provides the SecurityRedactor class for redacting sensitive information
from log messages including PII, financial data, and authentication credentials.
"""

import re
from typing import ClassVar

# Constants for validation
ABN_LENGTH = 11


class SecurityRedactor:
    """Handles redaction of sensitive information from logs."""

    # Pre-compile regex patterns for structured text redaction (key=value pairs)
    _STRUCTURED_TEXT_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        # Authentication & Authorization
        (re.compile(r"session_id=[0-9a-z-]+", re.IGNORECASE), "session_id=REDACTED"),
        (re.compile(r"token=[0-9a-z._-]+", re.IGNORECASE), "token=REDACTED"),
        (re.compile(r"password=[^&\s]+", re.IGNORECASE), "password=REDACTED"),
        (re.compile(r"api_key=[^&\s]+", re.IGNORECASE), "api_key=REDACTED"),
        (re.compile(r"Authorization:\s*Bearer\s+[^\s]+", re.IGNORECASE), "Authorization: Bearer REDACTED"),
        (re.compile(r"Authorization:\s*Splunk\s+[^\s]+", re.IGNORECASE), "Authorization: Splunk REDACTED"),
        # Customer Identifiers
        (re.compile(r"customer_id[\"']?\s*[:=]\s*[\"']?[a-z0-9_-]+[\"']?", re.IGNORECASE), "customer_id=REDACTED"),
        (re.compile(r"cif_code[\"']?\s*[:=]\s*[\"']?[a-z0-9_-]+[\"']?", re.IGNORECASE), "cif_code=REDACTED"),
        (re.compile(r"netbank_id[\"']?\s*[:=]\s*[\"']?[a-z0-9_-]+[\"']?", re.IGNORECASE), "netbank_id=REDACTED"),
        (re.compile(r"user_id[\"']?\s*[:=]\s*[\"']?[a-z0-9_-]+[\"']?", re.IGNORECASE), "user_id=REDACTED"),
        # Account Numbers & BSB
        (re.compile(r"account_number[\"']?\s*[:=]\s*[\"']?\d{4,16}[\"']?", re.IGNORECASE), "account_number=REDACTED"),
        (re.compile(r"accountNumber[\"']?\s*[:=]\s*[\"']?\d{4,16}[\"']?", re.IGNORECASE), "accountNumber=REDACTED"),
        (re.compile(r"account_id[\"']?\s*[:=]\s*[\"']?[a-z0-9_-]+[\"']?", re.IGNORECASE), "account_id=REDACTED"),
        (re.compile(r"bsb[\"']?\s*[:=]\s*[\"']?\d{3}[-\s]?\d{3}[\"']?", re.IGNORECASE), "bsb=REDACTED"),
        (
            re.compile(r"hashed_account_number[\"']?\s*[:=]\s*[\"']?[a-f0-9]{40,}[\"']?", re.IGNORECASE),
            "hashed_account_number=REDACTED",
        ),
        (
            re.compile(r"debtor_account_number_hash[\"']?\s*[:=]\s*[\"']?[a-f0-9]{40,}[\"']?", re.IGNORECASE),
            "debtor_account_number_hash=REDACTED",
        ),
        # Credit Card Numbers
        (re.compile(r"card_number[\"']?\s*[:=]\s*[\"']?\d+[\"']?", re.IGNORECASE), "card_number=REDACTED"),
        (re.compile(r"credit_card[\"']?\s*[:=]\s*[\"']?\d+[\"']?", re.IGNORECASE), "credit_card=REDACTED"),
        # Email Addresses
        (re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE), "EMAIL_REDACTED"),
        (re.compile(r"email[\"']?\s*[:=]\s*[\"']?[^\"'\s,}]+@[^\"'\s,}]+[\"']?", re.IGNORECASE), "email=REDACTED"),
        # Phone Numbers (Australian format and international)
        (re.compile(r"\b(?:\+61|0)[2-478](?:[\s-]?\d{4}[\s-]?\d{4}|\d{8})\b", re.IGNORECASE), "PHONE_REDACTED"),
        (re.compile(r"phone[\"']?\s*[:=]\s*[\"']?[\d\s\-\+()]+[\"']?", re.IGNORECASE), "phone=REDACTED"),
        (re.compile(r"mobile[\"']?\s*[:=]\s*[\"']?[\d\s\-\+()]+[\"']?", re.IGNORECASE), "mobile=REDACTED"),
        # Australian Business Number (ABN) and Australian Company Number (ACN) - must come before TFN
        (re.compile(r"\babn[\"']?\s*[:=]\s*[\"']?\d{11}[\"']?", re.IGNORECASE), "abn=REDACTED"),
        (re.compile(r"\bacn[\"']?\s*[:=]\s*[\"']?\d{9}[\"']?", re.IGNORECASE), "acn=REDACTED"),
        # Tax File Number (TFN) (after ABN/ACN to avoid conflicts)
        (re.compile(r"\btfn[\"']?\s*[:=]\s*[\"']?\d{8,9}[\"']?", re.IGNORECASE), "tfn=REDACTED"),
        # BPAY Details
        (re.compile(r"biller_code[\"']?\s*[:=]\s*[\"']?\d{4,6}[\"']?", re.IGNORECASE), "biller_code=REDACTED"),
        (re.compile(r"crn[\"']?\s*[:=]\s*[\"']?[\d\s-]+[\"']?", re.IGNORECASE), "crn=REDACTED"),
    ]

    # Patterns for redacting sensitive data from free-form text (no key=value pairs)
    # Order matters: more specific patterns should come before more general ones
    _FREE_TEXT_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        # Individual Healthcare Identifier (IHI) - 16 digits with context
        (
            re.compile(r"\b(?:IHI|healthcare\s+identifier)[\s#:]*\d{16}\b", re.IGNORECASE),
            r"IHI [IHI_REDACTED]",
        ),
        # DVA (Department of Veterans' Affairs) File Number - typically 2 letters + 6 digits
        (
            re.compile(r"\b(?:DVA|veterans?\s+affairs\s+file)[\s#:]*[A-Z]{2}\d{6}\b", re.IGNORECASE),
            r"DVA [DVA_NUMBER_REDACTED]",
        ),
        # Visa Grant Number - typically 10-13 digits with context
        (
            re.compile(r"\b(?:visa|grant\s+number)[\s#:]*\d{10,13}\b", re.IGNORECASE),
            r"visa [VISA_NUMBER_REDACTED]",
        ),
        # Vehicle Registration (Rego) - varies by state, typically 3-6 alphanumeric with context
        (
            re.compile(r"\b(?:rego|registration|vehicle\s+reg)[\s#:]*([A-Z0-9]{3,7})\b", re.IGNORECASE),
            r"rego [VEHICLE_REGO_REDACTED]",
        ),
        # Centrelink Customer Reference Number (CRN) - 9 digits followed by a letter (with or without CRN prefix)
        (re.compile(r"\bCRN[\s:]*\d{9}[A-Z]\b", re.IGNORECASE), "[CRN_REDACTED]"),
        # CRN without prefix - 9 digits followed by a letter (standalone pattern)
        (re.compile(r"\b\d{9}[A-Z]\b", re.IGNORECASE), "[CRN_REDACTED]"),
        # Australian passport numbers (1 letter followed by 7 digits)
        (re.compile(r"\b[A-Z]\d{7}\b", re.IGNORECASE), "[PASSPORT_REDACTED]"),
        # Australian Medicare numbers with context (to avoid false positives with phone numbers)
        # Format: 2345 67890 1 or 2345678901/1 or just 2345678901 (but with Medicare context)
        (
            re.compile(r"\b(?:medicare|health\s+card)[\s#:]*\d{4}[\s-]?\d{5}[\s-]?\d(?:[\s/-]?\d)?\b", re.IGNORECASE),
            r"medicare [MEDICARE_REDACTED]",
        ),
        # Medicare numbers in specific formats (with spaces/dashes that distinguish from phone numbers)
        (re.compile(r"\b\d{4}[\s-]\d{5}[\s-]\d(?:[\s/-]\d)?\b", re.IGNORECASE), "[MEDICARE_REDACTED]"),
        # Australian Driver's Licence - varies by state, typically 6-10 alphanumeric characters
        # Using context words to avoid false positives
        (
            re.compile(r"\b(?:driver'?s?\s+licen[cs]e|DL|licence\s+number)[\s#:]+([A-Z0-9]{6,10})\b", re.IGNORECASE),
            r"licence [DRIVERS_LICENCE_REDACTED]",
        ),
        # Email addresses in free text
        (re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE), "[EMAIL_REDACTED]"),
        # Credit card numbers (16 digits with optional spaces/dashes) - check early to avoid conflicts
        (
            re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", re.IGNORECASE),
            "[CARD_NUMBER_REDACTED]",
        ),
        # Australian phone numbers in free text (handles various formats including +61)
        # +61 format: +61 followed by 9 digits (area code + number)
        (re.compile(r"\+61[\s-]?[2-478][\s-]?\d{8}\b", re.IGNORECASE), "[PHONE_REDACTED]"),
        # Handle phone numbers with spaces first: 0412 345 678 (3-3-3 format)
        (re.compile(r"\b0[2-478]\d{2}[\s-]\d{3}[\s-]\d{3}\b", re.IGNORECASE), "[PHONE_REDACTED]"),
        # 0 format: 0 followed by area code and 8 digits (no spaces)
        (re.compile(r"\b0[2-478]\d{8}\b", re.IGNORECASE), "[PHONE_REDACTED]"),
        # Australian Business Numbers (11 digits) - with ABN prefix
        (re.compile(r"\bABN[\s:]*\d{11}\b", re.IGNORECASE), "[ABN_REDACTED]"),
        # Australian Company Numbers (9 digits) - check before TFN
        (re.compile(r"\bACN[\s:]*\d{9}\b", re.IGNORECASE), "[ACN_REDACTED]"),
        # Australian Tax File Numbers (8-9 digits) - check after ACN
        (re.compile(r"\bTFN[\s:]*\d{8,9}\b", re.IGNORECASE), "[TFN_REDACTED]"),
        # BSB numbers (6 digits with optional dash)
        (re.compile(r"\bBSB[\s:]*\d{3}[-\s]?\d{3}\b", re.IGNORECASE), "[BSB_REDACTED]"),
        # Account numbers (6-16 digits) - only with context words to avoid false positives
        (
            re.compile(
                r"\b(?:account|acc|acct)[\s#:]+(\d{6,16})\b",
                re.IGNORECASE,
            ),
            r"account [ACCOUNT_NUMBER_REDACTED]",
        ),
    ]

    # Pattern for ABN validation in free text
    _ABN_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"\b\d{11}\b")

    @staticmethod
    def redact_sensitive_data_from_structured_text(log_message: str) -> str:
        """Redact sensitive data from structured key=value fields in log messages.

        This method targets structured data patterns commonly found in log messages,
        such as session_id=abc123, email=user@example.com, account_number=12345, etc.
        It redacts the values while preserving the field names for log analysis.

        Args:
            log_message: Structured log message string (e.g., from application logs)

        Returns:
            Log message with sensitive field values redacted using REDACTED placeholders

        Example:
            >>> log = "User login: user_id=U123 email=test@example.com session_id=abc-123"
            >>> SecurityRedactor.redact_sensitive_data_from_structured_text(log)
            "User login: user_id=REDACTED email=REDACTED session_id=REDACTED"
        """
        redacted = log_message
        for pattern, replacement in SecurityRedactor._STRUCTURED_TEXT_PATTERNS:
            redacted = pattern.sub(replacement, redacted)

        return redacted

    @classmethod
    def redact_sensitive_data_from_free_text(cls, user_text: str) -> str:
        """Redact sensitive data from unstructured free-form user text.

        This method is designed for user-entered conversational text where we want to
        redact sensitive information like emails, phone numbers, and financial identifiers
        that appear naturally in sentences, without redacting structured log data like
        key=value pairs.

        ABN validation: 11-digit numbers are validated using the ABN checksum algorithm
        to reduce false positives before redaction.

        Args:
            user_text: Free text string entered by a user (e.g., chat messages, descriptions)

        Returns:
            Text with PII redacted using bracketed placeholders like [EMAIL_REDACTED]

        Example:
            >>> text = "My email is john@example.com and phone is 0412345678"
            >>> SecurityRedactor.redact_sensitive_data_from_free_text(text)
            "My email is [EMAIL_REDACTED] and phone is [PHONE_REDACTED]"
        """
        # First pass: Find and redact valid ABNs (11-digit numbers with valid checksum)
        redacted = cls.redact_abns(user_text)

        # Second pass: Apply all other PII patterns
        for pattern, replacement in cls._FREE_TEXT_PATTERNS:
            redacted = pattern.sub(replacement, redacted)

        return redacted

    @classmethod
    def redact_abns(cls, text: str) -> str:
        """Redact valid Australian Business Numbers from text.

        This method efficiently validates and redacts ABNs using a single regex
        substitution pass with a callback function.

        Args:
            text: Text string that may contain ABNs

        Returns:
            Text with valid ABNs redacted as [ABN_REDACTED]
        """

        def repl(m: re.Match[str]) -> str:
            abn = m.group(0)
            return "[ABN_REDACTED]" if cls._is_valid_abn(abn) else abn

        return cls._ABN_PATTERN.sub(repl, text)

    @classmethod
    def _is_valid_abn(cls, abn_str: str) -> bool:
        """Validate Australian Business Number using checksum algorithm.

        Args:
            abn_str: String containing 11 digits

        Returns:
            True if the ABN passes checksum validation, False otherwise
        """
        # Remove any spaces or dashes
        abn = abn_str.replace(" ", "").replace("-", "")

        if len(abn) != ABN_LENGTH or not abn.isdigit():
            return False

        # ABN checksum algorithm
        weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
        digits = [int(d) for d in abn]

        # Subtract 1 from the first digit
        digits[0] -= 1

        # Multiply each digit by its weight and sum
        total = sum(digit * weight for digit, weight in zip(digits, weights, strict=True))

        # Valid if divisible by 89
        return total % 89 == 0
