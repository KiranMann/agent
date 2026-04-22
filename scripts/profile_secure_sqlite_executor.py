#!/usr/bin/env python3
"""Profile memory usage and abort threshold for secure_sqlite_executor using the example query.

Usage:
  python scripts/profile_secure_sqlite_executor.py [--sizes 200 1000 5000 ...] [--json-out results.json]

Outputs a table per size with:
  - ok/error status
  - RSS before/after (KiB) and delta
  - Python peak allocations (KiB) via tracemalloc
  - abort reason classification (timeout vs limit_or_other)
  - elapsed time (seconds)
"""

import argparse
import gc
import importlib.util
import json
import logging
import os
import sqlite3
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    import resource  # Unix/macOS
except Exception:
    resource = None  # type: ignore[assignment]

try:
    import psutil  # type: ignore[import-untyped]
except Exception:
    psutil = None


def setup_environment() -> Path:
    """Add project root to sys.path and set PYTHONPATH."""
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("PYTHONPATH", str(project_root))
    return project_root


@dataclass
class ProfileResult:
    n: int
    ok: bool
    reason: str
    error: str | None
    # legacy summary
    rss_before_kb: int | None
    rss_after_kb: int | None
    rss_delta_kb: int | None
    # detailed breakdown
    rss_before_build_kb: int | None
    rss_after_build_kb: int | None
    rss_build_delta_kb: int | None
    rss_before_query_kb: int | None
    rss_after_query_kb: int | None
    rss_query_delta_kb: int | None
    rss_after_gc_kb: int | None
    # python-only peak alloc
    py_peak_kb: int
    elapsed_s: float


class MemoryLogHandler(logging.Handler):
    """Collect log messages in memory for classification."""

    def __init__(self) -> None:
        """Used to track memory handling."""
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception as e:
            print(e)
            pass


