#!/usr/bin/env python3
"""Financial Companion Code Formatting and Checking Script.

This script executes isort, ruff, and mypy in their respective fix/repair modes
with proper error handling, logging, and configuration detection.

Usage:
    python3 format_and_check.py [options] [paths...]

Examples:
    # Format and check all code
    python3 format_and_check.py

    # Run only specific tools
    python3 format_and_check.py --isort-only
    python3 format_and_check.py --ruff-only --mypy-only

    # Dry run mode
    python3 format_and_check.py --dry-run

    # Verbose output
    python3 format_and_check.py --verbose

    # Check specific files/directories
    python3 format_and_check.py financial_companion_agent/ common/
"""

import argparse
import fnmatch
import hashlib
import logging
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.logging.core import logger

try:
    import tomllib
except ImportError:
    # Python < 3.11 fallback
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        logger.info("Error: tomllib/tomli not available. Please install tomli for Python < 3.11")
        sys.exit(2)


# Color codes for console output
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    @classmethod
    def disable(cls) -> None:
        """Disable colors for non-terminal output."""
        for attr in dir(cls):
            if not attr.startswith("_") and attr != "disable":
                setattr(cls, attr, "")


@dataclass
class ToolResult:
    """Result of running a formatting/checking tool."""

    name: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    files_processed: int = 0
    fixes_applied: int = 0
    errors_found: int = 0


@dataclass
class ExecutionSummary:
    """Summary of all tool executions."""

    results: list[ToolResult] = field(default_factory=list)
    total_duration: float = 0.0
    overall_success: bool = True

    def add_result(self, result: ToolResult) -> None:
        """Add a tool result to the summary."""
        self.results.append(result)
        self.total_duration += result.duration
        if not result.success:
            self.overall_success = False


class ProjectDiscovery:
    """Handles project root discovery and environment detection."""

    def __init__(self, start_path: Path | None = None):
        """Initialize discovery with a start path, project root, and virtualenv resolution."""
        self.start_path = start_path or Path.cwd()
        self.project_root = self._find_project_root()
        self.venv_path = self._find_venv()

    def _find_project_root(self) -> Path:
        """Find the project root by looking for configuration files."""
        current = self.start_path.resolve()

        # Look for project indicators
        indicators = [
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            ".git",
            "requirements.txt",
            "Pipfile",
            "poetry.lock",
            "uv.lock",
        ]

        while current != current.parent:
            for indicator in indicators:
                if (current / indicator).exists():
                    return current
            current = current.parent

        # Fallback to current directory
        return self.start_path.resolve()

    def _find_venv(self) -> Path | None:
        """Find virtual environment directory."""
        venv_names = [".venv", "venv", "env"]

        # Check in project root
        for name in venv_names:
            venv_path = self.project_root / name
            if venv_path.exists() and venv_path.is_dir():
                return venv_path

        # Check if we're already in a virtual environment
        if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
            return Path(sys.prefix)

        return None


