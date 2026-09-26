import time

tickets_available: int = 0
# Append-only list of (ticket_number, user_id), one entry per genuinely new
# issuance — never a dict keyed by user_id, which would silently overwrite
# a user's earlier ticket on a second purchase, or by ticket_number, which
# can't represent two racing requests that got the same (buggy) number.
tickets_sold: list[tuple[int, str]] = []
idempotency: dict[str, int] = {}       # request_id → ticket_number
next_ticket: int = 1
start_time: float = time.time()
