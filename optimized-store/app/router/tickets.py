import asyncio
import time
from fastapi import APIRouter
from app.state import get_redis
from app.models import ResetRequest, BuyRequest, BuyResponse, ConfirmRequest, StatusResponse, TicketAssignment
from app.metrics import tracker
from app.router.debug import get_slow_delay_ms

router = APIRouter()

RESERVATION_TTL_SECONDS = 30

# KEYS[1] = request_id
# ARGV[1] = user_id
# ARGV[2] = reservation_ttl_seconds
#
# max_tickets is read from the 'ticket:max' key set by /reset, not passed
# as an argument — /buy's request body only carries user_id/request_id,
# it has no ticket_count to hand the script.
BUY_SCRIPT = """
local idem_key = 'idem:' .. KEYS[1]
local existing = redis.call('GET', idem_key)
if existing then
  local state = redis.call('GET', 'ticket:state:' .. existing)
  return {2, tonumber(existing), state or 'CONFIRMED'}
end

local max_tickets = tonumber(redis.call('GET', 'ticket:max'))

-- Prefer reusing a ticket number the expiry sweep released (an expired,
-- unconfirmed reservation with nobody on the waitlist to hand it to)
-- over minting a brand new one. This keeps ticket_num a true 1..max_tickets
-- range even after waitlist churn — see EXPIRY_SWEEP_SCRIPT for why we
-- can't just DECR/INCR ticket:counter to "return" an arbitrary ticket.
local ticket_num = redis.call('SPOP', 'ticket:released')

if not ticket_num then
  local next_num = redis.call('INCR', 'ticket:counter')
  if next_num > max_tickets then
    -- No tickets available. Add to waitlist if not already there.
    redis.call('DECR', 'ticket:counter')
    local already_waiting = redis.call('GET', 'waitlist:member:' .. ARGV[1])
    if not already_waiting then
      redis.call('RPUSH', 'waitlist', ARGV[1] .. ':' .. KEYS[1])
      redis.call('SET', 'waitlist:member:' .. ARGV[1], '1')
    end
    local position = redis.call('LLEN', 'waitlist')
    return {0, position, 0}
  end
  ticket_num = next_num
else
  ticket_num = tonumber(ticket_num)
end

-- Reserve the ticket. Assignments are keyed by request_id (not by
-- ticket_num or user_id) so a user buying more than once never overwrites
-- an earlier ticket, and two requests that raced to the same ticket_num
-- (a bug we want visible, not hidden) both still show up in /status.
redis.call('SET', idem_key, ticket_num)
redis.call('HSET', 'ticket:assignments', KEYS[1], ticket_num .. ':' .. ARGV[1])
redis.call('SET', 'ticket:state:' .. ticket_num, 'RESERVED')
redis.call('EXPIRE', 'ticket:state:' .. ticket_num, tonumber(ARGV[2]))
redis.call('SET', 'ticket:reservation:' .. KEYS[1], ticket_num)
redis.call('EXPIRE', 'ticket:reservation:' .. KEYS[1], tonumber(ARGV[2]))
return {1, ticket_num, 'RESERVED'}
"""

