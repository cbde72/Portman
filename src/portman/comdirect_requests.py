import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_delay(value, attempt, now=None):
    if isinstance(value, str):
        if value.strip().isdigit():
            return float(value.strip())
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is not None:
                return max(0, (deadline - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return 5 * 2 ** attempt


class RequestQueue:
    def __init__(self, interval=6.01, *, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.lock = threading.Lock()
        self.next_request = 0

    def run(self, action, check, progress, *, max_wait=None):
        started = self.clock()
        announced = False
        while True:
            check()
            if max_wait is not None and self.clock() - started >= max_wait:
                raise TimeoutError('comdirect-Warteschlange ist belegt.')
            if self.lock.acquire(blocking=False):
                try:
                    remaining = self.next_request - self.clock()
                    if remaining <= 0:
                        check()
                        self.next_request = self.clock() + self.interval
                        response = action()
                        if response.status_code == 429:
                            self.next_request = max(self.next_request, self.clock() +
                                retry_delay(response.headers.get('Retry-After'), 0))
                        return response
                finally:
                    self.lock.release()
            if not announced:
                progress('comdirect: Anfrage wartet auf das Abruflimit (höchstens 10 pro Minute) …')
                announced = True
            self.sleep(.1)

    def defer(self, seconds):
        with self.lock:
            self.next_request = max(self.next_request, self.clock() + seconds)


REQUEST_QUEUE = RequestQueue()
