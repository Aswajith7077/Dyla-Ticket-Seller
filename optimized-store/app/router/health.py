import os
import time
from fastapi import APIRouter
from app.state import get_redis, start_time
from app.models import HealthResponse, MetricsResponse
from app.metrics import tracker

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    try:
        r = await get_redis()
        await r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return HealthResponse(
        status="ok",
        uptime=round(time.time() - start_time, 2),
        redis_ok=redis_ok,
        service="optimized",
        instance_id=os.getenv("INSTANCE_ID", "standalone"),
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