class ConfigurationLoader:
    """Loads and parses tool configurations from pyproject.toml."""

    def __init__(self, project_root: Path):
        """Initialize with project root and load pyproject.toml configuration."""
        self.project_root = project_root
        self.pyproject_path = project_root / "pyproject.toml"
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from pyproject.toml."""
        if not self.pyproject_path.exists():
            return {}

        try:
            with open(self.pyproject_path, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            logging.warning(f"Failed to load pyproject.toml: {e}")
            return {}

    def get_tool_config(self, tool_name: str) -> dict[str, Any]:
        """Get configuration for a specific tool."""
        return self.config.get("tool", {}).get(tool_name, {})  # type: ignore[no-any-return]

    def has_tool_config(self, tool_name: str) -> bool:
        """Check if tool has configuration."""
        return tool_name in self.config.get("tool", {})


class FileFilter:
    """Filters files based on tool configurations from pyproject.toml."""

    def __init__(
        self,
        config_loader: ConfigurationLoader,
        directory_mode: bool = False,
        target_directory: str | None = None,
        file_mode: bool = False,
        target_file: str | None = None,
    ):
        """Initialize filtering with config loader and optional directory/file targeting."""
        self.config_loader = config_loader
        self.project_root = config_loader.project_root
        self.directory_mode = directory_mode
        self.target_directory = Path(target_directory) if target_directory else None
        self.file_mode = file_mode
        self.target_file = Path(target_file) if target_file else None

    def get_filtered_files(self, tool_name: str, paths: list[str]) -> list[Path]:
        """Get list of files that should be processed by the specified tool."""
        if self.file_mode and self.target_file:
            return self._get_single_file()
        elif self.directory_mode and self.target_directory:
            return self._get_files_from_directory()
        elif tool_name in {"ruff", "ruff-format"}:
            return self._filter_ruff_files(paths)
        elif tool_name == "isort":
            return self._filter_isort_files(paths)
        elif tool_name == "mypy":
            return self._filter_mypy_files(paths)
        elif tool_name == "black":
            return self._filter_black_files(paths)
        else:
            return self._get_python_files(paths)

    def _filter_ruff_files(self, paths: list[str]) -> list[Path]:
        """Filter files for ruff based on its configuration."""
        ruff_config = self.config_loader.get_tool_config("ruff")

        # Get src paths (defaults to current directory if not specified)
        src_paths = ruff_config.get("src", ["."])
        if isinstance(src_paths, str):
            src_paths = [src_paths]

        # Get exclusions
        excludes = ruff_config.get("exclude", [])

        # If user specified paths, check if they're within src_paths
        if paths:
            search_paths = []
            for user_path in paths:
                user_path_obj = Path(user_path)
                # Check if user path is within any of the src_paths
                for src_path in src_paths:
                    src_path_obj = Path(src_path)
                    try:
                        user_path_obj.resolve().relative_to(src_path_obj.resolve())
                        search_paths.append(user_path)
                        break
                    except ValueError:
                        continue
            if not search_paths:
                # User paths are outside src_paths, use src_paths instead
                search_paths = src_paths
        else:
            search_paths = src_paths

        python_files = []
        for path_str in search_paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                if not self._is_excluded(path, excludes):
                    python_files.append(path)
            elif path.is_dir():
                included_py_files = [
                    py_file for py_file in path.rglob("*.py") if not self._is_excluded(py_file, excludes)
                ]
                python_files += included_py_files

        return python_files

    def _filter_isort_files(self, paths: list[str]) -> list[Path]:
        """Filter files for isort based on its configuration."""
        isort_config = self.config_loader.get_tool_config("isort")

        # Get src_paths (isort specific configuration)
        src_paths = isort_config.get("src_paths", ["."])
        if isinstance(src_paths, str):
            src_paths = [src_paths]

        # If user specified paths, check if they're within src_paths
        if paths:
            search_paths = []
            for user_path in paths:
                user_path_obj = Path(user_path)
                # Check if user path is within any of the src_paths
                for src_path in src_paths:
                    src_path_obj = Path(src_path)
                    try:
                        user_path_obj.resolve().relative_to(src_path_obj.resolve())
                        search_paths.append(user_path)
                        break
                    except ValueError:
                        continue
            if not search_paths:
                # User paths are outside src_paths, use src_paths instead
                search_paths = src_paths
        else:
            search_paths = src_paths

        python_files = []
        for path_str in search_paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                python_files.append(path)
            elif path.is_dir():
                python_files += list(path.rglob("*.py"))

        return python_files

    def _filter_mypy_files(self, paths: list[str]) -> list[Path]:
        """Filter files for mypy based on its configuration."""
        mypy_config = self.config_loader.get_tool_config("mypy")

        # Get exclusions (regex patterns)
        excludes = mypy_config.get("exclude", [])

        # MyPy configuration shows it only checks investinghub_agent
        # Based on the overrides, we should focus on that module
        allowed_modules = ["financial_companion_agent/task_agents/investinghub_agent"]

        # If user specified paths, filter them; otherwise use allowed modules
        if paths:
            search_paths = []
            for user_path in paths:
                user_path_obj = Path(user_path)
                # Check if user path is within allowed modules
                for module_path in allowed_modules:
                    module_path_obj = Path(module_path)
                    try:
                        if user_path_obj.is_file():
                            user_path_obj.resolve().relative_to(module_path_obj.resolve())
                        else:
                            # For directories, check if they overlap
                            user_path_obj.resolve().relative_to(module_path_obj.resolve())
                        search_paths.append(user_path)
                        break
                    except ValueError:
                        continue
            if not search_paths:
                search_paths = allowed_modules
        else:
            search_paths = allowed_modules

        python_files = []
        for path_str in search_paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                if not self._is_excluded_regex(path, excludes):
                    python_files.append(path)
            elif path.is_dir():
                python_files += [
                    py_file for py_file in path.rglob("*.py") if not self._is_excluded_regex(py_file, excludes)
                ]

        return python_files

    def _filter_black_files(self, paths: list[str]) -> list[Path]:
        """Filter files for black based on its configuration."""
        black_config = self.config_loader.get_tool_config("black")

        # Get include pattern (defaults to Python files)
        include_pattern = black_config.get("include", r"\.pyi?$")

        # Get extend-exclude patterns
        extend_exclude = black_config.get("extend-exclude", "")

        # Black doesn't have src paths like ruff, so we use investinghub_agent as default scope
        # to be consistent with other tools
        default_scope = ["financial_companion_agent/task_agents/investinghub_agent"]

        # Validate user paths against scope
        search_paths = self._validate_user_paths_against_scope(paths, default_scope)

        python_files = []
        for path_str in search_paths:
            path = Path(path_str)
            if path.is_file() and self._matches_include_pattern(path, include_pattern):
                if not self._is_excluded_by_black(path, extend_exclude):
                    python_files.append(path)
            elif path.is_dir():
                included_py_files = [
                    py_file
                    for py_file in path.rglob("*.py")
                    if self._matches_include_pattern(py_file, include_pattern)
                    and not self._is_excluded_by_black(py_file, extend_exclude)
                ]
                python_files += included_py_files

        return python_files

    def _get_files_from_directory(self) -> list[Path]:
        """Get all Python files from the target directory, bypassing pyproject.toml filtering."""
        if not self.target_directory:
            return []

        if not self.target_directory.exists():
            return []

        python_files = []

        # Basic exclusions for directory mode (common build/cache directories)
        basic_excludes = {
            ".git",
            ".venv",
            "venv",
            "env",
            "__pycache__",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "build",
            "dist",
            ".eggs",
            ".tox",
            "node_modules",
        }

        if self.target_directory.is_file() and self.target_directory.suffix == ".py":
            # Single file specified
            python_files.append(self.target_directory)
        elif self.target_directory.is_dir():
            # Directory specified - find all .py files recursively
            for py_file in self.target_directory.rglob("*.py"):
                # Check if any parent directory is in basic excludes
                if any(parent.name in basic_excludes for parent in py_file.parents):
                    continue
                if py_file.parent.name in basic_excludes:
                    continue
                python_files.append(py_file)

        return python_files

    def _get_single_file(self) -> list[Path]:
        """Get the single target file, bypassing pyproject.toml filtering."""
        if not self.target_file:
            return []

        if not self.target_file.exists():
            return []

        # Validate it's a Python file
        if self.target_file.suffix != ".py":
            return []

        return [self.target_file]

    def _validate_user_paths_against_scope(self, paths: list[str], scope_paths: list[str]) -> list[str]:
        """Validate user-specified paths against allowed scope paths."""
        if not paths or paths == ["."]:
            return scope_paths

        search_paths = []
        for user_path in paths:
            user_path_obj = Path(user_path)
            # Check if user path is within any of the scope paths
            for scope_path in scope_paths:
                scope_path_obj = Path(scope_path)
                try:
                    user_path_obj.resolve().relative_to(scope_path_obj.resolve())
                    search_paths.append(user_path)
                    break
                except ValueError:
                    continue

        # If no user paths are within scope, fall back to scope paths
        return search_paths if search_paths else scope_paths

    def _matches_include_pattern(self, file_path: Path, pattern: str) -> bool:
        """Check if a file matches the include pattern."""
        try:
            return bool(re.search(pattern, str(file_path)))
        except re.error:
            # If regex is invalid, treat as literal string match
            return pattern in str(file_path)

    def _is_excluded_by_black(self, file_path: Path, extend_exclude: str) -> bool:
        """Check if a file is excluded by black's extend-exclude pattern."""
        if not extend_exclude:
            return False

        # Black's extend-exclude is a multi-line regex pattern
        try:
            # Remove the triple quotes and clean up the pattern
            pattern = extend_exclude.strip().strip("'''").strip('"""')  # noqa: B005
            # Convert to single line pattern
            pattern = re.sub(r"\s*\|\s*", "|", pattern.replace("\n", ""))
            pattern = pattern.strip("/()")

            file_str = str(file_path)
            return bool(re.search(pattern, file_str))
        except re.error:
            # If regex processing fails, fall back to simple string matching
            return any(exclude in str(file_path) for exclude in [".git", ".venv", "build", "dist"])

    @staticmethod
    def _get_python_files(paths: list[str]) -> list[Path]:
        """Get all Python files from the given paths."""
        python_files = []
        search_paths = paths if paths else ["."]

        for path_str in search_paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                python_files.append(path)
            elif path.is_dir():
                python_files += list(path.rglob("*.py"))

        return python_files

    @staticmethod
    def _is_excluded(file_path: Path, excludes: list[str]) -> bool:
        """Check if a file is excluded based on glob patterns."""
        file_str = str(file_path)
        for exclude_pattern in excludes:
            if (
                fnmatch.fnmatch(file_str, exclude_pattern)
                or fnmatch.fnmatch(file_str, f"*/{exclude_pattern}")
                or fnmatch.fnmatch(file_str, f"*/{exclude_pattern}/*")
            ):
                return True
            # Also check if any parent directory matches
            for parent in file_path.parents:
                if fnmatch.fnmatch(str(parent), exclude_pattern) or fnmatch.fnmatch(parent.name, exclude_pattern):
                    return True
        return False

    @staticmethod
    def _is_excluded_regex(file_path: Path, excludes: list[str]) -> bool:
        """Check if a file is excluded based on regex patterns."""
        file_str = str(file_path)
        for exclude_pattern in excludes:
            try:
                if re.match(exclude_pattern, file_str):
                    return True
            except re.error:
                # If regex is invalid, treat as literal string
                if exclude_pattern in file_str:
                    return True
        return False


