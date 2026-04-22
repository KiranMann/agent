#!/usr/bin/env python3
"""Generate a categorized changelog from git log.

This script parses commit messages and categorizes them by type.
"""

import re
import subprocess
import sys
from datetime import datetime

# Constants
MIN_ARGS_REQUIRED = 2
VERSION_ARG_INDEX = 2


def run_git_command(cmd: list[str]) -> str:
    """Run a git command and return the output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running git command: {' '.join(cmd)}", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        print(f"Return code: {e.returncode}", file=sys.stderr)
        if e.stderr:
            print(f"Stderr: {e.stderr}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"Unexpected error running git command: {e}", file=sys.stderr)
        return ""


def parse_commit_type(commit_message: str) -> tuple[str, str, str]:
    """Parse commit message to extract type, description, and PR number."""
    # Extract PR number from commit message
    pr_pattern = r"\(#(\d+)\)"
    pr_match = re.search(pr_pattern, commit_message)
    pr_number = pr_match.group(1) if pr_match else ""

    # Remove PR number from message for cleaner description
    clean_message = re.sub(pr_pattern, "", commit_message).strip()

    # Handle conventional commit format with optional -ai suffix
    pattern = r"^(feat|fix|chore|refactor|perf|style|docs|test|ci|build)(-ai)?[:\s]+(.+?)$"
    match = re.match(pattern, clean_message, re.IGNORECASE)

    if match:
        commit_type = match.group(1).lower()
        description = match.group(3).strip()
        return commit_type, description, pr_number

    # Fallback for other formats
    return "other", clean_message, pr_number


def categorize_commits(commit_range: str) -> dict[str, list[tuple[str, str]]]:
    """Get commits from git log and categorize them."""
    print(f"Generating changelog for commit range: {commit_range}", file=sys.stderr)

    git_cmd = ["git", "log", "--oneline", "--pretty=format:%s", commit_range]

    output = run_git_command(git_cmd)
    if not output:
        print(f"No commits found for range: {commit_range}", file=sys.stderr)
        return {}

    categories: dict[str, list[tuple[str, str]]] = {
        "feat": [],
        "fix": [],
        "refactor": [],
        "perf": [],
        "chore": [],
        "docs": [],
        "style": [],
        "test": [],
        "ci": [],
        "build": [],
        "other": [],
    }

    for line in output.split("\n"):
        if line.strip():
            commit_type, description, pr_number = parse_commit_type(line.strip())
            categories[commit_type].append((description, pr_number))

    return categories


def generate_changelog(categories: dict[str, list[tuple[str, str]]], version: str | None = None) -> str:
    """Generate formatted changelog from categorized commits."""
    changelog_sections = {
        "feat": ("✨ New Features", "feat"),
        "fix": ("🐛 Bug Fixes", "fix"),
        "refactor": ("♻️ Code Refactoring", "refactor"),
        "perf": ("⚡ Performance Improvements", "perf"),
        "chore": ("🧹 Chores", "chore"),
        "docs": ("📚 Documentation", "docs"),
        "style": ("💄 Styling", "style"),
        "test": ("🧪 Testing", "test"),
        "ci": ("🔧 CI/CD", "ci"),
        "build": ("📦 Build System", "build"),
        "other": ("🔀 Other Changes", "other"),
    }

    changelog = []

    if version:
        date_str = datetime.now().strftime("%Y-%m-%d")
        changelog.append(f"## {version} ({date_str})")
        changelog.append("")

    for category, (title, _) in changelog_sections.items():
        if categories.get(category):
            changelog.append(f"### {title}")
            changelog.append("")
            for description, pr_number in categories[category]:
                if pr_number:
                    # Create link to GitHub PR
                    pr_link = f"([#{pr_number}](https://github.com/CBA-General/FinancialCompanion/pull/{pr_number}))"
                    changelog.append(f"- {description} {pr_link}")
                else:
                    changelog.append(f"- {description}")
            changelog.append("")

    return "\n".join(changelog)


def main() -> None:
    """Main function."""
    if len(sys.argv) < MIN_ARGS_REQUIRED:
        print("Usage: python generate_changelog.py <commit_range> [version]")
        print("Example: python generate_changelog.py v0.1.2..HEAD v0.1.3")
        sys.exit(1)

    commit_range = sys.argv[1]
    version = sys.argv[VERSION_ARG_INDEX] if len(sys.argv) > VERSION_ARG_INDEX else None

    print(f"Starting changelog generation for range: {commit_range}", file=sys.stderr)

    try:
        categories = categorize_commits(commit_range)
        if not any(categories.values()):
            print("Warning: No categorized commits found", file=sys.stderr)

        changelog = generate_changelog(categories, version)
        print(changelog)
    except Exception as e:
        print(f"Error generating changelog: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