# Runs every 5s (see main.py's process_expirations). Scans current
# assignments for tickets whose RESERVED state key has expired (30s TTL,
# no /confirm call) and hands each one to the next waitlist entry.
EXPIRY_SWEEP_SCRIPT = """
local assignments = redis.call('HGETALL', 'ticket:assignments')
local reclaimed = 0

for i = 1, #assignments, 2 do
  local req_id = assignments[i]
  local value = assignments[i + 1]
  local colon = string.find(value, ':')
  local ticket_num = string.sub(value, 1, colon - 1)
  local state = redis.call('GET', 'ticket:state:' .. ticket_num)

  if not state then
    -- State key expired = reservation timed out. Drop the assignment.
    redis.call('HDEL', 'ticket:assignments', req_id)

    local next_entry = redis.call('LPOP', 'waitlist')
    if next_entry then
      local ncolon = string.find(next_entry, ':')
      local next_user = string.sub(next_entry, 1, ncolon - 1)
      local next_req = string.sub(next_entry, ncolon + 1)

      -- Hand this exact ticket number to the next waitlister — do not
      -- touch ticket:counter. DECR-then-INCR to "return" a ticket only
      -- gives back the correct number if it's the most-recently-issued
      -- one; reclaiming an earlier ticket while later ones are still
      -- held would hand this slot a number that's already assigned to
      -- someone else (verified: this was the actual cause of duplicate
      -- ticket numbers showing up in /status).
      redis.call('HSET', 'ticket:assignments', next_req, ticket_num .. ':' .. next_user)
      redis.call('SET', 'ticket:state:' .. ticket_num, 'RESERVED')
      redis.call('EXPIRE', 'ticket:state:' .. ticket_num, 30)
      redis.call('SET', 'ticket:reservation:' .. next_req, ticket_num)
      redis.call('EXPIRE', 'ticket:reservation:' .. next_req, 30)
      redis.call('SET', 'idem:' .. next_req, ticket_num)
      redis.call('DEL', 'waitlist:member:' .. next_user)
      reclaimed = reclaimed + 1
    else
      -- Nobody waiting: release the number back to the pool for a future
      -- brand-new buyer, instead of touching the sequential counter.
      redis.call('SADD', 'ticket:released', ticket_num)
    end
  end
end

return reclaimed
"""


async def run_expiry_sweep(r) -> int:
    return await r.eval(EXPIRY_SWEEP_SCRIPT, 0)


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
        delay = get_slow_delay_ms()
        if delay > 0:
            await asyncio.sleep(delay / 1000.0)
        r = await get_redis()
        code, num, state = await r.eval(
            BUY_SCRIPT, 1, body.request_id, body.user_id, RESERVATION_TTL_SECONDS
        )
        if code == 1 or code == 2:
            return BuyResponse(ticket=int(num), status=state)
        # code == 0: sold out for now, added to (or already on) the waitlist
        return BuyResponse(waitlisted=True, position=int(num))
    except Exception:
        tracker.record((time.time() - start) * 1000, is_error=True)
        raise
    finally:
        tracker.record((time.time() - start) * 1000)


@router.post("/confirm")
async def confirm(body: ConfirmRequest):
    r = await get_redis()
    reservation_key = f"ticket:reservation:{body.request_id}"
    ticket_num = await r.get(reservation_key)

    if not ticket_num:
        return {"expired": True}

    pipe = r.pipeline()
    pipe.set(f"ticket:state:{ticket_num}", "CONFIRMED")
    pipe.persist(f"ticket:state:{ticket_num}")  # remove the 30s TTL
    pipe.persist(reservation_key)
    await pipe.execute()

    return {"confirmed": True, "ticket": int(ticket_num)}


@router.get("/waitlist")
async def waitlist(user_id: str):
    r = await get_redis()
    entries = await r.lrange("waitlist", 0, -1)
    position = None
    for idx, entry in enumerate(entries, start=1):
        if entry.split(":", 1)[0] == user_id:
            position = idx
            break
    queue_length = len(entries)
    if position is None:
        return {"position": None, "queue_length": queue_length, "estimated_wait_seconds": None}
    return {
        "position": position,
        "queue_length": queue_length,
        "estimated_wait_seconds": position * RESERVATION_TTL_SECONDS,
    }


@router.get("/status", response_model=StatusResponse)
async def status():
    r = await get_redis()
    assignments = await r.hgetall("ticket:assignments")
    tickets = []
    for value in assignments.values():
        ticket_str, user_id = value.split(":", 1)
        tickets.append(TicketAssignment(ticket=int(ticket_str), user_id=user_id))
    return StatusResponse(sold=len(tickets), tickets=tickets)
