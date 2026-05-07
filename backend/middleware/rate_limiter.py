"""
Rate Limiter Middleware — configurable rate limiting via slowapi.
Optimized: auto-detects Redis availability to avoid startup delays.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.config import get_settings

settings = get_settings()


def _get_storage_uri() -> str:
    """Determine rate limiter storage — Redis if reachable, else in-memory."""
    if "redis" in settings.REDIS_URL:
        try:
            import socket

            # Quick connectivity check — don't hang on unreachable Redis
            parts = settings.REDIS_URL.replace("redis://", "").split(":")
            host = parts[0] if parts[0] else "localhost"
            port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # 500ms timeout
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return settings.REDIS_URL
        except Exception:
            pass
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_GENERAL],
    storage_uri=_get_storage_uri(),
    enabled=settings.ENVIRONMENT != "test",
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for rate limit exceeded errors in RFC 7807 format."""
    return JSONResponse(
        status_code=429,
        content={
            "type": "about:blank",
            "title": "Rate Limit Exceeded",
            "status": 429,
            "detail": f"Too many requests. {str(exc.detail)}",
            "instance": str(request.url.path),
        },
        headers={"Retry-After": str(exc.retry_after) if hasattr(exc, "retry_after") else "60"},
    )
