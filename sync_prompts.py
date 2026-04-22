# mypy: ignore-errors
# pylint: skip-file

"""Sync prompts from GitHub to Langfuse."""

import sys

from langfuse import get_client

from common.logging.core import log_error, logger
from common.prompts import COMMON_PROMPTS_DIR

products_instructions = "products_instructions"
savings_instructions = "savings_instructions"
homebuying_instructions = "homebuying_instructions"
principal_instructions = "principal_instructions"
input_guardrail_instructions = "input_guardrail_instructions"
output_guardrail_instructions = "output_guardrail_instructions"
investinghub_instructions = "investinghub_instructions"
investinghub_phase_2_instructions = "investinghub_phase_2_instructions"


def get_instructions_path(instructions: str) -> str:
    """Map instruction names to their corresponding markdown file paths.

    Returns the file path for the given instruction name.
    """
    base_path = "apps/companion/all_agents"
    if instructions == principal_instructions:
        return f"{COMMON_PROMPTS_DIR}/{instructions}.md"

    if instructions in [input_guardrail_instructions, output_guardrail_instructions]:
        return f"{base_path}/guardrails/prompts/{instructions}.md"

    agent_name = instructions_to_agent(instructions)
    return f"{base_path}/task_agents/{agent_name}/prompts/{instructions}.md"


def instructions_to_agent(instructions: str) -> str:
    """Map instruction names to their corresponding agent folder names.

    Returns the agent folder name for the given instruction name.
    """
    if instructions == products_instructions:
        return "products_agent"
    if instructions == savings_instructions:
        return "savings_agent"
    if instructions == homebuying_instructions:
        return "homeloans_agent"
    if instructions in [investinghub_instructions, investinghub_phase_2_instructions]:
        return "investinghub_agent"
    return ""


def main():
    """Main function to sync prompts."""
    instructions = [
        products_instructions,
        savings_instructions,
        homebuying_instructions,
        principal_instructions,
        input_guardrail_instructions,
        output_guardrail_instructions,
        investinghub_instructions,
        investinghub_phase_2_instructions,
    ]

    langfuse = get_client()
    any_failed_updates = False
    failed_updates = []
    for instruction in instructions:
        try:
            prompt = langfuse.get_prompt(instruction, label="production")
            file_path = get_instructions_path(instruction)
            logger.info(
                f"Syncing prompt from GitHub file '{file_path}' to Langfuse prompt '{instruction}'",
                extra={"file_path": file_path, "instruction": instruction},
            )
            with open(f"./{file_path}", encoding="utf-8") as f:
                contents = f.read()
                langfuse_bytes = prompt.prompt.encode("utf-8")
                local_bytes = contents.encode("utf-8")

                if langfuse_bytes == local_bytes:
                    logger.info(f"Skipping, as Langfuse and GitHub prompt is the same for '{instruction}'")
                    continue

                langfuse.create_prompt(
                    name=instruction,
                    type="text",
                    prompt=contents,
                    labels=["production"],
                )

        except Exception as e:
            log_error(e, context="sync_prompts", instruction=instruction, file_path=file_path)
            any_failed_updates = True
            failed_updates.append(instruction)
            continue

    if any_failed_updates:
        log_error(f"Some prompts failed to update: {failed_updates}")
        sys.exit(1)


if __name__ == "__main__":
    main()
