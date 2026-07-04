import time
import math
import threading
from collections import OrderedDict
from collections.abc import MutableMapping


class BoundedRateLimitDict(MutableMapping):
    """
    Thread-safe bounded LRU eviction rate limiter storage.
    Strictly caps in-memory capacity at `max_size` (default 10,000) unique client IPs.
    Supports automated TTL cleanup of expired timestamps.
    Guarantees thread safety with threading.RLock().
    """
    def __init__(self, max_size=10000):
        self._store = OrderedDict()
        self.max_size = max_size
        self.lock = threading.RLock()
        self._last_cleanup = time.time()

    def _evict_if_needed(self):
        # Must be called with lock held
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def purge_expired(self, window=60):
        now = time.time()
        with self.lock:
            expired_keys = []
            for key, reqs in list(self._store.items()):
                valid_reqs = [t for t in reqs if now - t < window]
                if not valid_reqs:
                    expired_keys.append(key)
                elif len(valid_reqs) != len(reqs):
                    self._store[key] = valid_reqs
            for key in expired_keys:
                del self._store[key]
            return len(expired_keys)

    def __getitem__(self, key):
        with self.lock:
            if key not in self._store:
                self._store[key] = []
                self._evict_if_needed()
            else:
                self._store.move_to_end(key)
            return self._store[key]

    def __setitem__(self, key, value):
        with self.lock:
            self._store[key] = value
            self._store.move_to_end(key)
            self._evict_if_needed()

    def __delitem__(self, key):
        with self.lock:
            del self._store[key]

    def __contains__(self, key):
        with self.lock:
            return key in self._store

    def __len__(self):
        with self.lock:
            return len(self._store)

    def __iter__(self):
        with self.lock:
            return iter(list(self._store.keys()))

    def __repr__(self):
        with self.lock:
            return repr(dict(self._store))

    def clear(self):
        with self.lock:
            self._store.clear()

    def keys(self):
        with self.lock:
            return list(self._store.keys())

    def values(self):
        with self.lock:
            return list(self._store.values())

    def items(self):
        with self.lock:
            return list(self._store.items())

    def get(self, key, default=None):
        with self.lock:
            if key in self._store:
                self._store.move_to_end(key)
                return self._store[key]
            return default

    def pop(self, key, *args):
        with self.lock:
            return self._store.pop(key, *args)


# Bounded IP-based token bucket rate limiter (120 req/min default, max 10,000 unique client IPs)
_rate_limits = BoundedRateLimitDict(max_size=10000)


def _check_rate_limit(ip, limit=120, window=60):
    with _rate_limits.lock:
        now = time.time()
        # Automated TTL cleanup: check periodically (every 5 seconds)
        if now - _rate_limits._last_cleanup >= 5.0:
            _rate_limits.purge_expired(window=window)
            _rate_limits._last_cleanup = now

        reqs = _rate_limits.get(ip, [])
        valid_reqs = [t for t in reqs if now - t < window]
        count = len(valid_reqs)
        if limit <= 0 or count >= limit:
            if not valid_reqs and ip in _rate_limits:
                del _rate_limits[ip]
            elif valid_reqs:
                _rate_limits[ip] = valid_reqs
            oldest = valid_reqs[0] if valid_reqs else now
            retry_after = max(1, int(math.ceil((oldest + window) - now)))
            return False, retry_after, 0, max(0, limit)
        valid_reqs.append(now)
        _rate_limits[ip] = valid_reqs
        return True, 0, limit - len(valid_reqs), limit

