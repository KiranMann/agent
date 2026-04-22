#!/usr/bin/env python3
"""Combine CSV files per prefix from a given input folder into consolidated CSVs.

Usage:
  python3 scripts/dm_extract/combine_csvs.py <input_folder> [--output <output_subfolder>] [--prefixes p1 p2 ...]
  python3 scripts/dm_extract/combine_csvs.py --input-dir <input_folder> [--output-dir <output_subfolder>] [--prefixes p1 p2 ...]

Behavior:
- Scans the input folder for CSV files that start with any of the specified prefixes
- For each prefix, merges all matching CSVs into a single output CSV inside <input_folder>/<output_subfolder>
- Uses the union of columns across files (ordered by first appearance). Missing values are left blank
- Skips empty files gracefully. Handles UTF-8 and UTF-8 with BOM inputs

Examples:
  python3 scripts/dm_extract/combine_csvs.py demo
  python3 scripts/dm_extract/combine_csvs.py demo --output combined
  python3 scripts/dm_extract/combine_csvs.py --input-dir demo --output-dir combined
  python3 scripts/dm_extract/combine_csvs.py --input-dir demo --prefixes activities conversations

"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_PREFIXES = [
    "activities",
    "activity_reviews",
    "conversations",
    "conversation_reviews",
    "system_event",
]


def find_prefix_files(input_dir: Path, prefix: str) -> list[Path]:
    """Return sorted list of CSV files in input_dir that start with prefix and end with .csv."""
    candidates = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    files = sorted([p for p in candidates if p.name.startswith(prefix)])
    return files


def read_header(path: Path) -> list[str]:
    """Read the first row as header from a CSV file (UTF-8 or UTF-8 BOM). Empty file returns []."""
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return []
            return [h.strip() for h in header]
    except Exception as e:
        logger.warning("Failed to read header from %s: %s", path, e)
        return []


def union_headers(files: Iterable[Path]) -> list[str]:
    """Create an ordered union of headers across the given files, preserving first-seen order."""
    seen = set()
    union: list[str] = []
    for f in files:
        header = read_header(f)
        for col in header:
            if col not in seen:
                seen.add(col)
                union.append(col)
    return union


def ensure_output_dir(base_dir: Path, output_subfolder: str) -> Path:
    out_dir = base_dir / output_subfolder
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def normalize_row(row: dict[str, str], fieldnames: list[str]) -> dict[str, str]:
    return {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in fieldnames}


def combine_files(files: list[Path], out_path: Path, fieldnames: list[str]) -> int:
    """Combine given CSV files into out_path using fieldnames union. Returns number of written rows."""
    count = 0
    with out_path.open("w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        for src in files:
            try:
                with src.open("r", newline="", encoding="utf-8-sig") as in_f:
                    reader = csv.DictReader(in_f)
                    for row in reader:
                        writer.writerow(normalize_row(row, fieldnames))
                        count += 1
            except Exception as e:
                logger.warning("Skipping %s due to read error: %s", src, e)
        return count


def run(input_folder: Path, output_subfolder: str, prefixes: list[str]) -> None:
    if not input_folder.exists() or not input_folder.is_dir():
        logger.error("Input folder not found or not a directory: %s", input_folder)
        sys.exit(1)

    out_dir = ensure_output_dir(input_folder, output_subfolder)

    logger.info("Input folder: %s", input_folder)
    logger.info("Output folder: %s", out_dir)
    logger.info("Prefixes: %s", prefixes)

    any_output = False
    for prefix in prefixes:
        files = find_prefix_files(input_folder, prefix)
        if not files:
            logger.info("No files for prefix '%s'", prefix)
            continue
        logger.info("Found %d file(s) for prefix '%s':", len(files), prefix)
        for f in files:
            logger.info("       - %s", f.name)

        fieldnames = union_headers(files)
        if not fieldnames:
            logger.warning("No headers found across files for prefix '%s'. Skipping.", prefix)
            continue

        out_path = out_dir / f"{prefix}_combined.csv"
        rows = combine_files(files, out_path, fieldnames)
        logger.info(
            "Wrote %d row(s) to %s with columns: %s",
            rows,
            out_path.relative_to(input_folder),
            fieldnames,
        )
        any_output = True

    if not any_output:
        logger.info("No outputs created. Ensure your folder contains CSVs with the given prefixes.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine per-prefix CSV files from a folder")
    # Positional input folder made optional to support --input-dir
    parser.add_argument(
        "input_folder",
        nargs="?",
        type=str,
        help="Path to the folder containing CSV files",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        help="Input folder containing CSV files (alias to positional input_folder)",
    )
    # Original --output retained; new alias --output-dir added
    parser.add_argument(
        "--output",
        type=str,
        default="combined",
        help="Name of the output subfolder created inside the input folder (default: combined)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Alias for --output; overrides --output if provided",
    )
    parser.add_argument(
        "--prefixes",
        nargs="*",
        default=DEFAULT_PREFIXES,
        help="Optional list of prefixes to include (default: built-in list)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    # Resolve input directory preferring --input-dir, falling back to positional
    chosen_input = args.input_dir or args.input_folder
    if not chosen_input:
        logger.error("Missing input folder. Provide --input-dir or a positional <input_folder>.")
        parse_args(["--help"])  # This prints help
        sys.exit(2)

    # Resolve output subfolder preferring --output-dir, falling back to --output
    output_subfolder = args.output_dir or args.output

    input_folder = Path(chosen_input)
    run(input_folder, output_subfolder, args.prefixes)


if __name__ == "__main__":
    main()
