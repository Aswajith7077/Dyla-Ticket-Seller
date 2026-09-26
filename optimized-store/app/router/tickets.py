import time
from fastapi import APIRouter
from app.state import get_redis
from app.models import ResetRequest, BuyRequest, BuyResponse, StatusResponse
from app.metrics import tracker

router = APIRouter()

BUY_SCRIPT = """
local idem_key = 'idem:' .. KEYS[1]
local existing = redis.call('GET', idem_key)
if existing then
  return {1, tonumber(existing)}
end

local ticket_num = redis.call('INCR', 'ticket:counter')
local max_tickets = tonumber(redis.call('GET', 'ticket:max'))

if ticket_num > max_tickets then
  redis.call('DECR', 'ticket:counter')
  return {0, 0}
end

redis.call('SET', idem_key, ticket_num)
redis.call('HSET', 'ticket:assignments', ARGV[1], ticket_num)
return {1, ticket_num}
"""


@router.post("/reset")
async def reset(body: ResetRequest):
    r = await get_redis()
    pipe = r.pipeline()
    pipe.flushdb()
    pipe.set("ticket:max", body.ticket_count)
    pipe.set("ticket:counter", 0)
    await pipe.execute()
    return {"ok": True, "ticket_count": body.ticket_count}


@router.post("/buy", response_model=BuyResponse)
async def buy(body: BuyRequest):
    start = time.time()
    try:
        r = await get_redis()
        result = await r.eval(BUY_SCRIPT, 1, body.request_id, body.user_id)
        issued, ticket_num = result
        if issued:
            return BuyResponse(ticket=int(ticket_num))
        return BuyResponse(sold_out=True)
    except Exception:
        tracker.record((time.time() - start) * 1000, is_error=True)
        raise
    finally:
        tracker.record((time.time() - start) * 1000)


@router.get("/status", response_model=StatusResponse)
async def status():
    r = await get_redis()
    assignments = await r.hgetall("ticket:assignments")
    return StatusResponse(
        sold=len(assignments),
        tickets={uid: int(tnum) for uid, tnum in assignments.items()},
    )
