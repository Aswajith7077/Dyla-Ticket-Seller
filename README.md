# Ticket Load Tester

A demo comparing two ticket-selling backends under concurrent load — one with an
intentional race condition, one built to be correct — plus a dashboard for
watching them live and running load tests against them.

## Architecture

| Service           | Port | Storage                    | Concurrency behavior                                                      |
| ----------------- | ---- | -------------------------- | --------------------------------------------------------------------------- |
| `naive-store`     | 8001 | In-memory Python dict      | No locking — read-modify-write race on ticket issuance. Resets on restart. |
| `optimized-store` | 8002 | Redis                      | Atomic Lua script for ticket issuance + idempotency. Resets on restart.    |
| `frontend`        | 3000 | None (client only)         | Next.js dashboard — health/metrics view + load-test runner + PDF export.   |

Both stores expose the same API:

- `POST /reset` — `{ ticket_count }`, resets available tickets and clears state
- `POST /buy` — `{ user_id, request_id }`, returns `{ ticket }` or `{ sold_out: true }`. Duplicate `request_id`s are idempotent (return the same ticket).
- `GET /status` — `{ sold, tickets }`
- `GET /health` — `{ status, uptime, redis_ok, service }`
- `GET /metrics` — `{ rps, p50_ms, p99_ms, total_requests, errors }`

The frontend never talks to these through Next.js API routes — it calls both
FastAPI services directly from the browser (see `NEXT_PUBLIC_NAIVE_URL` /
`NEXT_PUBLIC_OPTIMIZED_URL`).

Google OAuth (NextAuth) is wired up but currently **disabled** — there is no
`src/proxy.ts` route guard, so the dashboard and load-test pages are reachable
without signing in. Re-enable by adding back a proxy that checks
`getToken()` from `next-auth/jwt` (see `frontend/src/app/api/auth/[...nextauth]/route.ts`
for the existing NextAuth config).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) for the Python services
- [`pnpm`](https://pnpm.io/) for the frontend
- Redis (only needed for `optimized-store`)
- Docker + Docker Compose (optional, for running everything together)

## Running locally (no Docker)

Three terminals:

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
```

Open `http://localhost:3000`.

## Running with Docker Compose

```bash
# fill in the real values in .env at repo root first (see below)
docker compose up --build
```

This starts Redis, both stores, and the frontend in order (stores wait on
Redis's healthcheck; the frontend waits on both stores starting).

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
| `optimized-store/.env`      | `PORT` (default 8002), `REDIS_URL`                                |
| `frontend/.env.local`       | `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `GOOGLE_CLIENT_ID/SECRET`, `NEXT_PUBLIC_NAIVE_URL`, `NEXT_PUBLIC_OPTIMIZED_URL` |
| `.env` (repo root)          | Same NextAuth/Google values, read by `docker-compose.yml`        |

## Repo layout

```
naive-store/       FastAPI, in-memory racy ticket store
optimized-store/    FastAPI + Redis, atomic ticket store
frontend/           Next.js dashboard + load-test runner
docker-compose.yml  Redis + all three services
```

## Load testing

The `/load` page lets you configure ticket count, concurrency, total
requests, duplicate-request ratio, and user pool size, then fires requests
directly from the browser at either store. After a run it checks four
invariants against `/status` (no oversell, no duplicate ticket numbers,
idempotency held under duplicate `request_id`s, and that `/status.sold`
matches the tickets returned) and lets you export the results as a PDF.
