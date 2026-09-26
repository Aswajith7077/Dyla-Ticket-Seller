# Ticket Load Tester

A demo comparing two ticket-selling backends under concurrent load — one with an
intentional race condition, one built to be correct — plus a dashboard for
watching them live and running load tests against them, a standalone CLI load
generator, and a 3-instance cluster behind an nginx load balancer to prove
correctness holds with no application-level lock.

## Architecture

| Service                             | Port | Storage                | Concurrency behavior                                                                             |
| ------------------------------------ | ---- | ----------------------- | -------------------------------------------------------------------------------------------------- |
| `naive-store`                        | 8001 | In-memory Python list  | No locking — read-modify-write race on ticket issuance. Resets on restart.                        |
| `optimized-store`                    | 8002 | Redis                  | Atomic Lua script for ticket issuance + idempotency + waitlist. Resets on restart.                |
| `optimized-store-1/2/3` (via `nginx`) | 8003 | Same Redis as above    | Three replicas of `optimized-store` sharing one Redis, behind nginx (`least_conn`). Correctness comes from Redis atomicity, not app-level locking. |
| `frontend`                           | 3000 | None (client only)     | Next.js dashboard — health/metrics view + load-test runner + PDF export.                          |
| `load-client`                        | —    | None                   | Standalone multi-process Python CLI that load-tests any of the above, to prove throughput isn't limited by the browser-based load runner. |

Both `naive-store` and `optimized-store` expose the same core API:

- `POST /reset` — `{ ticket_count }`, resets available tickets and clears state
- `POST /buy` — `{ user_id, request_id }`, returns `{ ticket }` or `{ sold_out: true }` (naive) / `{ waitlisted: true, position }` (optimized, once sold out). Duplicate `request_id`s are idempotent (return the same ticket).
- `GET /status` — `{ sold, tickets: [{ ticket, user_id }, ...] }` — a flat list, not a dict, so it correctly shows a user holding more than one ticket and two requests that raced to the same ticket number (rather than either case silently overwriting the other).
- `GET /health` — `{ status, uptime, redis_ok, service, instance_id }`
- `GET /metrics` — `{ rps, p50_ms, p99_ms, total_requests, errors }`

`optimized-store` only, on top of the above:

- `POST /confirm` — `{ request_id }`, promotes a `RESERVED` ticket to `CONFIRMED` (clears its 30s expiry). Returns `{ expired: true }` if the reservation already timed out.
- `GET /waitlist?user_id=` — `{ position, queue_length, estimated_wait_seconds }` for a queued buyer.
- `POST /debug/slow?seconds=&delay_ms=`, `POST /debug/slow/clear`, `GET /debug/slow/status` — inject/clear artificial latency on every Redis call, to see how the system behaves when the datastore lags mid-sale.

### The waitlist

Once tickets sell out, `optimized-store` doesn't return `sold_out` — it queues the buyer instead. A ticket that's `RESERVED` but not `CONFIRMED` within 30 seconds is reclaimed by a background sweep (runs every 5s, see `main.py`) and handed to the next person in the queue. `naive-store` has no waitlist — it stays deliberately minimal so the race demo isn't muddied by extra state.

### The cluster

`optimized-store-1/2/3` are three instances of the exact same image, distinguished only by an `INSTANCE_ID` env var (shown in `/health` and the dashboard panel), sitting behind nginx on port 8003. All three share the same Redis, so there's no cross-instance coordination in the application code at all — the Lua script's atomicity is what holds the invariants, which is the whole point of the exercise.

The frontend never talks to any of these through Next.js API routes — it calls
the FastAPI services directly from the browser (see `NEXT_PUBLIC_NAIVE_URL` /
`NEXT_PUBLIC_OPTIMIZED_URL` / `NEXT_PUBLIC_CLUSTER_URL`).

