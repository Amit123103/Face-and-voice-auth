"""
Health Router — public health check and Prometheus-compatible metrics.
"""

import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.services.face_service import face_service
from backend.services.voice_service import voice_service
from backend.config import get_settings

settings = get_settings()
router = APIRouter(tags=["Health & Metrics"])

_start_time = time.time()

_metrics = {
    "requests_total": 0,
    "auth_success_total": 0,
    "auth_failure_total": 0,
    "face_verify_total": 0,
    "face_verify_latency_sum_ms": 0,
    "voice_verify_total": 0,
    "voice_verify_latency_sum_ms": 0,
    "voice_liveness_rejection_total": 0,
    "fusion_scores": [],
}


def record_metric(key: str, value: float = 1.0) -> None:
    """Record a metric value."""
    if key in _metrics:
        if isinstance(_metrics[key], list):
            _metrics[key].append(value)
            if len(_metrics[key]) > 1000:
                _metrics[key] = _metrics[key][-500:]
        else:
            _metrics[key] += value


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Public health check endpoint."""
    db_ok = True
    try:
        await db.execute(select(func.count(User.id)))
    except Exception:
        db_ok = False

    uptime = int(time.time() - _start_time)

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "face_model": "loaded" if face_service.is_ready else "unavailable",
        "voice_model": "loaded" if voice_service.is_ready else "unavailable",
        "uptime_seconds": uptime,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    uptime = int(time.time() - _start_time)

    avg_face_latency = 0
    if _metrics["face_verify_total"] > 0:
        avg_face_latency = _metrics["face_verify_latency_sum_ms"] / _metrics["face_verify_total"]

    avg_voice_latency = 0
    if _metrics["voice_verify_total"] > 0:
        avg_voice_latency = _metrics["voice_verify_latency_sum_ms"] / _metrics["voice_verify_total"]

    # Note: Fusion scores are recorded but not currently exposed in metrics

    auth_total = _metrics["auth_success_total"] + _metrics["auth_failure_total"]
    success_rate = 0
    if auth_total > 0:
        success_rate = round(_metrics["auth_success_total"] / auth_total, 4)

    voice_rejection_rate = 0
    if _metrics["voice_verify_total"] > 0:
        voice_rejection_rate = round(_metrics["voice_liveness_rejection_total"] / _metrics["voice_verify_total"], 4)

    lines = [
        "# HELP facevoiceauth_uptime_seconds Server uptime in seconds",
        "# TYPE facevoiceauth_uptime_seconds gauge",
        f"facevoiceauth_uptime_seconds {uptime}",
        "",
        "# HELP facevoiceauth_requests_total Total API requests",
        "# TYPE facevoiceauth_requests_total counter",
        f'facevoiceauth_requests_total {_metrics["requests_total"]}',
        "",
        "# HELP facevoiceauth_auth_success_rate Authentication success rate",
        "# TYPE facevoiceauth_auth_success_rate gauge",
        f"facevoiceauth_auth_success_rate {success_rate}",
        "",
        "# HELP facevoiceauth_face_verify_latency_ms Average face verification latency",
        "# TYPE facevoiceauth_face_verify_latency_ms gauge",
        f"facevoiceauth_face_verify_latency_ms {round(avg_face_latency, 2)}",
        "",
        "# HELP facevoiceauth_voice_verify_latency_ms Average voice verification latency",
        "# TYPE facevoiceauth_voice_verify_latency_ms gauge",
        f"facevoiceauth_voice_verify_latency_ms {round(avg_voice_latency, 2)}",
        "",
        "# HELP facevoiceauth_voice_liveness_rejection_rate Voice liveness rejection rate",
        "# TYPE facevoiceauth_voice_liveness_rejection_rate gauge",
        f"facevoiceauth_voice_liveness_rejection_rate {voice_rejection_rate}",
        "",
    ]

    from starlette.responses import PlainTextResponse

    return PlainTextResponse("\n".join(lines), media_type="text/plain")
