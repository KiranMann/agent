#!/usr/bin/env python3
"""Activity Annotations Extractor.

This script processes Excel or CSV files containing activity_annotations column with JSON data
and extracts question answers into separate columns.
"""

import argparse
import ast
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def log_error(exc: Exception, *, context: str) -> None:
    """Log an exception with lightweight context.

    This keeps the script standalone from the FC repo's logging utilities.
    """
    logger.exception("%s: %s", context, exc)


# Logging and lint constants
MAX_JSON_WARNINGS: int = 5
SUPPRESS_NOTICE_AT: int = MAX_JSON_WARNINGS + 1


def safe_json_parse(json_str: str) -> dict[str, Any]:
    """Safely parse JSON string with common fixes for malformed JSON.

    Args:
        json_str: JSON string to parse

    Returns:
        Parsed JSON dictionary or empty dict if parsing fails
    """
    try:
        # First try standard JSON parsing
        data = json.loads(json_str)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        try:
            # Try to fix common issues like single quotes instead of double quotes
            # Replace single quotes with double quotes (basic fix)
            fixed_str = json_str.replace("'", '"')
            data = json.loads(fixed_str)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            try:
                # Try using ast.literal_eval for Python-style dictionaries
                result = ast.literal_eval(json_str)
                return result if isinstance(result, dict) else {}
            except (ValueError, SyntaxError):
                # If all parsing attempts fail, return empty dict
                return {}


