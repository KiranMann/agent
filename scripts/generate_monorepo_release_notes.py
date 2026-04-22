#!/usr/bin/env python3
"""Generate monorepo release notes grouped by app and shared changes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CHANGE_TYPE_TITLES = {
    "feat": "✨ New Features",
    "fix": "🐛 Bug Fixes",
    "refactor": "♻️ Code Refactoring",
    "perf": "⚡ Performance Improvements",
    "chore": "🧹 Chores",
    "docs": "📚 Documentation",
    "style": "💄 Styling",
    "test": "🧪 Testing",
    "ci": "🔧 CI/CD",
    "build": "📦 Build System",
    "other": "🔀 Other Changes",
}
CHANGE_TYPE_ORDER = list(CHANGE_TYPE_TITLES.keys())
DEFAULT_SHARED_SECTION = "Shared"
CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(feat|fix|chore|refactor|perf|style|docs|test|ci|build)(-ai)?[:\s]+(.+?)$",
    re.IGNORECASE,
)
PULL_REQUEST_PATTERNS = [
    re.compile(r"\(#(?P<number>\d+)\)"),
    re.compile(r"Merge pull request #(?P<number>\d+)", re.IGNORECASE),
]
APP_TAG_PATTERN = re.compile(r"^app/(?P<app>[^/]+)/v(?P<version>.+)$")
STABLE_VERSION_TAG_PATTERN = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
GIT_LOG_FIELD_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class CommitRecord:
    """A commit included in a release range."""

    sha: str
    subject: str
    author: str


@dataclass(frozen=True)
class ChangeEntry:
    """A release note entry sourced from a pull request or commit."""

    title: str
    author: str
    category: str
    changed_files: tuple[str, ...]
    reference_label: str
    reference_url: str | None


@dataclass(frozen=True)
class ReleaseApp:
    """Resolved release manifest details for a single app."""

    name: str
    version: str
    tag: str | None
    changed_since_prod: bool | None
    tag_on_target_commit: bool | None


def write_stderr(message: str) -> None:
    """Write a message to stderr."""

    sys.stderr.write(f"{message}\n")


def run_git_command(command: list[str]) -> str:
    """Run a git command and return its stdout."""

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)  # noqa: S603
    except subprocess.CalledProcessError as error:
        command_text = " ".join(command)
        stderr_text = error.stderr.strip()
        raise RuntimeError(f"Git command failed: {command_text}\n{stderr_text}") from error

    return result.stdout.strip()


def parse_change_title(title: str) -> tuple[str, str]:
    """Return changelog category and cleaned title."""

    cleaned_title = title.strip()
    for pattern in PULL_REQUEST_PATTERNS:
        cleaned_title = pattern.sub("", cleaned_title).strip()

    match = CONVENTIONAL_COMMIT_PATTERN.match(cleaned_title)
    if not match:
        return "other", cleaned_title

    return match.group(1).lower(), match.group(3).strip()


def extract_pull_request_number(subject: str) -> str | None:
    """Extract a pull request number from a commit subject if present."""

    for pattern in PULL_REQUEST_PATTERNS:
        match = pattern.search(subject)
        if match:
            return match.group("number")

    return None


def get_commit_records(commit_range: str) -> list[CommitRecord]:
    """Return commits in the release range, oldest first."""

    git_log_output = run_git_command(
        [
            "git",
            "log",
            "--reverse",
            f"--pretty=format:%H{GIT_LOG_FIELD_SEPARATOR}%s{GIT_LOG_FIELD_SEPARATOR}%an",
            commit_range,
        ]
    )
    if not git_log_output:
        return []

    commits: list[CommitRecord] = []
    for raw_record in git_log_output.splitlines():
        if not raw_record.strip():
            continue

        sha, subject, author = raw_record.split(GIT_LOG_FIELD_SEPARATOR, maxsplit=2)
        commits.append(CommitRecord(sha=sha.strip(), subject=subject.strip(), author=author.strip()))

    return commits


def get_commit_changed_files(commit_sha: str) -> tuple[str, ...]:
    """Return files changed by a commit."""

    output = run_git_command(["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit_sha])
    if not output:
        return ()

    return tuple(file_path for file_path in output.splitlines() if file_path)


def get_previous_production_tag(current_tag: str | None) -> str | None:
    """Return the previous production baseline tag.

    Preference order:
    1. Latest monorepo production promotion tag: promote/prod/*
    2. Latest legacy stable repo tag: vX.Y.Z
    """

    tag_output = run_git_command(["git", "tag", "-l", "promote/prod/*", "--sort=-creatordate"])
    if tag_output:
        for tag in tag_output.splitlines():
            if current_tag and tag == current_tag:
                continue
            return tag

    return get_latest_stable_repo_tag(current_tag)


def parse_stable_version_tag(tag: str) -> tuple[int, int, int] | None:
    """Parse a stable SemVer tag, allowing an optional leading v."""

    match = STABLE_VERSION_TAG_PATTERN.fullmatch(tag.strip())
    if not match:
        return None

    return (int(match.group("major")), int(match.group("minor")), int(match.group("patch")))


def get_latest_stable_repo_tag(current_tag: str | None) -> str | None:
    """Return the highest stable SemVer repo tag, with or without a leading v."""

    tag_output = run_git_command(["git", "tag", "-l"])
    if not tag_output:
        return None

    stable_tags: list[tuple[tuple[int, int, int], str]] = []
    for tag in tag_output.splitlines():
        cleaned_tag = tag.strip()
        if current_tag and cleaned_tag == current_tag:
            continue

        parsed_tag = parse_stable_version_tag(cleaned_tag)
        if parsed_tag is not None:
            stable_tags.append((parsed_tag, cleaned_tag))

    if not stable_tags:
        return None

    return max(stable_tags, key=lambda item: item[0])[1]


def get_baseline_commit(previous_production_tag: str | None) -> tuple[str, str]:
    """Return the baseline commit and label for changelog generation."""

    if previous_production_tag:
        baseline_commit = run_git_command(["git", "rev-list", "-n", "1", previous_production_tag])
        return baseline_commit, previous_production_tag

    baseline_commit = run_git_command(["git", "rev-list", "--max-parents=0", "HEAD"])
    return baseline_commit, "initial commit"


def get_release_app_versions(target_commit: str) -> dict[str, str]:
    """Return app versions tagged on the release commit."""

    tags_output = run_git_command(["git", "tag", "--points-at", target_commit])
    if not tags_output:
        return {}

    versions: dict[str, str] = {}
    for tag in tags_output.splitlines():
        match = APP_TAG_PATTERN.match(tag)
        if match:
            versions[match.group("app")] = match.group("version")

    return dict(sorted(versions.items()))


def get_tag_url(repo_slug: str, tag: str) -> str:
    """Return a GitHub URL for a tag reference."""

    encoded_tag = urllib.parse.quote(tag, safe="")
    return f"https://github.com/{repo_slug}/tree/{encoded_tag}"


def get_tag_commit(tag: str) -> str:
    """Return the commit pointed to by a tag."""

    return run_git_command(["git", "rev-list", "-n", "1", tag])


def load_release_manifest(manifest_path: str | None) -> dict[str, dict[str, object]]:
    """Return raw app entries from a release manifest file."""

    if not manifest_path:
        return {}

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    apps = manifest.get("apps", {})
    if not isinstance(apps, dict):
        raise RuntimeError("Release manifest apps payload is invalid")

    return {str(app_name): app_data for app_name, app_data in apps.items() if isinstance(app_data, dict)}


def get_release_apps(target_commit: str, manifest_path: str | None) -> dict[str, ReleaseApp]:
    """Return all apps included in the release, preferring the explicit manifest."""

    manifest_apps = load_release_manifest(manifest_path)
    if manifest_apps:
        release_apps: dict[str, ReleaseApp] = {}
        for app_name, payload in sorted(manifest_apps.items()):
            version = payload.get("version")
            tag = payload.get("tag")
            changed_since_prod = payload.get("changed_since_prod")

            if not isinstance(version, str) or not version:
                raise RuntimeError(f"Release manifest entry for app '{app_name}' is missing a version")

            tag_value = tag if isinstance(tag, str) and tag else None
            tag_on_target_commit: bool | None = None
            if tag_value is not None:
                tag_on_target_commit = get_tag_commit(tag_value) == target_commit

            release_apps[app_name] = ReleaseApp(
                name=app_name,
                version=version,
                tag=tag_value,
                changed_since_prod=changed_since_prod if isinstance(changed_since_prod, bool) else None,
                tag_on_target_commit=tag_on_target_commit,
            )

        return release_apps

    return {
        app_name: ReleaseApp(
            name=app_name,
            version=version,
            tag=f"app/{app_name}/v{version}",
            changed_since_prod=None,
            tag_on_target_commit=True,
        )
        for app_name, version in get_release_app_versions(target_commit).items()
    }


def list_apps_in_repo(repo_root: Path) -> set[str]:
    """Return application names discovered under the apps directory."""

    apps_dir = repo_root / "apps"
    if not apps_dir.exists():
        return set()

    return {entry.name for entry in apps_dir.iterdir() if entry.is_dir() and not entry.name.startswith("__")}


def validate_github_api_url(url: str) -> None:
    """Ensure only GitHub HTTPS API URLs are used for outbound requests."""

    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "api.github.com":
        raise ValueError(f"Unsupported GitHub API URL: {url}")


def build_github_request(url: str, token: str | None) -> urllib.request.Request:
    """Build a GitHub API request."""

    validate_github_api_url(url)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return urllib.request.Request(url, headers=headers)  # noqa: S310


def fetch_json(url: str, token: str | None) -> object:
    """Fetch JSON from the GitHub API."""

    request = build_github_request(url, token)
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed for {url}: {error.code} {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"GitHub API request failed for {url}: {error.reason}") from error


def fetch_pull_request_details(repo_slug: str, pr_number: str, token: str | None) -> tuple[str, str, str]:
    """Return pull request title, author and URL."""

    encoded_repo = urllib.parse.quote(repo_slug, safe="")
    pr_url = f"https://api.github.com/repos/{encoded_repo}/pulls/{pr_number}"
    payload = fetch_json(pr_url, token)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected PR payload for #{pr_number}")

    title = str(payload.get("title", "PR title unavailable"))
    html_url = str(payload.get("html_url", ""))
    user_payload = payload.get("user")
    author = "unknown"
    if isinstance(user_payload, dict) and user_payload.get("login"):
        author = str(user_payload["login"])

    return title, author, html_url


def fetch_pull_request_files(repo_slug: str, pr_number: str, token: str | None) -> tuple[str, ...]:
    """Return files changed by a pull request."""

    encoded_repo = urllib.parse.quote(repo_slug, safe="")
    files: list[str] = []
    page = 1

    while True:
        files_url = f"https://api.github.com/repos/{encoded_repo}/pulls/{pr_number}/files?per_page=100&page={page}"
        payload = fetch_json(files_url, token)
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected files payload for PR #{pr_number}")

        if not payload:
            break

        for item in payload:
            if isinstance(item, dict) and item.get("filename"):
                files.append(str(item["filename"]))

        page += 1

    return tuple(files)


def build_fallback_pull_request_files(commits: list[CommitRecord]) -> tuple[str, ...]:
    """Return a de-duplicated ordered file list from commits."""

    seen: set[str] = set()
    files: list[str] = []
    for commit in commits:
        for file_path in get_commit_changed_files(commit.sha):
            if file_path not in seen:
                seen.add(file_path)
                files.append(file_path)

    return tuple(files)


def build_change_entries(commit_range: str, repo_slug: str, token: str | None) -> list[ChangeEntry]:
    """Return release note entries for the commit range."""

    commits = get_commit_records(commit_range)
    if not commits:
        return []

    pr_commits: dict[str, list[CommitRecord]] = {}
    pr_order: list[str] = []
    standalone_changes: list[ChangeEntry] = []

    for commit in commits:
        pr_number = extract_pull_request_number(commit.subject)
        if pr_number:
            if pr_number not in pr_commits:
                pr_commits[pr_number] = []
                pr_order.append(pr_number)
            pr_commits[pr_number].append(commit)
            continue

        category, clean_title = parse_change_title(commit.subject)
        standalone_changes.append(
            ChangeEntry(
                title=clean_title,
                author=commit.author,
                category=category,
                changed_files=get_commit_changed_files(commit.sha),
                reference_label=commit.sha[:7],
                reference_url=None,
            )
        )

    changes: list[ChangeEntry] = []
    for pr_number in pr_order:
        commits_for_pr = pr_commits[pr_number]
        fallback_commit = commits_for_pr[-1]
        fallback_files = build_fallback_pull_request_files(commits_for_pr)
        should_call_github_api = False

        if should_call_github_api:
            try:
                title, author, pr_url = fetch_pull_request_details(repo_slug, pr_number, token)
            except RuntimeError as error:
                write_stderr(
                    f"Warning: failed to fetch details for PR #{pr_number}; falling back to commit data. {error}"
                )
                title = fallback_commit.subject
                author = fallback_commit.author
                pr_url = f"https://github.com/{repo_slug}/pull/{pr_number}"
        else:
            title = fallback_commit.subject
            author = fallback_commit.author
            pr_url = f"https://github.com/{repo_slug}/pull/{pr_number}"

        if should_call_github_api:
            try:
                changed_files = fetch_pull_request_files(repo_slug, pr_number, token)
            except RuntimeError as error:
                write_stderr(
                    f"Warning: failed to fetch files for PR #{pr_number}; falling back to commit diff. {error}"
                )
                changed_files = fallback_files
        else:
            changed_files = fallback_files

        category, clean_title = parse_change_title(title)
        changes.append(
            ChangeEntry(
                title=clean_title,
                author=normalize_author_name(author),
                category=category,
                changed_files=changed_files,
                reference_label=f"#{pr_number}",
                reference_url=pr_url,
            )
        )

    changes.extend(standalone_changes)
    return changes


def classify_change(change: ChangeEntry, app_names: set[str]) -> tuple[list[str], bool]:
    """Return directly touched apps and whether the change belongs to Shared."""

    direct_apps: set[str] = set()
    has_shared_changes = False

    for file_path in change.changed_files:
        parts = Path(file_path).parts
        if len(parts) >= 2 and parts[0] == "apps" and parts[1] in app_names:
            direct_apps.add(parts[1])
            continue

        has_shared_changes = True

    if not change.changed_files:
        has_shared_changes = True

    return sorted(direct_apps), has_shared_changes


def group_changes(
    changes: list[ChangeEntry], app_names: set[str]
) -> defaultdict[str, defaultdict[str, list[ChangeEntry]]]:
    """Group changes into app sections and a Shared section."""

    grouped: defaultdict[str, defaultdict[str, list[ChangeEntry]]] = defaultdict(lambda: defaultdict(list))

    for change in changes:
        direct_apps, has_shared_changes = classify_change(change, app_names)
        for app_name in direct_apps:
            grouped[app_name][change.category].append(change)
        if has_shared_changes:
            grouped[DEFAULT_SHARED_SECTION][change.category].append(change)

    return grouped


def format_change_entry(change: ChangeEntry) -> str:
    """Render a markdown bullet for a change."""

    reference = change.reference_label
    if change.reference_url:
        reference = f"[{change.reference_label}]({change.reference_url})"
    else:
        reference = f"`{change.reference_label}`"

    return f"- {change.title} ({reference}) by {normalize_author_name(change.author)}"


def normalize_author_name(author: str) -> str:
    """Return a display-safe author name without GitHub mention formatting."""

    cleaned_author = author.strip().lstrip("@")
    return cleaned_author or "unknown"


def render_section(
    title: str,
    categories: dict[str, list[ChangeEntry]],
    app_version: str | None = None,
) -> list[str]:
    """Render a section and its categorized change bullets."""

    heading = f"### {title}"
    if app_version:
        heading = f"### {title} - {app_version}"

    lines = [heading, ""]
    has_content = False

    for category in CHANGE_TYPE_ORDER:
        entries = categories.get(category, [])
        if not entries:
            continue

        has_content = True
        lines.append(f"#### {CHANGE_TYPE_TITLES[category]}")
        lines.append("")
        for entry in entries:
            lines.append(format_change_entry(entry))
        lines.append("")

    if not has_content:
        lines.append("- No changes recorded for this section.")
        lines.append("")

    return lines


def render_app_table(release_apps: dict[str, ReleaseApp], repo_slug: str) -> list[str]:
    """Render the full app manifest table for release notes."""

    lines = [
        "| App | Version | Status | Delivery | Release Tag |",
        "| --- | --- | --- | --- | --- |",
    ]

    for app_name, app in sorted(release_apps.items()):
        if app.changed_since_prod is True:
            status = "Changed since prod"
        elif app.changed_since_prod is False:
            status = "Unchanged since prod"
        else:
            status = "Status unavailable"

        if app.tag is None:
            delivery = "Tag unresolved"
            tag_reference = "n/a"
        else:
            delivery = "Release tag resolved on train commit"
            if app.tag_on_target_commit is False:
                delivery = "Existing immutable tag reused"
            tag_reference = f"[{app.tag}]({get_tag_url(repo_slug, app.tag)})"

        lines.append(f"| {app_name} | {app.version} | {status} | {delivery} | {tag_reference} |")

    return lines


def generate_release_notes(
    release_type: str,
    tag: str,
    source_tag: str | None,
    target_commit: str,
    baseline_label: str,
    repo_slug: str,
    release_apps: dict[str, ReleaseApp],
    grouped_changes: defaultdict[str, defaultdict[str, list[ChangeEntry]]],
) -> str:
    """Generate the final markdown release notes."""

    lines: list[str] = []
    build_date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    if release_type == "prerelease":
        lines.extend(
            [
                f"This is a pre-release created when release train `{tag}` was cut.",
                "",
            ]
        )
    else:
        train_reference = source_tag or tag
        lines.extend(
            [
                f"This release was promoted to production from release train `{train_reference}`.",
                "",
            ]
        )

    lines.append("## Included App Versions")
    lines.append("")
    if release_apps:
        lines.extend(render_app_table(release_apps, repo_slug))
    else:
        lines.append("- No apps were resolved in the release manifest.")
    lines.append("")

    lines.append(f"## Changes since last production release ({baseline_label})")
    lines.append("")

    section_names = sorted(section for section in grouped_changes if section != DEFAULT_SHARED_SECTION)
    for app_name in section_names:
        release_app = release_apps.get(app_name)
        lines.extend(
            render_section(
                app_name,
                grouped_changes[app_name],
                release_app.version if release_app is not None else None,
            )
        )

    if DEFAULT_SHARED_SECTION in grouped_changes:
        lines.extend(render_section(DEFAULT_SHARED_SECTION, grouped_changes[DEFAULT_SHARED_SECTION]))

    if not grouped_changes:
        lines.append("- No pull requests or commits were found in this release range.")
        lines.append("")

    lines.append("## Release Details")
    lines.append("")
    if release_type == "prerelease":
        lines.append(f"- **Train tag:** `{tag}`")
    else:
        lines.append(f"- **Promoted from:** `{source_tag or tag}`")
        lines.append(f"- **Production promotion tag:** `{tag}`")
    lines.append(f"- **Build date:** {build_date}")
    lines.append(f"- **Commit:** `{target_commit}`")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(description="Generate monorepo release notes.")
    parser.add_argument("--release-type", choices=["prerelease", "production"], required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-tag")
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--manifest-path")
    return parser.parse_args()


def main() -> None:
    """Generate release notes and write markdown to stdout."""

    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    repo_slug = os.environ.get("GITHUB_REPOSITORY", "CBA-General/FinancialCompanion")
    github_token = os.environ.get("GITHUB_TOKEN")

    current_tag = args.tag if args.release_type == "production" else None
    previous_production_tag = get_previous_production_tag(current_tag)
    baseline_commit, baseline_label = get_baseline_commit(previous_production_tag)
    commit_range = f"{baseline_commit}..{args.target_commit}"

    write_stderr(f"Generating monorepo release notes for range: {commit_range}")

    release_apps = get_release_apps(args.target_commit, args.manifest_path)
    app_names = list_apps_in_repo(repo_root)
    grouped_changes = group_changes(build_change_entries(commit_range, repo_slug, github_token), app_names)

    release_notes = generate_release_notes(
        release_type=args.release_type,
        tag=args.tag,
        source_tag=args.source_tag,
        target_commit=args.target_commit,
        baseline_label=baseline_label,
        repo_slug=repo_slug,
        release_apps=release_apps,
        grouped_changes=grouped_changes,
    )
    sys.stdout.write(release_notes)


if __name__ == "__main__":
    main()
