from pydantic import BaseModel
from typing import Optional


class ResetRequest(BaseModel):
    ticket_count: int


class BuyRequest(BaseModel):
    user_id: str
    request_id: str


class BuyResponse(BaseModel):
    ticket: Optional[int] = None
    sold_out: Optional[bool] = None


class StatusResponse(BaseModel):
    sold: int
    tickets: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    uptime: float
    redis_ok: bool
    service: str


class MetricsResponse(BaseModel):
    rps: float
    p50_ms: float
    p99_ms: float
    total_requests: int
    errors: int
