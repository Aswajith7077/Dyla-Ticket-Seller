import time
from collections import deque


class MetricsTracker:
    def __init__(self):
        self.total_requests: int = 0
        self.errors: int = 0
        self._response_times: deque = deque(maxlen=10000)
        self._request_timestamps: deque = deque(maxlen=10000)

    def record(self, response_ms: float, is_error: bool = False):
        now = time.time()
        self.total_requests += 1
        self._response_times.append(response_ms)
        self._request_timestamps.append(now)
        if is_error:
            self.errors += 1

    def rps(self) -> float:
        now = time.time()
        recent = [t for t in self._request_timestamps if now - t <= 1.0]
        return float(len(recent))

    def percentile(self, p: float) -> float:
        if not self._response_times:
            return 0.0
        sorted_times = sorted(self._response_times)
        idx = int(len(sorted_times) * p / 100)
        return sorted_times[min(idx, len(sorted_times) - 1)]


tracker = MetricsTracker()
