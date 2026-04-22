"""LLM Scratchpad Tool for structured output through iterative editing.

This tool provides a clean interface for LLMs to create structured output
through an edit/check cycle with automatic verification against a Pydantic model.
"""

import pydantic
import yaml


class VerificationResult(pydantic.BaseModel):
    """Result of scratchpad content verification."""

    success: bool
    errors: list[str] = pydantic.Field(default_factory=list)
    guidance: str | None = ""

    def __str__(self) -> str:
        if self.success:
            return "✓ Verification successful"

        error_details = "\n".join([f"  - {error}" for error in self.errors])
        result = f"✗ Verification failed:\n{error_details}"

        if self.guidance:
            result += f"\n\nGuidance: {self.guidance}"

        return result


class ScratchpadTool:
    """LLM tool for iterative structured content creation with Pydantic validation.

    Features:
    - Needle/replace style editing with old_text/new_text
    - Automatic verification after each edit
    - Detailed error reporting with fix guidance
    - Reset functionality to clear state
    - Developer-controlled state management
    """

    def __init__(self, validator_model: type[pydantic.BaseModel]):
        """Initialize the scratchpad tool with a Pydantic validator model.

        Args:
            validator_model: Pydantic model class for content validation
        """
        self.validator_model = validator_model
        self.content = ""

    def edit(self, old_text: str, new_text: str) -> VerificationResult:
        """Edit the scratchpad content using needle/replace and verify the result.

        Args:
            old_text: Text to find and replace; if empty the `new_text` will be appended
            new_text: Text to replace with

        Returns:
            VerificationResult: Result of the edit and verification
        """
        if not old_text:
            self.content = self.content + new_text
        else:
            if old_text not in self.content:
                return VerificationResult(
                    success=False,
                    errors=[f"Text not found: '{old_text}'"],
                    guidance="Make sure the old_text exactly matches existing content, including whitespace and formatting.",
                )

            # Check for multiple occurrences
            count = self.content.count(old_text)
            if count > 1:
                return VerificationResult(
                    success=False,
                    errors=[f"Text appears {count} times: '{old_text}'"],
                    guidance="Ensure needle only appears once. Use more specific text to target a single occurrence.",
                )

            # Perform the replacement
            self.content = self.content.replace(old_text, new_text)

        # Automatically verify after edit
        return self.verify()

    def verify(self) -> VerificationResult:
        """Verify the current scratchpad content against the Pydantic model.

        Returns:
            VerificationResult: Detailed verification result with errors and guidance
        """
        if not self.content.strip():
            return VerificationResult(
                success=False,
                errors=["Empty content"],
                guidance="Add some content to the scratchpad before verification.",
            )

        # Try to parse as YAML
        try:
            parsed_data = yaml.safe_load(self.content)
        except yaml.YAMLError as e:
            return VerificationResult(
                success=False,
                errors=[f"YAML parsing error: {e!s}"],
                guidance="Ensure the content is valid YAML or JSON format.",
            )

        # Check if parsed_data is a dict (required for Pydantic model)
        if not isinstance(parsed_data, dict):
            return VerificationResult(
                success=False,
                errors=[f"Content must be a valid YAML/JSON object, got {type(parsed_data).__name__}"],
                guidance="Ensure the content is a valid YAML or JSON object with key-value pairs.",
            )

        try:
            # Validate against Pydantic model
            self.validator_model(**parsed_data)
            return VerificationResult(success=True)
        except pydantic.ValidationError as e:
            errors = []
            guidance_parts = []

            for error in e.errors():
                field_path = " -> ".join(str(loc) for loc in error["loc"])
                error_msg_text = error.get("msg", "")
                error_msg = f"{field_path}: {error_msg_text}"
                errors.append(error_msg)

                # Provide guidance based on error type
                error_type = error["type"]
                if error_type == "missing":
                    guidance_parts.append(f'Add required field "{field_path}"')
                elif error_type == "value_error":
                    guidance_parts.append(f'Fix value for "{field_path}": {error_msg_text}')
                elif error_type == "type_error":
                    expected_type = error.get("ctx", {}).get("expected_type", "correct type")
                    guidance_parts.append(f'Check data type for "{field_path}": expected {expected_type}')

            guidance = "; ".join(set(guidance_parts))

            return VerificationResult(
                success=False,
                errors=errors,
                guidance=guidance
                or "Review the Pydantic model requirements and ensure all fields are correctly formatted.",
            )

    def reset(self) -> None:
        """Clear the scratchpad state."""
        self.content = ""

    def get_content(self) -> str:
        """Get the current raw scratchpad content."""
        return self.content

    def set_content(self, content: str) -> VerificationResult:
        """Set the scratchpad content directly and verify.

        Args:
            content: Raw text content to set

        Returns:
            VerificationResult: Result of setting content and verification
        """
        self.content = content
        return self.verify()
