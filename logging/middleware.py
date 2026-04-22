"""FastAPI middleware for enhanced logging integration."""

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from common.logging.core import log_request, logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to add request context to logs and log HTTP requests."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())

        # Get client IP (handle proxy headers)
        client_ip: str = self._get_client_ip(request)

        # Start timing
        start_time: float = time.time()

        # Add request context to logger
        with logger.contextualize(
            request_id=request_id,
            request_path=request.url.path,
            client_ip=client_ip,
            method=request.method,
            url=str(request.url),
        ):
            # Log incoming request
            logger.info(
                f"Incoming request: {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "request_path": request.url.path,
                    "client_ip": client_ip,
                    "method": request.method,
                    "url": str(request.url),
                    "user_agent": request.headers.get("user-agent", ""),
                },
            )

            try:
                # Process request
                response = await call_next(request)

                # Calculate duration
                duration_seconds: float = time.time() - start_time

                # Log completed request
                log_request(
                    method=request.method,
                    request_id=request_id,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration=duration_seconds,
                    client_ip=client_ip,
                )

                # Add request ID to response headers for tracing
                response.headers["X-Request-ID"] = request_id

                return response

            except Exception as e:
                # Calculate duration for failed requests
                error_duration_seconds: float = time.time() - start_time

                # Log error
                logger.error(
                    "Request failed: %s %s - %s",
                    request.method,
                    request.url.path,
                    str(e),
                    extra={
                        "request_id": request_id,
                        "request_path": request.url.path,
                        "client_ip": client_ip,
                        "method": request.method,
                        "url": str(request.url),
                        "duration": error_duration_seconds,
                        "error": str(e),
                    },
                )

                # Re-raise the exception
                raise

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Extract client IP address from request, handling proxy headers."""
        # Check for forwarded headers (common in load balancers/proxies)
        forwarded_for: str | None = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            return forwarded_for.split(",")[0].strip()

        # Check for real IP header (some proxies use this)
        real_ip: str | None = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback to direct client IP
        if hasattr(request, "client") and request.client:
            return str(request.client.host)

        return "unknown"
