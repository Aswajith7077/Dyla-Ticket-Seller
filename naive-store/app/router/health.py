import time
from fastapi import APIRouter
from app import state
from app.models import HealthResponse, MetricsResponse
from app.metrics import tracker

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        uptime=round(time.time() - state.start_time, 2),
        redis_ok=False,
        service="naive",
    )


@router.get("/metrics", response_model=MetricsResponse)
async def metrics():
    return MetricsResponse(
        rps=round(tracker.rps(), 2),
        p50_ms=round(tracker.percentile(50), 2),
        p99_ms=round(tracker.percentile(99), 2),
        total_requests=tracker.total_requests,
        errors=tracker.errors,
    )
