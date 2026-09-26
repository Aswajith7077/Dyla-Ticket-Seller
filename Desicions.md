# Architecture Decision Record — Ticket Load Tester

**Author:** Aswajith S  
**Date:** 2026-09-26  
**Status:** Final


**Note:** The content is modified by the LLM to achieve a formatted version of the decisions.

---

## Context

The problem: sell exactly N tickets to 50,000 concurrent buyers within 60 seconds. Four invariants must hold under any load — no oversell, no duplicate ticket numbers, idempotent request IDs, and a /status count that always matches reality.

The submission requires two implementations: a naive one that breaks, and a fixed one that holds. The comparison must be demonstrable — a load client that catches the naive version failing is the deliverable, not an assertion that it would fail.

---

## Decision 1 — Language and Framework: Python + FastAPI

### What I considered

| Option | Why considered | Why rejected |
|---|---|---|
| Go + net/http | Native goroutines, no GIL, excellent concurrency story | Goroutines make the naive race harder to demonstrate naturally — you'd need explicit mutex removal which feels contrived |
| Node.js + Express | Single-threaded event loop, async-native | The race condition in naive is less dramatic; V8 event loop serialises JS, so you need worker threads to break it |
| Java + Spring Boot | Thread-per-request, race is obvious without tricks | Too much boilerplate for a hackathon, JVM startup weight |
| **Python + FastAPI** | **Chosen** | See below |

### Why FastAPI

**The naive race is real and teachable.** Python's asyncio is single-threaded, but inserting `await asyncio.sleep(0)` inside the read-modify-write in `/buy` yields the event loop between the read and the write. This makes the TOCTOU race visible under concurrent load without anything artificial — it mirrors exactly how production async code breaks when developers forget that `await` is a preemption point.

Running naive with `--workers 4` breaks the GIL boundary entirely, making races even more pronounced. The failure mode is instructive, not just a number.

**FastAPI specifics:**
- `async def` endpoints + uvicorn ASGI server handle concurrent connections without threads
- Pydantic models give typed request/response validation for free
- Auto-generated OpenAPI docs at `/docs` — useful during the demo
- `asynccontextmanager` lifespan hook for Redis warmup and background task management
- No boilerplate: three endpoints fit in ~50 lines each

**What FastAPI does not give you:** it does not solve the concurrency problem. That is Redis's job. FastAPI is the HTTP layer only.

---

## Decision 2 — Datastore: Redis (optimized) vs In-Memory Dict (naive)

### Naive store — intentional absence of a datastore

The naive implementation uses a Python module-level dict and an integer counter. No database, no ORM, no lock.

This is the correct choice for naive because:
- The race condition is in the application layer, not the storage layer
- Adding a database would obscure where the bug actually lives
- SQLite with serialised writes would accidentally fix the bug (SQLite's default WAL mode serialises writes)
- The failure must be visible and attributable

### Why not SQLModel / SQLite for naive

SQLite in WAL mode serialises concurrent writes at the DB level. A naive implementation backed by SQLite would accidentally pass the no-oversell invariant because the DB does the locking for you. The point of naive is to show what happens when you trust application-level read-modify-write without a lock. A dict makes that explicit.

### Why not Supabase / PostgreSQL

Supabase is appropriate for persistent user data and auth. Ticket state in this problem is ephemeral — it resets between runs. A full Postgres stack adds:
- Network round-trip latency that obscures whether latency comes from the application or the DB
- Schema migrations, connection pooling configuration, and auth that are irrelevant to the concurrency problem
- A dependency on an external service that may not be available in a demo environment

PostgreSQL with `SELECT FOR UPDATE` or `advisory locks` would also solve the problem, but the solution would be less legible than a Lua script, and the bottleneck analysis would be harder because Postgres's lock contention is opaque without additional tooling.

### Why Redis for optimized

Redis was chosen for three properties:

**1. Atomic Lua scripts**

Redis executes Lua scripts atomically — no other command runs on the server while a script is executing. The `/buy` script does in one round-trip what would require a transaction + lock in SQL:

```lua
-- Check idempotency
-- Atomically increment counter
-- Check against max
-- Assign ticket
-- Set TTL on reservation
```

This is not a workaround. Redis's Lua atomicity is a documented, first-class guarantee. It is the correct tool for a counter that must never be double-incremented.

**2. Single-instance and multi-instance correctness are the same code**

The Lua script runs on the Redis server, not on the application server. Whether one FastAPI instance calls it or three instances behind nginx call it simultaneously, the script executes serially on Redis. The three-instance cluster passes all four invariants with zero changes to application logic — the Lua script is the lock.

This is the core architectural insight: move the critical section to the datastore layer where atomicity is a primitive, not to the application layer where you have to engineer it.

**3. TTL-native reservation expiry**

The waitlist state machine requires reservations that expire after 30 seconds. Redis TTLs are a primitive — `EXPIRE ticket:state:{n} 30` — with no background job required to clean up. The background sweep only needs to handle the reallocation, not the detection of expiry.

---

## Decision 3 — Three-Instance Architecture: nginx + Redis Lua vs Application-Level Lock

### The wrong approach

A common failure mode for the multi-instance requirement is to add a distributed lock (Redlock, etc.) at the application layer:

```python
async with redis_lock("ticket:buy:lock"):
    ticket_num = await r.incr("ticket:counter")
    if ticket_num > max:
        ...
```

This works but:
- Introduces lock contention — all three instances queue on a single lock
- Adds failure modes (lock holder crashes, TTL misconfiguration)
- Throughput is limited by lock acquisition rate, not by Redis's actual command throughput
- Redlock's correctness under network partition is contested (Lamport, Martin Kleppmann's analysis)

