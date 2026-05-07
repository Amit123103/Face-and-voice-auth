"""
CSRF Protection Middleware — double-submit cookie pattern.
Performance optimized: skips static assets and uses set-based lookups.
"""

import secrets
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PATHS = frozenset({
    "/api/auth/login", "/api/auth/register", "/health", "/metrics", "/docs", "/openapi.json", "/redoc"
})
STATIC_PREFIXES = ("/css/", "/js/", "/static/")


from backend.config import get_settings
settings = get_settings()

class CSRFMiddleware(BaseHTTPMiddleware):
    """Implements double-submit cookie CSRF protection."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip CSRF entirely for static assets — pure speed
        if path.startswith(STATIC_PREFIXES):
            return await call_next(request)

        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        if not csrf_cookie:
            csrf_cookie = secrets.token_hex(32)

        if request.method not in SAFE_METHODS and settings.ENVIRONMENT != "test":
            is_exempt = path in EXEMPT_PATHS or any(path.startswith(ep) for ep in EXEMPT_PATHS)

            if not is_exempt:
                header_token = request.headers.get(CSRF_HEADER_NAME, "")
                if not header_token or header_token != csrf_cookie:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "type": "about:blank",
                            "title": "CSRF Validation Failed",
                            "status": 403,
                            "detail": "Missing or invalid CSRF token",
                        },
                    )

        response = await call_next(request)

        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=csrf_cookie,
            httponly=False,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=3600,
        )

        return response
