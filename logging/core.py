"""Enhanced logging handler.

Combines best practices from DHP Observe logging and CEB logging implementations
"""

import json
import logging
import os
import queue
import socket
import sys
import threading
import time
import uuid
from functools import lru_cache
from queue import Queue
from typing import Any

import boto3
import requests
from loguru import logger as loguru_logger

from common.configs.app_config_settings import AppConfig
from common.metrics import record_log_level_event
from common.utils.security_redactor import SecurityRedactor


class EnhancedLoggingHandler(logging.Handler):
    """Enhanced logging handler that combines features from both reference implementations.

    - Batched log sending with configurable batch size and flush intervals
    - Automatic DHP environment detection
    - Security redaction of sensitive data
    - Proper SSL certificate handling
    - Request context tracking
    - Graceful error handling and fallback

    Note: Ruff's T201 rule discourages print() statements in production code because they bypass
    structured logging, lack log levels, and don't integrate with observability tools.
    Here print is used as a last-resort fallback mechanism, which is a legitimate exception,
    so # noqa: T201 has been added to the print statements to suppress the ruff warning.
    """

    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: int = 10,
        max_wait_time: int = 30,
        enable_local_fallback: bool = True,
    ):
        """Initialize the DHPHandler with batching and fallback configuration.

        Args:
            batch_size: Maximum number of log records to batch before sending (default: 50)
            flush_interval: Time in seconds between automatic flushes (default: 10)
            max_wait_time: Maximum time in seconds to wait before forcing a flush (default: 30)
            enable_local_fallback: Enable fallback to local logging on DHP failures (default: True)
        """
        super().__init__()
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_wait_time = max_wait_time
        self.enable_local_fallback = enable_local_fallback

        self.queue: Queue[dict[str, Any]] = Queue()
        self.stop_event = threading.Event()
        self.last_send_time = time.time()
        self.last_added: float | None = None

        # Start background worker thread
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

        # Reduce noise from HTTP client logging
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    @staticmethod
    def is_dhp_environment() -> bool:
        """Detect if running in DHP environment."""
        return bool(
            os.environ.get("Serilog__LogitOptions__Host")  # noqa: SIM112 - .NET config convention
            or os.environ.get("DHP_APP_NAME")
            or os.environ.get("DHP_SPLUNK_HEC_TOKEN")
            or os.environ.get("SECRET_ARNS")
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Process and queue log record."""
        try:
            # Skip DEBUG logs in production
            if record.levelno == logging.DEBUG and self.is_dhp_environment():
                return

            # Format the log message and redact sensitive data
            log_message = SecurityRedactor.redact_sensitive_data_from_structured_text(record.getMessage())

            # Get request context if available (from FastAPI middleware)
            request_id = getattr(record, "request_id", str(uuid.uuid4()))
            request_path = getattr(record, "request_path", record.pathname)
            client_ip = getattr(record, "client_ip", None)
            method = getattr(record, "method", None)
            url = getattr(record, "url", None)
            status_code = getattr(record, "status_code", None)

            # Create structured log payload
            payload = self._create_log_payload(
                message=log_message,
                level=record.levelname,
                request_id=request_id,
                request_path=request_path,
                client_ip=client_ip,
                method=method,
                url=url,
                status_code=status_code,
                timestamp=record.created,
            )

            self.queue.put(payload)
            self.last_added = time.time()

        except Exception as e:
            self.handleError(record)
            if self.enable_local_fallback:
                print(f"Logging error: {e}", file=sys.stderr)  # noqa: T201

    def _create_log_payload(
        self,
        message: str,
        level: str,
        request_id: str,
        request_path: str,
        client_ip: str | None = None,
        method: str | None = None,
        url: str | None = None,
        status_code: str | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Create structured log payload."""
        event_data = {
            "EVENT_MESSAGE": message,
            "APPLICATION_NAME": os.environ.get("DHP_APP_NAME"),
            "Level": level,
            "RequestId": request_id,
            "RequestPath": request_path,
            "ENVIRONMENT": os.environ.get("Serilog__LogitOptions__Environment"),  # noqa: SIM112 - .NET config convention
            "SERVER": socket.gethostname(),
            "message": {"data": message},
            "timestamp": timestamp or time.time(),
        }

        # Add request-specific fields if available
        if client_ip:
            event_data["CLIENT_IP"] = client_ip
        if method:
            event_data["METHOD"] = method
        if url:
            event_data["URL"] = SecurityRedactor.redact_sensitive_data_from_structured_text(url)
        if status_code:
            event_data["StatusCode"] = status_code

        payload = {
            "source": os.environ.get("Serilog__LogitOptions__Source"),  # noqa: SIM112 - .NET config convention
            "sourcetype": os.environ.get("Serilog__LogitOptions__SourceType", "json"),  # noqa: SIM112 - .NET config convention
            "event": event_data,
            "fields": {
                "env": os.environ.get("Serilog__LogitOptions__Environment"),  # noqa: SIM112 - .NET config convention
                "plat": os.environ.get("DHP_PLATFORM", "local"),
            },
        }

        return payload

    def _process_queue(self) -> None:
        """Background worker to process queued log messages."""
        batch = []

        while not self.stop_event.is_set():
            try:
                # Try to get a message from queue
                try:
                    message = self.queue.get(timeout=1.0)
                    batch.append(message)
                except queue.Empty:
                    pass

                # Send batch if conditions are met
                should_send = (
                    len(batch) >= self.batch_size
                    or (batch and self.last_added and (time.time() - self.last_added) >= self.flush_interval)
                    or (batch and (time.time() - self.last_send_time) >= self.max_wait_time)
                )

                if should_send:
                    self._send_batch(batch)
                    batch = []
                    self.last_send_time = time.time()

            except Exception as e:
                if self.enable_local_fallback:
                    print(f"Queue processing error: {e}", file=sys.stderr)  # noqa: T201

        # Send remaining logs on shutdown
        if batch:
            self._send_batch(batch)

    def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        """Send batch of log messages to observe endpoint."""
        if not batch:
            return

        if not self._has_required_config():
            if self.enable_local_fallback and not self.is_dhp_environment():
                self._fallback_log_batch_to_stderr(batch)
            return

        try:
            payload = "\n".join(json.dumps(event) for event in batch)

            # Get authentication token
            token = os.environ.get("DHP_SPLUNK_HEC_TOKEN") or self._get_secret("SplunkHecToken")
            if not token:
                if self.enable_local_fallback:
                    print("No Splunk HEC token available", file=sys.stderr)  # noqa: T201
                return

            headers = {
                "Authorization": f"Splunk {token}",
                "X-Splunk-Request-Channel": str(uuid.uuid4()),
                "Content-Type": "application/json",
            }

            # Construct host URL with consistent double quotes usage
            host_url = f"{os.environ.get('Serilog__LogitOptions__Host')}/services/collector/event"  # noqa: SIM112 - .NET config convention

            # Send the batch - requests automatically uses system certificates via environment variables
            response = requests.post(url=host_url, headers=headers, data=payload, timeout=30.0)
            response.raise_for_status()

        except requests.RequestException as e:
            if self.enable_local_fallback:
                print(f"Failed to send log batch: {e}", file=sys.stderr)  # noqa: T201
                self._fallback_log_batch_to_stderr(batch)

    def _has_required_config(self) -> bool:
        """Check if required Splunk configuration is available."""
        return bool(
            os.environ.get("Serilog__LogitOptions__Host")  # noqa: SIM112 - .NET config convention
            and os.environ.get("DHP_SPLUNK_HEC_TOKEN")
        )

    def _fallback_log_batch_to_stderr(self, batch: list[dict[str, Any]]) -> None:
        """Fallback: log batch entries to stderr when remote logging unavailable."""
        for log_entry in batch:
            print(json.dumps(log_entry["event"], indent=2), file=sys.stderr)  # noqa: T201

    def _get_secret(self, secret_name: str) -> str | None:
        """Get secret from AWS Secrets Manager (DHP environment)."""
        try:
            secret_arns = os.environ.get("SECRET_ARNS", "").split(",")
            for secret_arn in secret_arns:
                if not secret_arn.strip():
                    continue

                client = boto3.client(
                    "secretsmanager",
                    region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
                )
                secret_value = client.get_secret_value(SecretId=secret_arn.strip())
                secrets = json.loads(secret_value["SecretString"])

                if secret_name in secrets:
                    return str(secrets[secret_name])

        except Exception as e:
            if self.enable_local_fallback:
                print(f"Failed to get secret {secret_name}: {e}", file=sys.stderr)  # noqa: T201

        return None

    def close(self) -> None:
        """Gracefully close the handler."""
        self.stop_event.set()
        self.worker.join(timeout=5.0)
        self.flush()
        super().close()

    def flush(self) -> None:
        """Flush any remaining log messages."""
        batch = []
        try:
            while not self.queue.empty():
                batch.append(self.queue.get_nowait())
        except queue.Empty:
            pass

        if batch:
            self._send_batch(batch)


def _record_log_level_metrics(loguru_record: dict[str, Any]) -> None:
    """Record warning/error metrics for all log events emitted via logging core."""
    level_name = str(loguru_record["level"].name)

    if level_name not in {"WARNING", "ERROR", "CRITICAL"}:
        return

    record_log_level_event(
        level=level_name,
        logger_name=str(loguru_record.get("name") or ""),
        module_name=str(loguru_record.get("module") or ""),
        function_name=str(loguru_record.get("function") or ""),
    )


def _log_metrics_sink(message: Any) -> None:
    """Loguru sink that transforms warning/error records into metric events."""
    _record_log_level_metrics(message.record)


@lru_cache(maxsize=1)
def setup_logging():  # type: ignore[no-untyped-def]
    """Setup enhanced logging configuration."""
    # Remove default loguru handlers
    loguru_logger.remove()

    if EnhancedLoggingHandler.is_dhp_environment():
        # DHP environment - use enhanced handler with observe integration
        enhanced_handler = EnhancedLoggingHandler(batch_size=100, flush_interval=5, max_wait_time=30)

        # Configure loguru to use our enhanced handler
        loguru_logger.add(
            sink=enhanced_handler,
            level=AppConfig.LOGLEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
            backtrace=True,
            diagnose=True,
        )

    else:
        # Local development - enhanced console logging
        loguru_logger.add(
            sys.stdout,
            level="DEBUG",
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | {message}",
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

    # Emit dedicated global warning/error counters from the central logger.
    loguru_logger.add(_log_metrics_sink, level="WARNING", backtrace=False, diagnose=False)

    return loguru_logger


# Create the logger instance
logger = setup_logging()


# Convenience functions for common logging patterns
def log_request(
    method: str,
    request_id: str,
    path: str,
    status_code: int,
    duration: float,
    client_ip: str | None = None,
) -> None:
    """Log HTTP request with structured data."""
    if path == "/health":  # Skip health check logs
        return

    logger.info(  # noqa: PLE1205
        "{} {} - {} - {:.3f}s",
        method,
        path,
        status_code,
        duration,
        extra={
            "method": method,
            "request_id": request_id,
            "request_path": path,
            "status_code": str(status_code),
            "duration": duration,
            "client_ip": client_ip,
        },
    )


def log_error(error: Exception, context: str | None = None, **kwargs: Any) -> None:
    """Log error with context and structured data."""
    message = f"Error in {context}: {error!s}" if context else f"Error: {error!s}"
    logger.error("{}", message, extra=kwargs)  # noqa: PLE1205


def log_security_event(event_type: str, details: str, client_ip: str | None = None, **kwargs: Any) -> None:
    """Log security-related events."""
    logger.warning(  # noqa: PLE1205
        "Security event - {}: {}",
        event_type,
        details,
        extra={"security_event": event_type, "client_ip": client_ip, **kwargs},
    )
