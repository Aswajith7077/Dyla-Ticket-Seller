import asyncio
import time
from fastapi import APIRouter
from app import state
from app.models import ResetRequest, BuyRequest, BuyResponse, StatusResponse, TicketAssignment
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
        # Idempotency check — racy together with the section below: two
        # concurrent requests sharing a request_id can both pass this
        # check before either writes to state.idempotency, so both go on
        # to issue their own ticket number instead of sharing one.
        if body.request_id in state.idempotency:
            return BuyResponse(ticket=state.idempotency[body.request_id])

        if state.next_ticket > state.tickets_available:
            return BuyResponse(sold_out=True)

        # THE RACE: read-modify-write with no lock. The await below yields
        # the event loop between the read and the write, so a concurrent
        # request's coroutine can run in the gap and read the same
        # state.next_ticket before this one writes it back — a genuine
        # TOCTOU race under asyncio's single-threaded concurrency.
        ticket_num = state.next_ticket
        await asyncio.sleep(0)
        state.next_ticket = ticket_num + 1
        state.tickets_sold.append((ticket_num, body.user_id))
        state.idempotency[body.request_id] = ticket_num
        return BuyResponse(ticket=ticket_num)
    finally:
        elapsed_ms = (time.time() - start) * 1000
        tracker.record(elapsed_ms)


@router.get("/status", response_model=StatusResponse)
async def status():
    return StatusResponse(
        sold=len(state.tickets_sold),
        tickets=[TicketAssignment(ticket=t, user_id=u) for t, u in state.tickets_sold],
    )
