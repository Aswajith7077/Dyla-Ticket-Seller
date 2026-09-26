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


class TicketAssignment(BaseModel):
    ticket: int
    user_id: str


class StatusResponse(BaseModel):
    sold: int
    # A flat list, not a dict keyed by ticket or by user: a dict keyed by
    # user_id would silently overwrite a user's earlier ticket if they buy
    # more than once, and a dict keyed by ticket_num can't represent two
    # people racing to the same ticket number (exactly the bug this store
    # is supposed to demonstrate) since object/hash keys can't repeat.
    tickets: list[TicketAssignment]


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
