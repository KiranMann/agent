#!/usr/bin/env python3
"""Script to update the main evaluation results page with latest run information from child pages."""

import argparse
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger()


def extract_last_updated_info(file_path: Path) -> tuple[str | None, str | None]:
    """Extract last updated date and workflow run info from a child page.

    Returns:
        Tuple of (date, workflow_run_info) or (None, None) if not found
    """
    if not file_path.exists():
        return None, None

    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Look for "**Last Updated:** YYYY-MM-DD (from [workflow run ...])"
        pattern = r"\*\*Last Updated:\*\* (\d{4}-\d{2}-\d{2})(\s*\(from \[workflow run [^\]]+\]\([^)]+\)\))?"
        match = re.search(pattern, content)

        if match:
            date = match.group(1)
            workflow_info = match.group(2) if match.group(2) else ""
            return date, workflow_info.strip()

        # Check for "Not run yet" or similar status
        not_run_pattern = r"\*\*Last Updated:\*\* (Not run yet|Pending|Not available)"
        if re.search(not_run_pattern, content, re.IGNORECASE):
            logger.info(f"File {file_path} shows evaluation not run yet")
            return None, None

        return None, None

    except Exception as e:
        logger.warning(f"Could not read {file_path}: {e}")
        return None, None


def update_main_page_status(
    main_page_path: Path,
    single_turn_file: Path | None = None,
    multi_turn_file: Path | None = None,
) -> bool:
    """Update the main evaluation results page with latest status information.

    Args:
        main_page_path: Path to the main eval-results.md file
        single_turn_file: Path to single-turn results file (optional)
        multi_turn_file: Path to multi-turn results file (optional)

    Returns:
        True if the file was updated, False otherwise
    """
    # Extract information from child pages
    single_turn_date, single_turn_run = None, None
    multi_turn_date, multi_turn_run = None, None

    if single_turn_file:
        single_turn_date, single_turn_run = extract_last_updated_info(single_turn_file)
        logger.info(f"Single-turn info: date={single_turn_date}, run={single_turn_run}")

    if multi_turn_file:
        multi_turn_date, multi_turn_run = extract_last_updated_info(multi_turn_file)
        logger.info(f"Multi-turn info: date={multi_turn_date}, run={multi_turn_run}")

    # Read current main page content
    if not main_page_path.exists():
        logger.error(f"Main page not found: {main_page_path}")
        return False

    try:
        with open(main_page_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        logger.exception("Could not read main page")
        return False

    # Update the workflow status table
    lines = content.split("\n")
    updated_lines = []
    in_status_table = False
    table_header_found = False

    for line in lines:
        # Detect the workflow status table - updated to match actual table structure
        if "| Evaluation Type | Last Updated | Status | Workflow Run | GitHub Actions |" in line:
            in_status_table = True
            table_header_found = True
            updated_lines.append(line)
            continue
        elif in_status_table and line.startswith("|:"):
            # Table separator line
            updated_lines.append(line)
            continue
        elif in_status_table and line.startswith("| **Single-Turn** |"):
            # Update single-turn row only if we have new data, otherwise preserve existing
            if single_turn_file and single_turn_date:
                # We have new single-turn data, update the row
                status = "✅ Active"
                last_updated = single_turn_date
                workflow_run = single_turn_run.strip() if single_turn_run else "-"

                # Extract workflow run number and create proper link
                if single_turn_run and "workflow run" in single_turn_run:
                    # Extract run number from format like "(from [workflow run 19258483415](...)"
                    run_match = re.search(r"workflow run (\d+)", single_turn_run)
                    if run_match:
                        run_number = run_match.group(1)
                        workflow_run = f"[Run {run_number}](https://github.com/CBA-General/FinancialCompanion/actions/runs/{run_number})"

                updated_line = f"| **Single-Turn** | {last_updated} | {status} | {workflow_run} | [🔗 Workflow](https://github.com/CBA-General/FinancialCompanion/actions/workflows/run-evals-single-turn.yaml) |"
                updated_lines.append(updated_line)
            else:
                # No new single-turn data, preserve existing line
                updated_lines.append(line)
            continue
        elif in_status_table and line.startswith("| **Multi-Turn** |"):
            # Update multi-turn row only if we have new data, otherwise preserve existing
            if multi_turn_file and multi_turn_date:
                # We have new multi-turn data, update the row
                status = "✅ Active"
                last_updated = multi_turn_date
                workflow_run = multi_turn_run.strip() if multi_turn_run else "-"

                # Extract workflow run number and create proper link
                if multi_turn_run and "workflow run" in multi_turn_run:
                    # Extract run number from format like "(from [workflow run 19258483415](...)"
                    run_match = re.search(r"workflow run (\d+)", multi_turn_run)
                    if run_match:
                        run_number = run_match.group(1)
                        workflow_run = f"[Run {run_number}](https://github.com/CBA-General/FinancialCompanion/actions/runs/{run_number})"

                updated_line = f"| **Multi-Turn** | {last_updated} | {status} | {workflow_run} | [🔗 Workflow](https://github.com/CBA-General/FinancialCompanion/actions/workflows/run-evals-multi-turn.yaml) |"
                updated_lines.append(updated_line)
            else:
                # No new multi-turn data, preserve existing line
                updated_lines.append(line)
            continue
        elif in_status_table and (line.strip() == "" or not line.startswith("|")):
            # End of table
            in_status_table = False
            updated_lines.append(line)
            continue
        else:
            updated_lines.append(line)

    if not table_header_found:
        logger.warning("Workflow status table not found in main page")
        return False

    # Write updated content
    updated_content = "\n".join(updated_lines)

    try:
        with open(main_page_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        logger.info(f"Successfully updated main page: {main_page_path}")
        return True

    except Exception:
        logger.exception("Could not write to main page")
        return False


def main() -> int:
    """Main function to update the main evaluation results page."""
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Update main evaluation results page with latest run information")
    parser.add_argument(
        "--output-file",
        default="docs/project-management/eval-results.md",
        help="Path to main evaluation results file",
    )
    parser.add_argument("--single-turn-file", help="Path to single-turn results file")
    parser.add_argument("--multi-turn-file", help="Path to multi-turn results file")

    args = parser.parse_args()

    # Convert to Path objects
    main_page_path = Path(args.output_file)
    single_turn_file = Path(args.single_turn_file) if args.single_turn_file else None
    multi_turn_file = Path(args.multi_turn_file) if args.multi_turn_file else None

    # Validate inputs
    if not single_turn_file and not multi_turn_file:
        logger.error("At least one of --single-turn-file or --multi-turn-file must be provided")
        return 1

    # Update the main page
    success = update_main_page_status(main_page_path, single_turn_file, multi_turn_file)

    if success:
        logger.info("✅ Main evaluation results page updated successfully")
        return 0
    else:
        logger.error("❌ Failed to update main evaluation results page")
        return 1


if __name__ == "__main__":
    sys.exit(main())