def extract_question_answers_and_reasons(
    json_data: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Extract question answers and reasoning from the checklist JSON structure.

    Args:
        json_data: The parsed JSON data from activity_annotations column

    Returns:
        Tuple of (answers_dict, reasons_dict) where:
        - answers_dict: Maps question text to answer values (including guardrail checkbox selections)
        - reasons_dict: Maps question text to reasoning text from noReasonTexts
    """
    answers: dict[str, str] = {}
    reasons: dict[str, str] = {}

    try:
        checklist = json_data.get("checklist", {})
        question_tree = checklist.get("questionTree", [])
        main_questions = checklist.get("mainQuestions", {})
        no_reason_texts = checklist.get("noReasonTexts", {})
        checkboxes = checklist.get("checkboxes", {}) or {}

        # Create mapping from question ID to question text
        id_to_question: dict[str, str] = {}

        # Build the mapping from questionTree
        def process_questions(question_list: list[dict[str, Any]]) -> None:
            for question_item in question_list:
                question_id = question_item.get("id", "")
                question_text = question_item.get("question", "")

                if question_id and question_text:
                    id_to_question[str(question_id)] = str(question_text)

                # Process children if they exist
                children = question_item.get("children", [])
                if children:
                    process_questions(children)

        process_questions(question_tree)

        # Extract answers from mainQuestions using the ID to question text mapping
        for question_id, answer in main_questions.items():
            qid = str(question_id)
            if qid in id_to_question:
                question_text = id_to_question[qid]
                answers[question_text] = str(answer)

        # Map reasoning texts to question texts
        for question_id, reason_text in no_reason_texts.items():
            qid = str(question_id)
            if qid in id_to_question:
                question_text = id_to_question[qid]
                reasons[question_text] = str(reason_text)

        # Helper to find a node by id in a tree
        def find_node_by_id(nodes: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
            for node in nodes:
                if node.get("id") == target_id:
                    return node
                child_nodes = node.get("children", [])
                if child_nodes:
                    found = find_node_by_id(child_nodes, target_id)
                    if found:
                        return found
            return None

        # Extract guardrail checkbox selections into dedicated columns
        guardrails_node = find_node_by_id(question_tree, "guardrails_trigger")
        if guardrails_node:
            for category_id in ("should_have_triggered", "incorrectly_triggered"):
                category_node = find_node_by_id(guardrails_node.get("children", []), category_id)
                # Determine display column name
                if category_id in id_to_question:
                    column_name: str = id_to_question[category_id]
                elif category_node and isinstance(category_node.get("question"), str):
                    column_name = str(category_node.get("question"))
                else:
                    column_name = category_id

                selected_labels: list[str] = []
                if category_node:
                    # Build id -> label map from children
                    options = category_node.get("children", [])
                    id_to_label: dict[str, str] = {}
                    for opt in options:
                        opt_id_any: Any = opt.get("id")
                        if isinstance(opt_id_any, str):
                            opt_id = opt_id_any
                            label_val = opt.get("question", opt_id)
                            id_to_label[opt_id] = str(label_val)
                    prefix = f"guardrails_trigger-{category_id}"
                    for opt_id, label in id_to_label.items():
                        if checkboxes.get(f"{prefix}-{opt_id}", False):
                            selected_labels.append(str(label))

                answers[column_name] = ", ".join(selected_labels) if selected_labels else "N/A"

    except Exception as e:
        log_error(e, context="extract_question_answers_and_reasons")

    return answers, reasons


def extract_question_answers(json_data: dict[str, Any]) -> dict[str, str]:
    """Extract question answers from the checklist JSON structure.

    Args:
        json_data: The parsed JSON data from activity_annotations column

    Returns:
        Dictionary mapping question text to answer values
    """
    answers, _ = extract_question_answers_and_reasons(json_data)
    return answers


def get_all_unique_questions(df: pd.DataFrame, column_name: str) -> set[str]:
    """Get all unique questions across all rows to ensure consistent columns.

    Args:
        df: DataFrame containing the data
        column_name: Name of the column containing JSON data

    Returns:
        Set of all unique question texts
    """
    all_questions: set[str] = set()
    parse_errors = 0

    for idx, row in df.iterrows():
        try:
            if pd.notna(row[column_name]):
                json_str = str(row[column_name])
                json_data = safe_json_parse(json_str)
                if json_data:  # Only process if parsing was successful
                    answers = extract_question_answers(json_data)
                    all_questions.update(answers.keys())
                else:
                    parse_errors += 1
        except Exception as e:
            logger.warning("Could not process row %s: %s", idx, e)
            parse_errors += 1
            continue

    if parse_errors > 0:
        logger.info("%d rows had JSON parsing issues and were skipped", parse_errors)

    return all_questions


def get_all_unique_questions_and_reasons(df: pd.DataFrame, column_name: str) -> tuple[set[str], set[str]]:
    """Get all unique questions and reasoning keys across all rows to ensure consistent columns.

    Args:
        df: DataFrame containing the data
        column_name: Name of the column containing JSON data

    Returns:
        Tuple of (unique_questions_set, unique_reason_questions_set)
    """
    all_questions: set[str] = set()
    all_reason_questions: set[str] = set()
    parse_errors = 0

    for idx, row in df.iterrows():
        try:
            if pd.notna(row[column_name]):
                json_str = str(row[column_name])
                json_data = safe_json_parse(json_str)
                if json_data:  # Only process if parsing was successful
                    answers, reasons = extract_question_answers_and_reasons(json_data)
                    all_questions.update(answers.keys())
                    all_reason_questions.update(reasons.keys())
                else:
                    parse_errors += 1
        except Exception as e:
            logger.warning("Could not process row %s: %s", idx, e)
            parse_errors += 1
            continue

    if parse_errors > 0:
        logger.info("%d rows had JSON parsing issues and were skipped", parse_errors)

    return all_questions, all_reason_questions


def detect_file_type(file_path: str) -> str:
    """Detect file type based on extension.

    Args:
        file_path: Path to the file

    Returns:
        File type: 'excel' or 'csv'
    """
    extension = Path(file_path).suffix.lower()
    if extension in [".xlsx", ".xls"]:
        return "excel"
    elif extension == ".csv":
        return "csv"
    else:
        raise ValueError(f"Unsupported file format: {extension}. Supported formats: .xlsx, .xls, .csv")


def read_file(file_path: str) -> pd.DataFrame:
    """Read file based on its type (Excel or CSV).

    Args:
        file_path: Path to the input file

    Returns:
        DataFrame containing the file data
    """
    file_type = detect_file_type(file_path)

    if file_type == "excel":
        return pd.read_excel(file_path)
    elif file_type == "csv":
        return pd.read_csv(file_path)

    # Unreachable since detect_file_type guards valid values
    raise AssertionError("Unsupported file type branch reached")


def save_file(df: pd.DataFrame, file_path: str) -> None:
    """Save DataFrame to file based on its type (Excel or CSV).

    Args:
        df: DataFrame to save
        file_path: Path to the output file
    """
    file_type = detect_file_type(file_path)

    if file_type == "excel":
        df.to_excel(file_path, index=False)
    elif file_type == "csv":
        df.to_csv(file_path, index=False)
    else:
        raise AssertionError("Unsupported file type branch reached")


def process_file(
    input_file: str,
    output_file: str,
    column_name: str = "activity_annotations",
    debug: bool = False,
) -> None:
    """Process the input file (Excel or CSV) and create new columns for each question.

    Args:
        input_file: Path to input file (Excel or CSV)
        output_file: Path to output file (Excel or CSV)
        column_name: Name of the column containing JSON data
        debug: If True, show detailed error information for JSON parsing failures
    """
    try:
        # Read the file
        input_type = detect_file_type(input_file)
        output_type = detect_file_type(output_file)

        logger.info("Reading %s file: %s", input_type.upper(), input_file)
        df = read_file(input_file)

        if column_name not in df.columns:
            raise ValueError(
                f"Column '{column_name}' not found in {input_type.upper()} file. Available columns: {list(df.columns)}"
            )

        logger.info("Found %d rows in the %s file", len(df), input_type.upper())

        # Get all unique questions and reasons to ensure consistent column structure
        logger.info("Extracting all unique questions and reasoning...")
        all_questions, all_reason_questions = get_all_unique_questions_and_reasons(df, column_name)
        logger.info(
            "Found %d unique questions and %d questions with reasoning",
            len(all_questions),
            len(all_reason_questions),
        )

        # Find the position of the target column
        target_col_index = df.columns.get_loc(column_name)

        # Create a list of sorted questions for consistent ordering
        sorted_questions = sorted(all_questions)

        # Insert new columns right after the target column
        # For each question, insert the question column first, then the reasoning column if it exists
        col_insert_offset = 1
        for question in sorted_questions:
            # Insert the question answer column
            df.insert(target_col_index + col_insert_offset, question, "N/A")
            col_insert_offset += 1

            # If this question has reasoning, insert the reasoning column right after
            if question in all_reason_questions:
                reason_col_name = f"{question} - Reasoning"
                df.insert(target_col_index + col_insert_offset, reason_col_name, "N/A")
                col_insert_offset += 1

        # Process each row
        logger.info("Processing rows and extracting answers...")
        processed_count = 0
        skipped_count = 0

        for idx, row in df.iterrows():
            try:
                if pd.notna(row[column_name]):
                    json_str = str(row[column_name])
                    json_data = safe_json_parse(json_str)

                    if json_data:  # Only process if parsing was successful
                        answers, reasons = extract_question_answers_and_reasons(json_data)

                        # Update the DataFrame with extracted answers
                        for question, answer in answers.items():
                            if question in df.columns:
                                df.at[idx, question] = answer

                        # Update the DataFrame with extracted reasoning
                        for question, reason in reasons.items():
                            reason_col_name = f"{question} - Reasoning"
                            if reason_col_name in df.columns:
                                df.at[idx, reason_col_name] = reason

                        processed_count += 1
                    else:
                        skipped_count += 1
                        if debug or skipped_count <= MAX_JSON_WARNINGS:  # Show all errors in debug mode
                            if debug:
                                logger.debug(
                                    "Row %s JSON parsing failed. Content preview: %s...",
                                    idx,
                                    json_str[:100],
                                )
                            else:
                                logger.warning(
                                    "Could not parse JSON in row %s - malformed JSON data",
                                    idx,
                                )
                        elif skipped_count == SUPPRESS_NOTICE_AT and not debug:
                            logger.info(
                                "... (suppressing further JSON parsing warnings - use --debug for full details)"
                            )

            except Exception as e:
                skipped_count += 1
                if debug or skipped_count <= MAX_JSON_WARNINGS:
                    logger.warning("Could not process row %s: %s", idx, e)
                elif skipped_count == SUPPRESS_NOTICE_AT and not debug:
                    logger.info("... (suppressing further processing warnings - use --debug for full details)")
                continue

        logger.info(
            "Successfully processed %d rows, skipped %d rows due to JSON issues",
            processed_count,
            skipped_count,
        )

        # Reorder columns: move guardrail category columns after parent reasoning column
        try:
            columns = list(df.columns)
            parent_reason_col = "Were all guardrails triggered appropriately? - Reasoning"
            parent_col = "Were all guardrails triggered appropriately?"
            child_cols = [
                "A guardrail should have triggered",
                "A guardrail was incorrectly triggered",
            ]
            existing_child_cols = [c for c in child_cols if c in columns]
            if existing_child_cols:
                if parent_reason_col in columns:
                    anchor_idx = columns.index(parent_reason_col) + 1
                elif parent_col in columns:
                    anchor_idx = columns.index(parent_col) + 1
                else:
                    anchor_idx = None
                if anchor_idx is not None:
                    # Remove children from current order and reinsert after anchor
                    for c in existing_child_cols:
                        columns.remove(c)
                    for i, c in enumerate(existing_child_cols):
                        columns.insert(anchor_idx + i, c)
                    df = df.reindex(columns=columns)
        except Exception as e:
            logger.warning("Could not reorder guardrail columns: %s", e)

        # Save the updated DataFrame
        logger.info("Saving results to %s file: %s", output_type.upper(), output_file)
        save_file(df, output_file)

        total_new_columns = len(all_questions) + len(all_reason_questions)
        logger.info(
            "Successfully created %s with %d new columns (%d questions + %d reasoning columns)",
            output_file,
            total_new_columns,
            len(all_questions),
            len(all_reason_questions),
        )

        # Log summary of extracted questions
        logger.info("Extracted Questions (in column order):")
        for i, question in enumerate(sorted_questions, 1):
            has_reasoning = question in all_reason_questions
            reasoning_suffix = " + Reasoning" if has_reasoning else ""
            logger.info("%d. %s%s", i, question, reasoning_suffix)

    except Exception:
        logger.exception("Error processing file")
        sys.exit(1)


def main() -> None:
    """Main function to handle command line arguments and run the processing."""
    parser = argparse.ArgumentParser(
        description="Extract question answers from Excel/CSV activity_annotations JSON column",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python dm_extract.py input.xlsx output.xlsx
  python dm_extract.py input.csv output.csv
  python dm_extract.py data.xlsx processed_data.csv --column activity_annotations
  python dm_extract.py data.csv processed_data.xlsx --column activity_annotations
        """,
    )

    parser.add_argument("input_file", help="Path to input file (Excel .xlsx/.xls or CSV .csv)")
    parser.add_argument("output_file", help="Path to output file (Excel .xlsx/.xls or CSV .csv)")
    parser.add_argument(
        "--column",
        default="activity_annotations",
        help="Name of column containing JSON data (default: activity_annotations)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show detailed error information for JSON parsing failures",
    )

    args = parser.parse_args()

    # Validate input file exists
    if not Path(args.input_file).exists():
        logger.error("Input file '%s' does not exist", args.input_file)
        sys.exit(1)

    try:
        # Validate file formats
        detect_file_type(args.input_file)
        detect_file_type(args.output_file)
    except ValueError:
        sys.exit(1)

    # Process the file
    process_file(args.input_file, args.output_file, args.column, args.debug)


if __name__ == "__main__":
    main()
