import time
from fastapi import APIRouter

router = APIRouter(prefix="/debug")

_slow_until: float = 0.0
_slow_delay_ms: float = 0.0


def get_slow_delay_ms() -> float:
    if time.time() < _slow_until:
        return _slow_delay_ms
    return 0.0


@router.post("/slow")
async def inject_slow(seconds: float = 10.0, delay_ms: float = 200.0):
    global _slow_until, _slow_delay_ms
    _slow_until = time.time() + seconds
    _slow_delay_ms = delay_ms
    return {
        "ok": True,
        "slow_until": _slow_until,
        "delay_ms": delay_ms,
        "message": f"Redis calls will be slowed by {delay_ms}ms for {seconds}s",
    }


@router.post("/slow/clear")
async def clear_slow():
    global _slow_until
    _slow_until = 0.0
    return {"ok": True, "message": "Slow injection cleared"}


@router.get("/slow/status")
async def slow_status():
    remaining = max(0.0, _slow_until - time.time())
    return {
        "active": remaining > 0,
        "remaining_seconds": round(remaining, 1),
        "delay_ms": _slow_delay_ms if remaining > 0 else 0,
    }
