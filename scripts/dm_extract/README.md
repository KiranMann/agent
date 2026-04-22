# DM Extract Scripts

Utilities for working with Dialogue Monitoring exports. This folder contains two CLI tools:

- combine_csvs.py — Combines multiple CSVs by filename prefix into consolidated CSVs with a unified header
- dm_extract.py — Extracts structured answers and reasoning from a JSON "activity_annotations" column in Excel/CSV files

These are used to create the human-readable summaries from the DM extracts by first combining the multi-part CSVs then
expanding the activities checklist into separate columns.

Requirements

- Python 3.11+
- pandas (required for Excel/CSV IO)
- openpyxl (recommended for reading/writing .xlsx)

Standalone

- These scripts are fully standalone and do not depend on any other modules in the Financial Companion (FC) repository.
- They use only the Python standard library + pandas (and openpyxl for .xlsx).

Install

- pip install pandas openpyxl

combine_csvs.py — Combine CSVs by prefix with unified headers
Description

- Scans an input folder for CSV files whose filenames start with specified prefixes
- For each prefix, produces one combined CSV inside a subfolder (default: combined) under the input folder
- Uses the union of headers across all files for that prefix (keeps first-seen order); missing values are blank
- Skips empty files gracefully; supports UTF-8 and UTF-8 with BOM inputs

Default prefixes

- activities
- activity_reviews
- conversations
- conversation_reviews
- system_event

Usage

- python3 scripts/dm_extract/combine_csvs.py <input_folder> [--output <output_subfolder>] [--prefixes p1 p2 ...]
- python3 scripts/dm_extract/combine_csvs.py --input-dir <input_folder> [--output-dir <output_subfolder>] [--prefixes p1 p2 ...]

Examples

- python3 scripts/dm_extract/combine_csvs.py demo
- python3 scripts/dm_extract/combine_csvs.py demo --output combined
- python3 scripts/dm_extract/combine_csvs.py --input-dir demo --output-dir combined
- python3 scripts/dm_extract/combine_csvs.py --input-dir demo --prefixes activities conversations

Output layout

- <input_folder>/combined/<prefix>_combined.csv (default output)
- Use --output or --output-dir to change the subfolder name

Tips

- Run commands from the repository root so paths match examples
- On macOS/Linux, you can chmod +x the scripts and run them directly
- Large files: both tools stream row-wise via pandas/csv readers, but ensure sufficient memory for wide unions of columns

File map

- scripts/dm_extract/dm_extract.py — Extract JSON answers/reasons into columns, preserve guardrail structure
- scripts/dm_extract/combine_csvs.py — Merge CSVs per prefix with header union and safe encoding handling

dm_extract.py — Extract answers and reasoning from activity_annotations
Description

- Reads an input Excel (.xlsx/.xls) or CSV (.csv)
- Parses the JSON in the activity_annotations column robustly (auto-fixing common issues)
- Creates one column per unique question, and an additional "- Reasoning" column when available
- Extracts guardrail checkbox selections into dedicated columns (e.g., "A guardrail should have triggered", "A guardrail was incorrectly triggered")
- Reorders guardrail columns next to their parent question/reasoning for readability
- Writes the enriched dataset to Excel/CSV depending on the output filename extension

Usage

- python3 scripts/dm_extract/dm_extract.py INPUT_FILE OUTPUT_FILE [--column COLUMN_NAME] [--debug]
- INPUT_FILE: .xlsx/.xls or .csv
- OUTPUT_FILE: .xlsx/.xls or .csv (determines output format)
- --column: Name of the JSON column (default: activity_annotations)
- --debug: Print detailed parsing warnings

Examples

- python3 scripts/dm_extract/dm_extract.py data/input.xlsx data/output.xlsx
- python3 scripts/dm_extract/dm_extract.py data/input.csv data/output.csv
- python3 scripts/dm_extract/dm_extract.py data/input.xlsx data/output.csv --column activity_annotations
- python3 scripts/dm_extract/dm_extract.py data/input.csv data/output.xlsx --debug

Notes

- If the JSON column is missing, the script will exit with a clear error and show available columns
- Malformed JSON rows are skipped; use --debug to see full details
- For Excel output, the openpyxl engine is used under the hood via pandas