Google OAuth (NextAuth) is wired up but currently **disabled** — there is no
route guard, so the dashboard (`/`) and load-test page (`/load`) are reachable
without signing in. Re-enable by adding a proxy that checks `getToken()` from
`next-auth/jwt` (see `frontend/src/app/api/auth/[...nextauth]/route.ts` for the
existing NextAuth config).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) for the Python services
- [`pnpm`](https://pnpm.io/) for the frontend
- Redis (only needed for `optimized-store` and the cluster)
- Docker Desktop + Docker Compose (optional, for running everything together — must actually be **running**, not just installed, before `docker compose up` will connect)

## Running locally (no Docker)

Four terminals:

```bash
# 1. naive-store — no external dependencies
cd naive-store
uv run uvicorn main:app --reload --port 8001

# 2. optimized-store — needs Redis reachable at REDIS_URL (optimized-store/.env)
redis-server &   # or: docker run -d -p 6379:6379 redis:7-alpine
cd optimized-store
uv run uvicorn main:app --reload --port 8002

# 3. frontend
cd frontend
pnpm install
pnpm dev

# 4. (optional) CLI load client, once the above are up
cd load-client
uv run main.py --target http://localhost:8002 --tickets 100 --requests 5000 --concurrency 100 --workers 4
```

Open `http://localhost:3000`.

## Running with Docker Compose

```bash
docker compose up
```

This pulls the pre-built images from GHCR (`ghcr.io/aswajith7077/dyla-ticket-seller-*:latest`, all public) and starts Redis, both single-instance stores, the 3-replica cluster behind nginx, and the frontend. Pass `--build` to build from local source instead of pulling (useful while developing):

```bash
docker compose up --build
```

Redis is published on host port **6380** (not 6379) to avoid colliding with a system-level Redis service if you have one running — container-to-container traffic (`optimized-store` → `redis:6379`) is on the internal Docker network and unaffected by this.

To run the CLI load client against the compose stack (it doesn't start automatically — it's in the `tools` profile):

```bash
docker compose run load-client
docker compose run load-client --target http://localhost:8001                         # naive
docker compose run load-client --target http://localhost:8003 --workers 8             # cluster
```

If `docker compose up` fails with `error from registry: denied` even though the images are public, you likely have a stale/incorrect saved login for `ghcr.io` — run `docker logout ghcr.io` and try again.

### Root `.env` (for `docker compose`)

```
NEXTAUTH_SECRET=<openssl rand -base64 32>
GOOGLE_CLIENT_ID=<your Google OAuth client id>
GOOGLE_CLIENT_SECRET=<your Google OAuth client secret>
```

These are only consumed if you re-enable auth — the app runs fine with
placeholder values while auth is disabled.

## Environment files

| File                       | Purpose                                                         |
| --------------------------- | ---------------------------------------------------------------- |
| `naive-store/.env`          | `PORT` (default 8001)                                            |
| `optimized-store/.env`      | `PORT` (default 8002), `REDIS_URL`, `REDIS_MAX_CONNECTIONS` (default 500), `INSTANCE_ID` (cluster only) |
| `frontend/.env.local`       | `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `GOOGLE_CLIENT_ID/SECRET`, `NEXT_PUBLIC_NAIVE_URL`, `NEXT_PUBLIC_OPTIMIZED_URL`, `NEXT_PUBLIC_CLUSTER_URL` |
| `.env` (repo root)          | Same NextAuth/Google values, read by `docker-compose.yml`        |

The GitHub Actions build (`.github/workflows/docker-publish.yml`) bakes
`NEXT_PUBLIC_NAIVE_URL` / `NEXT_PUBLIC_OPTIMIZED_URL` / `NEXT_PUBLIC_CLUSTER_URL`
into the published frontend image from repo **variables** (not secrets) of the
same name, falling back to `http://localhost:800{1,2,3}` if unset — since these
are `NEXT_PUBLIC_*` values, they're compiled into the browser bundle at build
time and can't be changed by setting env vars on the running container afterward.

## Repo layout

```
naive-store/        FastAPI, in-memory racy ticket store
optimized-store/     FastAPI + Redis, atomic ticket store + waitlist
load-client/         Standalone multi-process Python CLI load generator
nginx/               nginx.conf for the 3-replica optimized-store cluster
frontend/            Next.js dashboard + load-test runner
problem-statement/   The original take-home brief
docker-compose.yml   Redis + both stores + the cluster + frontend + load-client
```

## Frontend pages

- `/` — **Health Check**: live `/health` + `/metrics` panels for naive, optimized, and the cluster.
- `/load` — **Load Test**: configure and run a load test against Naive, Optimized, Both, or Cluster, with chaos controls (inject/clear artificial Redis delay) and a per-instance load-distribution chart in cluster mode.

## Load testing

The `/load` page lets you configure ticket count, concurrency, total
requests, duplicate-request ratio, and user pool size, then fires requests
directly from the browser at the selected target. After a run it checks four
invariants against `/status` (no oversell, no duplicate ticket numbers,
idempotency held under duplicate `request_id`s, and that `/status.sold`
matches the tickets returned) and lets you export the results as a PDF.

The standalone `load-client/` CLI runs the same kind of test from multiple
OS processes instead of one browser tab, to prove the numbers aren't
capped by the browser's own connection limits.