### The correct approach

The Lua script is already the lock. Redis processes commands sequentially. `INCR` is atomic. The script wraps the entire buy logic in a single atomic operation. There is nothing to additionally lock.

The three-instance setup is:
```
nginx (least_conn) → [instance-1, instance-2, instance-3] → Redis
```

All three instances share one Redis. All three call the same Lua script. Redis serialises the calls. Invariants hold.

This is a different problem from the single-instance version only in that you must prove it — hence the `X-Served-By` header from nginx showing which instance handled each request, and the per-instance distribution chart in the frontend.

---

## Decision 4 — Load Client: Python CLI (multiprocess) vs Browser (fetch)

### Why the browser load runner is not sufficient

The frontend load runner fires requests using `fetch()` from a browser tab. Browser limitations:

- HTTP/1.1 connection limit: 6 concurrent connections per origin (Chrome, Firefox)
- Even with HTTP/2, the browser's networking stack is not designed for bulk load generation
- A concurrency slider showing 500 means 500 queued promises, not 500 simultaneous TCP connections
- Measurements from a browser include browser-side scheduling jitter

The spec explicitly asks to prove throughput numbers are not limited by the client. You cannot prove this from a browser tab.

### Why multiprocess Python CLI

`aiohttp` + `uvloop` + `multiprocessing`:

- `uvloop` replaces asyncio's default event loop with a libuv-based implementation — roughly 2–4× faster for I/O-bound workloads
- Each worker process has its own event loop and connection pool — no GIL contention between workers
- `TCPConnector(limit=concurrency)` sets an explicit per-process connection pool size
- The per-worker breakdown table in the output shows that all workers are contributing roughly equally — if one worker is doing all the work, the client is the bottleneck

**Proof of client non-bottleneck:** if adding workers increases aggregate RPS proportionally (2 workers → 2× RPS, 4 workers → 4× RPS), the seller is the ceiling, not the client. When adding workers stops increasing RPS linearly, you've found the seller's ceiling.

---

## Decision 5 — Waitlist: Redis State Machine vs Application Queue

### What was not done

An in-memory asyncio queue (`asyncio.Queue`) would work on a single instance but:
- Does not survive a process restart
- Does not work across the three-instance cluster (each instance has its own queue)
- Loses waitlist state if the instance handling the queue dies

### What was done

The waitlist lives entirely in Redis as a `LIST`. Enqueue is `RPUSH`, dequeue is `LPOP`, both atomic. The state machine transitions happen inside the Lua scripts.

The state machine:
```
AVAILABLE
    ↓  (INCR succeeds)
RESERVED  ← Redis key with 30s TTL
    ↓  (POST /confirm within 30s)      ↓  (TTL expires)
CONFIRMED                           AVAILABLE (returned to pool)
                                         ↓
                                    next waitlist member → RESERVED
```

The race condition most implementations introduce here: checking if a reservation has expired and re-assigning it in two separate Redis calls. Between the check and the reassign, another instance could do the same check and also try to reassign. The expiry sweep Lua script handles the entire transition atomically — check, reclaim, reassign, notify — in one script execution.

---

## What Was Not Implemented and Why

### Persistent storage across restarts

The spec does not require this for the core problem. Redis is configured without AOF/RDB persistence — state is intentionally ephemeral between `/reset` calls. The "kill the datastore" take-it-further extension would require enabling Redis persistence and adding retry logic in the FastAPI clients. This was scoped out for time.

### Distributed load client across separate machines

The multiprocess CLI runs on one machine. True distributed load (across multiple machines) would require a coordinator and result aggregation over the network. For a hackathon demo, four processes on one machine generating 10,000+ RPS is sufficient to show the seller is the ceiling, not the client.

### JWT / token-based ticket confirmation

The `/confirm` endpoint currently trusts `request_id` as the confirmation token. In production this would be a signed JWT issued at reservation time. For this problem scope, the request_id is sufficient.

---

## Summary

| Layer | Choice | Core reason |
|---|---|---|
| HTTP framework | FastAPI | Async-native, minimal boilerplate, instructive race condition |
| Naive datastore | In-memory dict, no lock | Race must be visible and attributable to application code |
| Optimized datastore | Redis | Lua atomicity is the correct primitive for this problem |
| Multi-instance correctness | Redis Lua (no app lock) | The script runs on Redis; instances are irrelevant to correctness |
| Reservation expiry | Redis TTL + sweep script | TTLs are a Redis primitive; expiry detection is free |
| Load client | aiohttp + uvloop + multiprocessing | Proves seller is the bottleneck, not the client |
| Frontend | Next.js + shadcn + recharts | Constraint from project brief; covers visualization and PDF export |
| Auth | NextAuth.js + Google OAuth | Minimal setup, no custom auth infrastructure needed |