class ToolExecutor:
    """Executes formatting and checking tools with proper error handling."""

    def __init__(
        self,
        project_discovery: ProjectDiscovery,
        config_loader: ConfigurationLoader,
        dry_run: bool = False,
        verbose: bool = False,
        directory_mode: bool = False,
        target_directory: str | None = None,
        file_mode: bool = False,
        target_file: str | None = None,
    ):
        """Initialize tool execution with project context, config, and targeting options.

        Args:
            project_discovery: Resolved project root and virtualenv info.
            config_loader: Parsed tool configuration from pyproject.toml.
            dry_run: When True, do not modify files.
            verbose: When True, emit detailed command output.
            directory_mode: When True, target a specific directory.
            target_directory: Directory path for directory mode.
            file_mode: When True, target a single file.
            target_file: File path for file mode.
        """
        self.project_discovery = project_discovery
        self.config_loader = config_loader
        self.file_filter = FileFilter(config_loader, directory_mode, target_directory, file_mode, target_file)
        self.dry_run = dry_run
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)

    def _run_command(self, cmd: list[str], tool_name: str, cwd: Path | None = None) -> ToolResult:
        """Run a command and return the result."""
        start_time = time.time()

        if self.dry_run:
            self._print_info(f"[DRY RUN] Executing: {' '.join(cmd)}")
        elif self.verbose:
            self._print_info(f"Executing: {' '.join(cmd)}")

        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                cwd=cwd or self.project_discovery.project_root,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                check=False,
            )

            duration = time.time() - start_time

            return ToolResult(
                name=tool_name,
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration=duration,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self._print_error(f"{tool_name} timed out after 5 minutes")
            return ToolResult(
                name=tool_name,
                success=False,
                exit_code=124,  # Timeout exit code
                stdout="",
                stderr="Command timed out",
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start_time
            self._print_error(f"Failed to execute {tool_name}: {e}")
            return ToolResult(
                name=tool_name,
                success=False,
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration=duration,
            )

    def _get_base_command(self) -> list[str]:
        """Get base command prefix (python -m)."""
        # Check if we're in a virtual environment and use its Python
        if self.project_discovery.venv_path:
            venv_python = self.project_discovery.venv_path / "bin" / "python"
            if venv_python.exists():
                self._print_info(f"Using virtual environment Python: {venv_python}")
                return [str(venv_python), "-m"]

        # Try python3 first, then python
        if shutil.which("python3"):
            self._print_info("Using system python3")
            return ["python3", "-m"]
        elif shutil.which("python"):
            self._print_info("Using system python")
            return ["python", "-m"]
        else:
            self._print_error("No Python executable found!")
            return ["python", "-m"]  # Fallback that will likely fail

    def run_isort(self, paths: list[str]) -> ToolResult:
        """Run isort for import sorting. In dry-run mode, shows what would be sorted. In fix mode, applies sorting."""
        mode = "sorting imports" if not self.dry_run else "checking import order"
        self._print_step(f"Running isort ({mode})")

        # Get filtered files based on configuration
        filtered_files = self.file_filter.get_filtered_files("isort", paths)

        if not filtered_files:
            self._print_info("No files to process with isort")
            return ToolResult(
                name="isort",
                success=True,
                exit_code=0,
                stdout="No files to process",
                stderr="",
                duration=0.0,
            )

        cmd = [*self._get_base_command(), "isort"]

        # Add flags based on mode
        if self.dry_run:
            # Dry-run: check what would be sorted
            cmd.extend(["--check-only", "--diff"])
        else:
            # Fix mode: actually sort imports
            cmd.append("--overwrite-in-place")

        # Add configuration from pyproject.toml if available
        if self.config_loader.has_tool_config("isort"):
            cmd.extend(["--settings-path", str(self.config_loader.pyproject_path)])

        # Add filtered files
        cmd.extend([str(f) for f in filtered_files])

        result = self._run_command(cmd, "isort")

        if result.success:
            self._print_success("✓ isort completed successfully")
        else:
            self._print_error(f"✗ isort failed (exit code: {result.exit_code})")
            # Always show error details, not just in verbose mode
            self._print_tool_error_details(result, "isort")

        return result

    def run_ruff(self, paths: list[str]) -> ToolResult:
        """Run ruff for formatting and linting. In dry-run mode, shows issues found. In fix mode, applies fixes including unsafe ones."""
        mode = "applying fixes" if not self.dry_run else "checking for issues"
        self._print_step(f"Running ruff ({mode})")

        # Get filtered files based on configuration
        filtered_files = self.file_filter.get_filtered_files("ruff", paths)

        if not filtered_files:
            self._print_info("No files to process with ruff")
            return ToolResult(
                name="ruff",
                success=True,
                exit_code=0,
                stdout="No files to process",
                stderr="",
                duration=0.0,
            )

        cmd = [*self._get_base_command(), "ruff", "check"]

        # Add flags based on mode
        if self.dry_run:
            # Dry-run: just check (no --fix flag)
            pass
        else:
            # Fix mode: apply fixes (including unsafe ones)
            cmd.extend(["--fix", "--unsafe-fixes"])

        # Add configuration from pyproject.toml if available
        if self.config_loader.has_tool_config("ruff"):
            cmd.extend(["--config", str(self.config_loader.pyproject_path)])

        # Add filtered files
        cmd.extend([str(f) for f in filtered_files])

        result = self._run_command(cmd, "ruff")

        if result.success:
            self._print_success("✓ ruff completed successfully")
        else:
            self._print_error(f"✗ ruff failed (exit code: {result.exit_code})")
            # Always show error details, not just in verbose mode
            self._print_tool_error_details(result, "ruff")

        return result

    def run_ruff_format(self, paths: list[str]) -> ToolResult:
        """Run ruff format for code formatting. In dry-run mode, shows what would be formatted. In fix mode, applies formatting."""
        mode = "applying formatting" if not self.dry_run else "checking formatting"
        self._print_step(f"Running ruff format ({mode})")

        # Get filtered files based on configuration
        filtered_files = self.file_filter.get_filtered_files("ruff", paths)

        if not filtered_files:
            self._print_info("No files to process with ruff format")
            return ToolResult(
                name="ruff-format",
                success=True,
                exit_code=0,
                stdout="No files to process",
                stderr="",
                duration=0.0,
            )

        cmd = [*self._get_base_command(), "ruff", "format"]

        # Add flags based on mode
        if self.dry_run:
            # Dry-run: don't modify files, just show what would change
            cmd.append("--check")

        # Add configuration from pyproject.toml if available
        if self.config_loader.has_tool_config("ruff"):
            cmd.extend(["--config", str(self.config_loader.pyproject_path)])

        # Add filtered files
        cmd.extend([str(f) for f in filtered_files])

        result = self._run_command(cmd, "ruff-format")

        if result.success:
            self._print_success("✓ ruff format completed successfully")
        else:
            self._print_error(f"✗ ruff format found formatting issues (exit code: {result.exit_code})")
            # Always show formatting details, not just in verbose mode
            self._print_tool_error_details(result, "ruff-format")

        return result

    def run_mypy(self, paths: list[str]) -> ToolResult:
        """Run mypy for type checking (always read-only)."""
        self._print_step("Running mypy (type checking)")

        # Get filtered files based on configuration
        filtered_files = self.file_filter.get_filtered_files("mypy", paths)

        if not filtered_files:
            self._print_info("No files to process with mypy")
            return ToolResult(
                name="mypy",
                success=True,
                exit_code=0,
                stdout="No files to process",
                stderr="",
                duration=0.0,
            )

        cmd = [*self._get_base_command(), "mypy"]

        # Add configuration from pyproject.toml if available
        if self.config_loader.has_tool_config("mypy"):
            cmd.extend(["--config-file", str(self.config_loader.pyproject_path)])

        # Add filtered files
        cmd.extend([str(f) for f in filtered_files])

        result = self._run_command(cmd, "mypy")

        if result.success:
            self._print_success("✓ mypy completed successfully")
        else:
            self._print_error(f"✗ mypy found type issues (exit code: {result.exit_code})")
            # Always show type error details, not just in verbose mode
            self._print_tool_error_details(result, "mypy")

        return result

    def run_black(self, paths: list[str]) -> ToolResult:
        """Run black for code formatting. In dry-run mode, shows formatting diff. In fix mode, applies formatting."""
        mode = "applying formatting" if not self.dry_run else "checking formatting"
        self._print_step(f"Running black ({mode})")

        # Get filtered files based on configuration
        filtered_files = self.file_filter.get_filtered_files("black", paths)

        if not filtered_files:
            self._print_info("No files to process with black")
            return ToolResult(
                name="black",
                success=True,
                exit_code=0,
                stdout="No files to process",
                stderr="",
                duration=0.0,
            )

        cmd = [*self._get_base_command(), "black"]

        # Add flags based on mode
        if self.dry_run:
            # Dry-run: don't modify files, just show what would change
            cmd.extend(["--check", "--diff"])
        else:
            # Fix mode: black modifies files by default (no additional flags needed)
            pass

        # Add configuration from pyproject.toml if available
        if self.config_loader.has_tool_config("black"):
            cmd.extend(["--config", str(self.config_loader.pyproject_path)])

        # Add filtered files
        cmd.extend([str(f) for f in filtered_files])

        result = self._run_command(cmd, "black")

        if result.success:
            self._print_success("✓ black completed successfully")
        else:
            self._print_error(f"✗ black found formatting issues (exit code: {result.exit_code})")
            # Always show formatting details, not just in verbose mode
            self._print_tool_error_details(result, "black")

        return result

    @staticmethod
    def get_last_lines(text: str, n: int = 10) -> str:
        """Get the last N lines from text output, preserving formatting but removing trailing empty lines."""
        if not text or not text.strip():
            return ""

        # Split into lines and remove trailing whitespace from each line
        lines = [line.rstrip() for line in text.strip().split("\n")]

        # Remove trailing empty lines only
        while lines and not lines[-1]:
            lines.pop()

        if not lines:
            return ""

        # Get the last N lines, preserving empty lines within the content
        last_lines = lines[-n:] if len(lines) > n else lines
        return "\n".join(f"    {line}" for line in last_lines)

    def _print_tool_error_details(self, result: ToolResult, tool_name: str) -> None:
        """Print detailed error information for a failed tool run."""
        if tool_name == "mypy":
            # MyPy outputs type errors to stdout, not stderr
            if result.stdout:
                output_lines = self.get_last_lines(result.stdout, 10)
                if output_lines:
                    logger.info(f"{Colors.RED}  Last 10 lines of type errors:{Colors.RESET}")
                    logger.info(output_lines)
            elif result.stderr:
                # Show stderr if stdout is empty (configuration errors, etc.)
                error_lines = self.get_last_lines(result.stderr, 10)
                if error_lines:
                    logger.info(f"{Colors.RED}  Last 10 lines of error output:{Colors.RESET}")
                    logger.info(error_lines)
        elif tool_name in ["black", "ruff-format"]:
            # Black and ruff format output formatting diffs to stdout, not stderr
            if result.stdout:
                output_lines = self.get_last_lines(result.stdout, 10)
                if output_lines:
                    logger.info(f"{Colors.RED}  Last 10 lines of formatting diff:{Colors.RESET}")
                    logger.info(output_lines)
            elif result.stderr:
                # Show stderr if stdout is empty (configuration errors, etc.)
                error_lines = self.get_last_lines(result.stderr, 10)
                if error_lines:
                    logger.info(f"{Colors.RED}  Last 10 lines of error output:{Colors.RESET}")
                    logger.info(error_lines)
        # Ruff and isort typically use stderr
        elif result.stderr:
            error_lines = self.get_last_lines(result.stderr, 10)
            if error_lines:
                logger.info(f"{Colors.RED}  Last 10 lines of error output:{Colors.RESET}")
                logger.info(error_lines)
        elif result.stdout:
            # Some tools might output errors to stdout
            output_lines = self.get_last_lines(result.stdout, 10)
            if output_lines:
                logger.info(f"{Colors.RED}  Last 10 lines of output:{Colors.RESET}")
                logger.info(output_lines)

    @staticmethod
    def _print_step(message: str) -> None:
        """Print a step message with formatting."""
        logger.info(f"{Colors.BLUE}==> {message}{Colors.RESET}")

    @staticmethod
    def _print_success(message: str) -> None:
        """Print a success message with formatting."""
        logger.info(f"{Colors.GREEN}{message}{Colors.RESET}")

    @staticmethod
    def _print_error(message: str) -> None:
        """Print an error message with formatting."""
        logger.info(f"{Colors.RED}{message}{Colors.RESET}")

    @staticmethod
    def _print_info(message: str) -> None:
        """Print an info message with formatting."""
        logger.info(f"{Colors.CYAN}{message}{Colors.RESET}")


class FormatAndCheckRunner:
    """Main runner class that orchestrates the formatting and checking process."""

    def __init__(self, args: argparse.Namespace):
        """Initialize runner state from parsed CLI arguments.

        Args:
            args: Parsed command-line arguments controlling tools and modes.
        """
        self.args = args
        self.setup_logging()
        self.setup_colors()

        # Determine if we're in dry-run mode (default unless --fix is specified)
        is_dry_run = not args.fix

        # Check if directory mode is enabled
        directory_mode = bool(args.dir)
        target_directory = args.dir if directory_mode else None

        # Check if file mode is enabled
        file_mode = bool(args.file)
        target_file = args.file if file_mode else None

        # Validate directory exists if specified
        if directory_mode and target_directory:
            dir_path = Path(target_directory)
            if not dir_path.exists():
                logger.info(f"{Colors.RED}Error: Directory '{target_directory}' does not exist{Colors.RESET}")
                raise SystemExit(1)

        # Validate file exists and is Python file if specified
        if file_mode and target_file:
            file_path = Path(target_file)
            if not file_path.exists():
                logger.info(f"{Colors.RED}Error: File '{target_file}' does not exist{Colors.RESET}")
                raise SystemExit(1)
            if file_path.suffix != ".py":
                logger.info(
                    f"{Colors.RED}Error: File '{target_file}' is not a Python file (must have .py extension){Colors.RESET}"
                )
                raise SystemExit(1)

        # Initialize components
        self.project_discovery = ProjectDiscovery()
        self.config_loader = ConfigurationLoader(self.project_discovery.project_root)
        self.tool_executor = ToolExecutor(
            self.project_discovery,
            self.config_loader,
            dry_run=is_dry_run,
            verbose=args.verbose,
            directory_mode=directory_mode,
            target_directory=target_directory,
            file_mode=file_mode,
            target_file=target_file,
        )
        self.summary = ExecutionSummary()
        self.files_changed_by_tool: dict[str, list[Path]] = {}  # Track files changed in fix mode

    def _get_file_hashes(self, files: list[Path]) -> dict[Path, str]:
        """Get SHA256 hashes of files for change detection."""
        hashes: dict[Path, str] = {}
        for file_path in files:
            if file_path.exists():
                try:
                    with open(file_path, "rb") as f:
                        content = f.read()
                        hashes[file_path] = hashlib.sha256(content).hexdigest()
                except OSError:
                    # If we can't read the file, use empty hash
                    hashes[file_path] = ""
            else:
                hashes[file_path] = ""
        return hashes

    def _detect_changes_in_dry_run(self, result: ToolResult) -> bool:
        """Detect if a tool would make changes based on its output and exit code."""
        if result.name == "mypy":
            # MyPy: non-zero exit code or "error:" in output indicates issues
            return result.exit_code != 0 or (bool(result.stdout) and "error:" in result.stdout.lower())
        elif result.name in ["black", "ruff-format"]:
            # Black and ruff-format: non-zero exit code in --check mode means files would be reformatted
            return result.exit_code != 0
        elif result.name == "ruff":
            # Ruff: non-zero exit code means issues found (even with --fix in dry-run)
            return result.exit_code != 0
        elif result.name == "isort":
            # isort: non-zero exit code means imports would be sorted
            return result.exit_code != 0
        else:
            # Generic: non-zero exit code indicates changes needed
            return result.exit_code != 0

    def setup_logging(self) -> None:
        """Setup logging configuration."""
        level = logging.DEBUG if self.args.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def setup_colors(self) -> None:
        """Setup color output based on terminal capabilities."""
        if not sys.stdout.isatty() or self.args.no_color:
            Colors.disable()

    def print_header(self) -> None:
        """Print the script header with project information."""
        logger.info(f"{Colors.BOLD}{Colors.CYAN}")
        logger.info("=" * 60)
        logger.info("  Financial Companion - Code Format & Check")
        logger.info("=" * 60)
        logger.info(f"{Colors.RESET}")
        logger.info(f"Project root: {Colors.YELLOW}{self.project_discovery.project_root}{Colors.RESET}")
        logger.info(f"Virtual env:  {Colors.YELLOW}{self.project_discovery.venv_path or 'None'}{Colors.RESET}")
        logger.info(f"Config file:  {Colors.YELLOW}{self.config_loader.pyproject_path}{Colors.RESET}")
        logger.info(" ")

    def run(self) -> int:
        """Run the formatting and checking process."""
        start_time = time.time()

        self.print_header()

        # Determine which tools to run
        tools_to_run = []
        if self.args.isort_only:
            tools_to_run = [("isort", self.tool_executor.run_isort)]
        elif self.args.ruff_only:
            tools_to_run = [("ruff", self.tool_executor.run_ruff)]
        elif self.args.mypy_only:
            tools_to_run = [("mypy", self.tool_executor.run_mypy)]
        elif self.args.black_only:
            tools_to_run = [("black", self.tool_executor.run_black)]
        elif self.args.ruff_format_only:
            tools_to_run = [("ruff-format", self.tool_executor.run_ruff_format)]
        else:
            # Default: run all tools using ruff-format instead of isort+black to avoid conflicts
            tools_to_run = [
                ("ruff-format", self.tool_executor.run_ruff_format),
                ("ruff", self.tool_executor.run_ruff),
                ("mypy", self.tool_executor.run_mypy),
            ]

        # Get paths to process
        if self.args.dir or self.args.file:
            # In directory or file mode, paths are not used (handled by FileFilter)
            paths: list[str] = []
        else:
            paths = self.args.paths if self.args.paths else ["."]

        # Show what will be changed and ask for confirmation
        if not self._confirm_execution([name for name, _ in tools_to_run], paths):
            self._print_info("Operation cancelled by user.")
            return 0

        # Run the selected tools
        for tool_name, tool_func in tools_to_run:
            # Get filtered files once for this tool
            filtered_files = self.tool_executor.file_filter.get_filtered_files(tool_name, paths)

            # Track files before execution (only in fix mode)
            files_before: dict[Path, str] = {}
            if self.args.fix:
                files_before = self._get_file_hashes(filtered_files)

            result = tool_func(paths)
            self.summary.add_result(result)

            # Track which files were actually changed (only in fix mode)
            if self.args.fix and result.success:
                files_after = self._get_file_hashes(filtered_files)
                changed_files: list[Path] = []
                for file_path in filtered_files:
                    if file_path.exists():
                        before_hash = files_before.get(file_path, "")
                        after_hash = files_after.get(file_path, "")
                        if before_hash != after_hash:
                            changed_files.append(file_path)
                self.files_changed_by_tool[tool_name] = changed_files

        # Calculate total duration
        self.summary.total_duration = time.time() - start_time

        # Print summary
        self.print_summary()

        # Return appropriate exit code
        return self.get_exit_code()

    def _confirm_execution(self, tool_names: list[str], paths: list[str]) -> bool:
        """Ask user for confirmation before executing the tools."""
        # Collect files for all tools
        all_files_by_tool: dict[str, list[Path]] = {}
        total_files: set[Path] = set()

        for tool_name in tool_names:
            filtered_files = self.tool_executor.file_filter.get_filtered_files(tool_name, paths)
            all_files_by_tool[tool_name] = filtered_files
            total_files.update(filtered_files)

        if not total_files:
            logger.info(f"\n{Colors.YELLOW}No files found to process with any tools{Colors.RESET}")
            logger.info(
                f"{Colors.RED}This may be due to exclusions in pyproject.toml or no matching files in the specified paths.{Colors.RESET}"
            )
            return False

        # Show execution mode
        mode = "fix mode (will modify files)" if self.args.fix else "dry-run mode (will show what would change)"

        if self.args.file:
            target_info = f" on file '{self.args.file}'"
            filtering_info = " (bypassing pyproject.toml filtering)"
        elif self.args.dir:
            target_info = f" on directory '{self.args.dir}'"
            filtering_info = " (bypassing pyproject.toml filtering)"
        else:
            target_info = ""
            filtering_info = " (using pyproject.toml filtering)"
        logger.info(f"\n{Colors.BOLD}{Colors.YELLOW}Running in {mode}{target_info}{filtering_info}{Colors.RESET}")

        if len(tool_names) == 1:
            tool_name = tool_names[0]
            filtered_files = all_files_by_tool[tool_name]
            logger.info(f"\n{Colors.YELLOW}About to run {tool_name} on {len(filtered_files)} files:{Colors.RESET}")
        else:
            logger.info(
                f"\n{Colors.YELLOW}About to run {len(tool_names)} tools on {len(total_files)} total files:{Colors.RESET}"
            )
            for tool_name in tool_names:
                file_count = len(all_files_by_tool[tool_name])
                logger.info(f"  • {tool_name}: {file_count} files")

        # Show up to 10 files, then summarize the rest
        cutoff_file_count = 10
        display_files = list(total_files)[:cutoff_file_count]
        logger.info(f"\n{Colors.CYAN}Files to process:{Colors.RESET}")
        for file_path in display_files:
            logger.info(f"  📄 {Colors.CYAN}{file_path}{Colors.RESET}")

        if len(total_files) > cutoff_file_count:
            remaining = len(total_files) - cutoff_file_count
            logger.info(f"  ... and {remaining} more files")

        # Show configuration info for single tool
        if len(tool_names) == 1:
            tool_name = tool_names[0]
            logger.info(f"\n{Colors.YELLOW}Tool: {tool_name}{Colors.RESET}")

            def __log_exclusions(_excludes: list[str], cutoff: int) -> None:
                truncated_exclusions = _excludes[:cutoff]
                filler = "..." if len(_excludes) > cutoff else ""
                logger.info(f"  • Excludes: {truncated_exclusions}{filler}")

            if tool_name == "isort":
                logger.info("  • Will sort and organize import statements")
                if self.args.fix:
                    logger.info("  • Will modify files to fix import order")
                else:
                    logger.info("  • Will show what import changes are needed")
                isort_config = self.tool_executor.config_loader.get_tool_config("isort")
                src_paths = isort_config.get("src_paths", ["."])
                logger.info(f"  • Configured src_paths: {src_paths}")
            elif tool_name == "ruff":
                logger.info("  • Will check code formatting and linting issues")
                if self.args.fix:
                    logger.info("  • Will modify files to apply automatic fixes")
                else:
                    logger.info("  • Will show what fixes are needed")
                ruff_config = self.tool_executor.config_loader.get_tool_config("ruff")
                src_paths = ruff_config.get("src", ["."])
                excludes = ruff_config.get("exclude", [])
                logger.info(f"  • Configured src: {src_paths}")
                if excludes:
                    __log_exclusions(excludes, 3)
            elif tool_name == "mypy":
                logger.info("  • Will check for type errors (always read-only)")
                logger.info("  • Will not modify any files")
                mypy_config = self.tool_executor.config_loader.get_tool_config("mypy")
                excludes = mypy_config.get("exclude", [])
                logger.info("  • Configured to check: all_agents.task_agents.investinghub_agent.*")
                if excludes:
                    __log_exclusions(excludes, 2)
            elif tool_name == "black":
                logger.info("  • Will check code formatting")
                if self.args.fix:
                    logger.info("  • Will modify files to apply formatting")
                else:
                    logger.info("  • Will show diff of what would be formatted (read-only)")
                black_config = self.tool_executor.config_loader.get_tool_config("black")
                line_length = black_config.get("line-length", 88)
                target_version = black_config.get("target-version", ["py313"])
                logger.info(f"  • Configured line-length: {line_length}")
                logger.info(f"  • Configured target-version: {target_version}")
                extend_exclude = black_config.get("extend-exclude", "")
                if extend_exclude:
                    logger.info("  • Has custom exclude patterns configured")
            elif tool_name == "ruff-format":
                logger.info("  • Will check code formatting using ruff formatter")
                if self.args.fix:
                    logger.info("  • Will modify files to apply formatting")
                else:
                    logger.info("  • Will show what formatting changes are needed (read-only)")
                ruff_config = self.tool_executor.config_loader.get_tool_config("ruff")
                line_length = ruff_config.get("line-length", 88)
                src_paths = ruff_config.get("src", ["."])
                excludes = ruff_config.get("exclude", [])
                logger.info(f"  • Configured line-length: {line_length}")
                logger.info(f"  • Configured src: {src_paths}")
                if excludes:
                    __log_exclusions(excludes, 3)

        if self.args.fix:  # Only ask for confirmation if we're going to modify files
            try:
                tools_str = tool_names[0] if len(tool_names) == 1 else f"{len(tool_names)} tools"
                response = input(f"\n{Colors.BOLD}Proceed with {tools_str}? (y/N): {Colors.RESET}").strip().lower()
                return response in ["y", "yes"]
            except KeyboardInterrupt:
                logger.info(f"\n{Colors.YELLOW}Operation cancelled by user.{Colors.RESET}")
                return False
        else:
            # In dry-run mode, proceed without confirmation
            return True

    @staticmethod
    def _print_error(message: str) -> None:
        """Print an error message with formatting."""
        logger.info(f"{Colors.RED}{message}{Colors.RESET}")

    @staticmethod
    def _print_info(message: str) -> None:
        """Print an info message with formatting."""
        logger.info(f"{Colors.CYAN}{message}{Colors.RESET}")

    def print_summary(self) -> None:
        """Print execution summary."""
        is_fix_mode = self.args.fix
        mode_text = "Fix Mode" if is_fix_mode else "Dry-Run Mode"

        logger.info(f"\n{Colors.BOLD}{Colors.CYAN}{mode_text} Summary{Colors.RESET}")
        logger.info("=" * 50)

        for result in self.summary.results:
            status_color = Colors.GREEN if result.success else Colors.RED
            status_symbol = "✓" if result.success else "✗"

            logger.info(f"{status_color}{status_symbol} {result.name:<10} ({result.duration:.2f}s){Colors.RESET}")

            # Show files changed in fix mode or files that would be changed in dry-run mode
            file_count_cutoff = 5
            if is_fix_mode and result.name in self.files_changed_by_tool:
                changed_files = self.files_changed_by_tool[result.name]
                if changed_files:
                    logger.info(f"  {Colors.GREEN}Files modified: {len(changed_files)}{Colors.RESET}")
                    for file_path in changed_files[:5]:  # Show first 5 files
                        logger.info(f"    • {Colors.CYAN}{file_path}{Colors.RESET}")
                    if len(changed_files) > file_count_cutoff:
                        remaining = len(changed_files) - file_count_cutoff
                        logger.info(f"    ... and {remaining} more files")
                else:
                    logger.info(f"  {Colors.YELLOW}No files modified{Colors.RESET}")
            elif not is_fix_mode:
                # In dry-run mode, show what would be changed based on tool output and exit codes
                changes_detected = self._detect_changes_in_dry_run(result)
                if changes_detected:
                    if result.name == "mypy":
                        logger.info(
                            f"  {Colors.YELLOW}Type errors found (run with --fix to see full details){Colors.RESET}"
                        )
                    elif result.name in ["black", "ruff-format"]:
                        logger.info(
                            f"  {Colors.YELLOW}Files would be reformatted (run with --fix to apply){Colors.RESET}"
                        )
                    elif result.name in ["ruff", "isort"]:
                        logger.info(f"  {Colors.YELLOW}Fixes would be applied (run with --fix to apply){Colors.RESET}")
                elif result.name == "mypy":
                    logger.info(f"  {Colors.GREEN}No type errors found{Colors.RESET}")
                elif result.name in ["black", "ruff-format"]:
                    logger.info(f"  {Colors.GREEN}No formatting changes needed{Colors.RESET}")
                elif result.name in ["ruff", "isort"]:
                    logger.info(f"  {Colors.GREEN}No changes needed{Colors.RESET}")

            if not result.success:
                # Show detailed error information in summary for quick reference
                error_output = ""
                if result.name in ["mypy", "black", "ruff-format"]:
                    # MyPy outputs type errors to stdout, Black and ruff format output diffs to stdout
                    if result.stdout:
                        error_output = self.tool_executor.get_last_lines(
                            result.stdout, 3
                        )  # Show fewer lines in summary
                    elif result.stderr:
                        error_output = self.tool_executor.get_last_lines(result.stderr, 3)
                # Ruff and isort typically use stderr
                elif result.stderr:
                    error_output = self.tool_executor.get_last_lines(result.stderr, 3)
                elif result.stdout:
                    error_output = self.tool_executor.get_last_lines(result.stdout, 3)

                if error_output:
                    logger.info(f"  {Colors.RED}Last 3 lines of output:{Colors.RESET}")
                    logger.info(error_output)

        logger.info(f"\nTotal duration: {Colors.YELLOW}{self.summary.total_duration:.2f}s{Colors.RESET}")

        if is_fix_mode:
            total_files_changed = sum(len(files) for files in self.files_changed_by_tool.values())
            if total_files_changed > 0:
                logger.info(
                    f"{Colors.GREEN}{Colors.BOLD}✓ Successfully modified {total_files_changed} files!{Colors.RESET}"
                )
            else:
                logger.info(f"{Colors.GREEN}{Colors.BOLD}✓ All tools completed - no changes needed!{Colors.RESET}")
        elif self.summary.overall_success:
            logger.info(f"{Colors.GREEN}{Colors.BOLD}✓ All tools completed successfully!{Colors.RESET}")
            logger.info(f"{Colors.CYAN}Run with --fix flag to apply changes{Colors.RESET}")
        else:
            logger.info(
                f"{Colors.RED}{Colors.BOLD}✗ Some tools found issues. Run with --fix to address them.{Colors.RESET}"
            )

    def get_exit_code(self) -> int:
        """Get appropriate exit code for CI/CD integration."""
        if self.summary.overall_success:
            return 0  # Success

        # Check if any tool found issues (but didn't fail)
        has_issues = any(result.exit_code != 0 and result.name == "mypy" for result in self.summary.results)

        if has_issues:
            return 1  # Issues found

        return 2  # Tool failures


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Format and check Python code using ruff-format, ruff, and mypy by default (isort/black available individually)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                         # Run all tools in dry-run mode (ruff-format, ruff, mypy)
  %(prog)s --fix                   # Run all tools and apply changes (ruff-format, ruff, mypy)
  %(prog)s --dir src/              # Run all tools on 'src/' directory, bypassing pyproject.toml
  %(prog)s --dir src/ --fix        # Run all tools on 'src/' directory and apply changes
  %(prog)s --file src/module.py    # Run all tools on single file, bypassing pyproject.toml
  %(prog)s --file src/module.py --fix # Run all tools on single file and apply changes
  %(prog)s --isort-only            # Run only isort in dry-run mode
  %(prog)s --ruff-only --fix       # Run only ruff and apply changes
  %(prog)s --file src/module.py --ruff-only --fix # Run only ruff on single file and apply changes
  %(prog)s --mypy-only             # Run only mypy (always read-only)
  %(prog)s --black-only            # Run only black in dry-run mode
  %(prog)s --ruff-format-only      # Run only ruff format in dry-run mode
  %(prog)s --ruff-format-only --fix # Run only ruff format and apply changes
  %(prog)s --verbose               # Run all tools with detailed output
  %(prog)s src/ --fix              # Run all tools on specific directory using pyproject.toml filtering and apply changes
        """,
    )

    # Tool selection (mutually exclusive, optional - defaults to all tools)
    tool_group = parser.add_mutually_exclusive_group(required=False)
    tool_group.add_argument("--isort-only", action="store_true", help="Run only isort (import sorting)")
    tool_group.add_argument(
        "--ruff-only",
        action="store_true",
        help="Run only ruff (formatting and linting)",
    )
    tool_group.add_argument(
        "--mypy-only",
        action="store_true",
        help="Run only mypy (type checking, always read-only)",
    )
    tool_group.add_argument("--black-only", action="store_true", help="Run only black (code formatting)")
    tool_group.add_argument(
        "--ruff-format-only",
        action="store_true",
        help="Run only ruff format (code formatting)",
    )

    # Execution options
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply changes to files (default: dry-run mode shows what would change)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly enable dry-run mode (default behavior, kept for compatibility)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output including command execution details",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress non-essential output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    # Paths - these are mutually exclusive but we handle validation manually
    # since paths is positional and argparse requires mutually exclusive args to be optional
    parser.add_argument(
        "paths",
        nargs="*",
        help="Specific files or directories to process using pyproject.toml filtering (default: current directory)",
    )
    parser.add_argument(
        "--dir",
        type=str,
        help="Process all Python files in the specified directory, bypassing pyproject.toml filtering",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Process a single specific Python file, bypassing pyproject.toml filtering",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()

    # Validate argument combinations
    if args.quiet and args.verbose:
        parser.error("--quiet and --verbose are mutually exclusive")

    # Validate that paths, --dir, and --file are mutually exclusive
    path_options = [bool(args.paths), bool(args.dir), bool(args.file)]
    if sum(path_options) > 1:
        parser.error("paths, --dir, and --file are mutually exclusive")

    try:
        runner = FormatAndCheckRunner(args)
        return runner.run()
    except KeyboardInterrupt:
        logger.info(f"\n{Colors.YELLOW}Interrupted by user{Colors.RESET}")
        return 130
    except Exception as e:
        logger.info(f"{Colors.RED}Unexpected error: {e}{Colors.RESET}")
        if args.verbose:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
