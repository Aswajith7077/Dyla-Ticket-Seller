import time

tickets_available: int = 0
tickets_sold: dict[str, int] = {}      # user_id → ticket_number
idempotency: dict[str, int] = {}       # request_id → ticket_number
next_ticket: int = 1
start_time: float = time.time()