def get_rss_kb() -> int | None:
    """Return current process RSS in KiB if measurable on this platform.

    Prefer psutil for 'current' RSS; resource.ru_maxrss is a 'max so far' metric on many platforms.
    """
    # Prefer psutil (current RSS)
    try:
        if psutil is not None:
            proc = psutil.Process(os.getpid())
            return int(proc.memory_info().rss // 1024)  # bytes -> KiB
    except Exception as e:
        print(e)
        pass

    # Fallback to resource (may be max, not current)
    try:
        if resource is not None:
            ru = resource.getrusage(resource.RUSAGE_SELF)
            rss = ru.ru_maxrss
            if sys.platform == "darwin":
                return int(rss // 1024)  # bytes -> KiB
            else:
                return int(rss)  # KiB on Linux
    except Exception as e:
        print(e)
        pass
    return None


def build_tx_data(n: int) -> list[dict[str, Any]]:
    """Build synthetic transactions for the example query."""
    rows: list[dict[str, Any]] = []
    base = datetime(2024, 1, 1)
    for i in range(n):
        ts = (base + timedelta(days=i % 365)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(
            {
                "id": f"tx_{i}",
                "timestamp": ts,
                "amount": float((i % 200) - 100),
                "currency": "USD",
                "merchant": "ACME_CO",
                "description": "test transaction",
                "category": "Entertainment",
            }
        )
    return rows


def load_secure_executor_module(project_root: Path) -> ModuleType:
    """Load secure_sqlite_executor directly by file path to avoid circular imports via package __init__."""
    module_path = project_root / "all_agents" / "common" / "tools" / "secure_sqlite_executor.py"
    spec = importlib.util.spec_from_file_location("secure_sqlite_executor", str(module_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_one(n: int, module: ModuleType, logger: logging.Logger, query: str) -> ProfileResult:
    """Run one profile attempt with detailed build/query/GC memory phases."""
    # Phase A: baseline before building dataset
    gc.collect()
    rss_before_build = get_rss_kb()

    # Build dataset that scales with n
    tx_data = build_tx_data(n)

    rss_after_build = get_rss_kb()
    rss_build_delta = None
    if rss_before_build is not None and rss_after_build is not None:
        rss_build_delta = int(rss_after_build - rss_before_build)

    # Prepare logging capture
    handler = MemoryLogHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # Phase B: measure before query
    gc.collect()
    rss_before_query = get_rss_kb()

    # Run query
    tracemalloc.start()
    start = time.perf_counter()
    ok = True
    error: str | None = None
    reason = "-"
    try:
        _ = module.execute_secure_tx_query(tx_data, query)
    except sqlite3.OperationalError as e:
        ok = False
        error = str(e)
    elapsed = time.perf_counter() - start
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rss_after_query = get_rss_kb()
    rss_query_delta = None
    if rss_before_query is not None and rss_after_query is not None:
        rss_query_delta = int(rss_after_query - rss_before_query)

    # classify reason from log messages
    msgs = handler.messages[:]
    logger.removeHandler(handler)
    if not ok:
        reason = "timeout" if any("Query timeout exceeded" in m for m in msgs) else "limit_or_other"

    # Phase C: drop references and GC
    del tx_data
    gc.collect()
    rss_after_gc = get_rss_kb()

    # Legacy summary (from build start to after query)
    rss_before = rss_before_build
    rss_after = rss_after_query
    rss_delta = None
    if rss_before is not None and rss_after is not None:
        rss_delta = int(rss_after - rss_before)

    return ProfileResult(
        n=n,
        ok=ok,
        reason=reason,
        error=error,
        rss_before_kb=rss_before,
        rss_after_kb=rss_after,
        rss_delta_kb=rss_delta,
        rss_before_build_kb=rss_before_build,
        rss_after_build_kb=rss_after_build,
        rss_build_delta_kb=rss_build_delta,
        rss_before_query_kb=rss_before_query,
        rss_after_query_kb=rss_after_query,
        rss_query_delta_kb=rss_query_delta,
        rss_after_gc_kb=rss_after_gc,
        py_peak_kb=int(peak_bytes // 1024),
        elapsed_s=elapsed,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile secure_sqlite_executor with example query")
    parser.add_argument(
        "--sizes",
        nargs="*",
        type=int,
        help="Explicit list of transaction sizes (e.g., --sizes 200 1000 5000)",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=200,
        help="Minimum transaction count",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=40000,
        help="Maximum transaction count",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=2000,
        help="Step between sizes when --sizes not provided",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        help="Optional path to write JSON results",
    )
    return parser.parse_args()


EXAMPLE_QUERY = (
    "SELECT strftime('%Y-%m-%d', timestamp) as cycle_start, "
    "SUM(amount) as total_spent "
    "FROM user_tx "
    "WHERE category = 'Entertainment' "
    "GROUP BY strftime('%Y-%W', timestamp) "
    "ORDER BY cycle_start DESC "
    "LIMIT 8;"
)


def main() -> None:
    project_root = setup_environment()
    args = parse_args()

    module = load_secure_executor_module(project_root)
    logger = module.SQLITE_SUS_TX_LOGGER

    sizes = args.sizes or list(range(args.min_size, args.max_size + 1, args.step))

    print(
        "size,ok,build_delta_kb,query_delta_kb,py_peak_kb,elapsed_s,reason,rss_before_kb,rss_after_kb,rss_delta_kb,rss_after_gc_kb"
    )
    results: list[ProfileResult] = []
    abort_at: int | None = None
    abort_reason: str | None = None

    for n in sizes:
        res = run_one(n, module, logger, EXAMPLE_QUERY)
        results.append(res)
        print(
            f"{res.n},{res.ok},{res.rss_build_delta_kb},{res.rss_query_delta_kb},"
            f"{res.py_peak_kb},{res.elapsed_s:.4f},{res.reason},"
            f"{res.rss_before_kb},{res.rss_after_kb},{res.rss_delta_kb},{res.rss_after_gc_kb}"
        )
        if not res.ok and abort_at is None:
            abort_at = res.n
            abort_reason = res.reason

    if abort_at is not None:
        print(f"# abort_threshold_n={abort_at} reason={abort_reason}")
    else:
        print("# no abort observed")

    if args.json_out:
        try:
            out = {
                "sizes": sizes,
                "results": [asdict(r) for r in results],
                "abort_threshold_n": abort_at,
                "abort_reason": abort_reason,
            }
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            print(f"# wrote JSON to {args.json_out}")
        except Exception as e:
            print(f"# failed to write JSON: {e}")


if __name__ == "__main__":
    main()
