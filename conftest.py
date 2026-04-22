import os
import sys
from pathlib import Path

from common.logging import logger

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# This should probably be revisited later, as the solution feels hacky.
# Disable OTLP metrics export during tests to prevent the OpenTelemetry
# PeriodicExportingMetricReader from attempting to flush to a non-existent
# collector on process shutdown, which causes a segfault (exit code 139).
os.environ.setdefault("OTLP_METRICS_ENABLED", "False")

# Tell the OpenTelemetry SDK to use no-op implementations for the global
# meter/tracer providers.  This prevents accidental real metric collection
# during unit tests while still allowing tests that explicitly construct
# SDK providers to function normally.
os.environ.setdefault("OTEL_SDK_DISABLED", "True")


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def] # noqa: ARG001
    """Gracefully shut down any OpenTelemetry MeterProvider at session end.

    Some tests create real ``SdkMeterProvider`` instances (with mocked
    exporters) that register ``atexit`` handlers.  During CPython 3.13
    interpreter shutdown these handlers race with thread teardown causing
    a segfault (exit code 139).  Explicitly shutting down the global
    provider here—while threads are still alive—avoids the crash.
    """
    logger.info("Running teardown with pytest sessionfinish...")
    try:
        from opentelemetry import metrics  # noqa: PLC0415

        provider = metrics.get_meter_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except ImportError:
        logger.warning("OpenTelemetry metrics module not found during pytest sessionfinish teardown")
    except AttributeError:
        logger.exception(
            "OpenTelemetry MeterProvider does not have the get_meter_provider or "
            "shutdown method during pytest sessionfinish teardown"
        )
    except Exception:
        logger.exception("Failed to shutdown OpenTelemetry MeterProvider")
