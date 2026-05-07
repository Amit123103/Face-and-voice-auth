"""
Audit Middleware — logs every request with IP, user-agent, user_id, timing, status.
Performance optimized: skips static asset and health check logging.
"""

import time
import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("audit")

# Paths that are too noisy / not security relevant to log
_SKIP_AUDIT_PREFIXES = ("/css/", "/js/", "/static/", "/favicon")
_SKIP_AUDIT_PATHS = frozenset({"/health", "/metrics", "/openapi.json"})


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs all API requests with full context for security auditing."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        path = request.url.path

        # Fast-path: skip audit logging for static assets and frequent probes
        if path.startswith(_SKIP_AUDIT_PREFIXES) or path in _SKIP_AUDIT_PATHS:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        start_time = time.perf_counter()  # perf_counter is higher-resolution than time.time()

        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        method = request.method

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "duration_ms": duration_ms,
                    "status_code": 500,
                    "error": str(exc),
                },
            )
            raise

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        user_id = getattr(request.state, "user_id", None)

        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "user_id": user_id,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        return response
