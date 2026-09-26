Checked the actual problem statement (problem-statement/dyla_take_home_problems.md.pdf — Problem 1, Ticket Stampede) against the code, and ran two live tests rather than trust assumptions. Two real findings, plus gaps in the earlier pasted assessment.

Verified by testing, not in the earlier list

1. The naive store's race doesn't actually fire. /buy has zero await between reading and writing state.next_ticket — under asyncio's single-threaded event loop, nothing can preempt a coroutine mid-execution without a yield point. I reset it to 100 tickets and fired 500 concurrent requests via asyncio.gather: exactly 100 sold, 0 duplicates, 0 oversell. The demo's core narrative — "write naive first, show the buyer catching it overselling" — currently has no failing run to show, because it can't fail as written. Fix is small: insert await asyncio.sleep(0) between the read and the write in naive-store/app/router/tickets.py to force a real interleaving point.

2. /status silently loses tickets — in the optimized store too. Both stores key their assignment map by user_id, not by ticket or request. I bought twice for the same user_id with two different (non-duplicate) request_ids against optimized-store: both succeeded, issuing real tickets #1 and #2 — but /status came back {"sold":1,"tickets":{"sameuser":2}}. Ticket #1 is gone from /status forever, even though it was legitimately issued and can never be reissued. This is a direct, deterministic violation of the spec's own 4th invariant ("the count reported by /status always matches the tickets actually issued") — not a race, a data-model bug, so it's 100% reproducible. It matters more than it might look: your own load generator (userPoolSize: 200 against totalRequests: 5000) guarantees this triggers on basically every run you've done. Worse, the frontend's "Count Matches" invariant check can never catch it — it compares status.sold to Object.values(status.tickets).length, both derived from the same corrupted response, so it's tautological. It should instead compare against the buyer's own count of successful /buy responses.

Corrections to the pasted list

- "GET /metrics is fake / deque has no time-based eviction" — checked metrics.py: rps() already filters timestamps by now - t <= 1.0. This claim is stale/wrong as written.
- "Naive redis_ok hardcoded false" — confirmed accurate, still true.
- "Race not dramatic enough" — confirmed, and it's worse than "not dramatic":  above).

Bigger gap: the submission itself doesn't meet the spec's ground rules yet

These apply regardless of which take-home problem, and the spec is explicit th

- No /logs directory. "You must submit your session logs... A submission withou do have .claude/sessions/*.md already (good instinct), but they're in the
  wrong place and incomplete — today's debugging session (exactly the kind of aterial they want) isn't exported yet.
- No DECISIONS.md. Required, ≤2 pages: architecture chosen/rejected, trade-offwhat's next.
- Repo is public, spec asks for a private repo shared with them.
- Not implemented from "what we want to see": slow-datastore-for-10s injection, and an explained (not just measured) bottleneck diagnosis.

Where I'd spend time next (your call, but here's the ordering I'd argue for)

1. Fix bug #2 first — it's small, it's a genuine invariant violation in the store meant to be correct, and writing it up honestly in DECISIONS.md ("obvious approach, keyed assignments by user, verified it drops tickets, replaced with...") is exactly the kind of ic rewards.
2. Fix bug #1 (asyncio.sleep(0)) — needed so the failing/passing run pair in your write-up is real.
3. /logs + DECISIONS.md + flip repo private — these are pass/fail gate items, no partial credit.
4. Pick one "take it further" item. Given you already have Redis + Lua in place, the waitlist state machine (30s reservation → expiry → next-in-queue) is the more interesting one and directly touches the same assignment-model bug you'll have just fixed — but the 3-instance-behind-LB option is nearly free since the Lua script already gives you cross-instance
   atomicity. Want me to sketch what either would take?