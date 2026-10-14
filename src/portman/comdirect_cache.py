from copy import deepcopy
import threading
import time


class MemoryCache:
    def __init__(self, ttl=300, capacity=32, *, clock=time.monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self.entries = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            expires, value = entry
            if self.clock() >= expires:
                del self.entries[key]
                return None
            return deepcopy(value)

    def put(self, key, value, *, acquired_at=None):
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if v[0] > now and k != key}
            while len(self.entries) >= self.capacity:
                del self.entries[next(iter(self.entries))]
            expires = (now if acquired_at is None else acquired_at) + self.ttl
            if expires > now:
                self.entries[key] = (expires, deepcopy(value))

    def clear(self):
        with self.lock:
            self.entries.clear()

    def discard(self, key):
        with self.lock:
            self.entries.pop(key, None)


FETCH_CACHE = MemoryCache()
