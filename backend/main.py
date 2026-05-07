"""
FaceVoiceAuth — Main FastAPI Application
Enterprise tri-modal biometric authentication platform.
Optimized for fast startup and high-throughput request handling.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from backend.routers import auth, face, voice, biometric, admin, health, transaction, documents, vault, account

from backend.config import get_settings
from backend.database import init_db, close_db
from backend.middleware.csrf import CSRFMiddleware
from backend.middleware.audit import AuditMiddleware
from backend.middleware.rate_limiter import limiter, rate_limit_exceeded_handler

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _preload_ml_models() -> None:
    """Pre-load ML models in a background thread so startup isn't blocked."""
    try:
        from backend.services.face_service import face_service
        logger.info(f"Face model ready: {face_service.is_ready}")
    except Exception as e:
        logger.warning(f"Face model pre-load skipped: {e}")
    try:
        from backend.services.voice_service import voice_service
        logger.info(f"Voice model ready: {voice_service.is_ready}")
    except Exception as e:
        logger.warning(f"Voice model pre-load skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    await init_db()
    from backend.database import sync_database_schema
    await sync_database_schema()
    logger.info("Database initialized and synchronized")

    await _seed_admin_user()

    # Pre-load ML models in background thread — don't block the event loop
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _preload_ml_models)
    logger.info("ML model pre-load scheduled in background")

    yield

    await close_db()
    logger.info("Application shutdown complete")


async def _seed_admin_user() -> None:
    """Seed the initial admin user if not exists."""
    from backend.database import async_session_factory
    from backend.models.user import User, UserRole, AuthMode
    from backend.services.auth_service import auth_service
    from backend.services.encryption_service import encryption_service
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(User).where(User.email == settings.ADMIN_EMAIL)
        )
        if result.scalar_one_or_none() is None:
            salt = encryption_service.generate_salt()
            admin = User(
                email=settings.ADMIN_EMAIL,
                username="admin",
                full_name="System Administrator",
                hashed_password=auth_service.hash_password(settings.ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                auth_mode=AuthMode.PASSWORD,
                is_active=True,
                is_verified=True,
                encryption_salt=salt,
                security_score=20.0,
            )
            db.add(admin)
            await db.commit()
            logger.info(f"Admin user seeded: {settings.ADMIN_EMAIL}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Enterprise tri-modal biometric authentication platform with "
        "face recognition, voice verification, and password login."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter

# ── Performance: GZip compression for all responses ──
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(AuditMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler returning RFC 7807 Problem Detail JSON."""
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        exc_info=not settings.is_production,
    )

    detail = str(exc) if not settings.is_production else "An internal error occurred"

    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "Internal Server Error",
            "status": 500,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc) -> JSONResponse:
    """Custom 404 handler."""
    return JSONResponse(
        status_code=404,
        content={
            "type": "about:blank",
            "title": "Not Found",
            "status": 404,
            "detail": f"The resource at {request.url.path} was not found",
            "instance": str(request.url.path),
        },
    )


# ── Import and mount routers ──

app.include_router(auth.router)
app.include_router(face.router)
app.include_router(voice.router)
app.include_router(biometric.router)
app.include_router(admin.router)
app.include_router(health.router)
app.include_router(transaction.router)
app.include_router(documents.router)
app.include_router(vault.router)
app.include_router(account.router)

# ── Serve frontend static files with caching headers ──
_frontend_dir = Path(__file__).parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/css", StaticFiles(directory=str(_frontend_dir / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(_frontend_dir / "js")), name="js")
    logger.info(f"Static files mounted from {_frontend_dir}")


@app.middleware("http")
async def cache_static_assets(request: Request, call_next):
    """Add aggressive Cache-Control headers for static CSS/JS assets."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/css/") or path.startswith("/js/"):
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        response.headers["Vary"] = "Accept-Encoding"
    return response


@app.get("/", include_in_schema=False)
async def root():
    """API root — service information."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# ── Serve frontend HTML pages ──


@app.get("/index.html", include_in_schema=False)
@app.get("/home", include_in_schema=False)
async def serve_index():
    return FileResponse(str(_frontend_dir / "index.html"), media_type="text/html")


@app.get("/login.html", include_in_schema=False)
async def serve_login():
    return FileResponse(str(_frontend_dir / "login.html"), media_type="text/html")


@app.get("/register.html", include_in_schema=False)
async def serve_register():
    return FileResponse(str(_frontend_dir / "register.html"), media_type="text/html")


@app.get("/dashboard.html", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(str(_frontend_dir / "dashboard.html"), media_type="text/html")


@app.get("/admin.html", include_in_schema=False)
async def serve_admin():
    return FileResponse(str(_frontend_dir / "admin.html"), media_type="text/html")
