import time
from fastapi import APIRouter
from app import state
from app.models import ResetRequest, BuyRequest, BuyResponse, StatusResponse
from app.metrics import tracker

router = APIRouter()


@router.post("/reset")
async def reset(body: ResetRequest):
    state.tickets_available = body.ticket_count
    state.tickets_sold.clear()
    state.idempotency.clear()
    state.next_ticket = 1
    state.start_time = time.time()
    return {"ok": True, "ticket_count": body.ticket_count}


@router.post("/buy", response_model=BuyResponse)
async def buy(body: BuyRequest):
    start = time.time()
    try:
        # Idempotency check (also racy — intentional)
        if body.request_id in state.idempotency:
            return BuyResponse(ticket=state.idempotency[body.request_id])

        if state.next_ticket > state.tickets_available:
            return BuyResponse(sold_out=True)

        # THE RACE: read-modify-write with no lock
        ticket_num = state.next_ticket
        state.next_ticket += 1
        state.tickets_sold[body.user_id] = ticket_num
        state.idempotency[body.request_id] = ticket_num
        return BuyResponse(ticket=ticket_num)
    finally:
        elapsed_ms = (time.time() - start) * 1000
        tracker.record(elapsed_ms)


@router.get("/status", response_model=StatusResponse)
async def status():
    return StatusResponse(
        sold=len(state.tickets_sold),
        tickets=dict(state.tickets_sold),
    )
