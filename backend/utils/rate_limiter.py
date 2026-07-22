"""
Token Bucket Rate Limiting Engine
Houses a thread-safe, bounded LRU eviction dictionary and token-bucket algorithm
to protect API endpoints against denial-of-service (DoS) attacks, brute-force enumeration,
and unauthenticated scraping while preventing unbounded memory consumption.
"""

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
    Guarantees thread safety in multi-threaded WSGI workers with threading.RLock().
    """
    def __init__(self, max_size=10000):
        """
        Initialize the bounded rate limit storage dictionary.

        Args:
            max_size (int): The maximum number of unique client IP addresses to store in memory.
        """
        self._store = OrderedDict()
        self.max_size = max_size
        self.lock = threading.RLock()
        self._last_cleanup = time.time()

    def _evict_if_needed(self):
        """
        Evict the oldest accessed IP entries if the current store exceeds `max_size`.
        Must be called with `self.lock` held by the calling thread.
        """
        while len(self._store) > self.max_size:
            # popitem(last=False) removes the oldest FIFO/LRU item in O(1) time
            self._store.popitem(last=False)

    def purge_expired(self, window=60):
        """
        Sweep the data store and remove any timestamp records older than the sliding window.

        Args:
            window (int): The duration in seconds after which a request record is considered expired.

        Returns:
            int: The number of unique client IP keys completely removed from the dictionary.
        """
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
        """Retrieve the request timestamp list for a client IP, marking it as recently used."""
        with self.lock:
            if key not in self._store:
                self._store[key] = []
                self._evict_if_needed()
            else:
                # Move to end to maintain LRU access order
                self._store.move_to_end(key)
            return self._store[key]

    def __setitem__(self, key, value):
        """Set the request timestamp list for a client IP and enforce capacity bounding."""
        with self.lock:
            self._store[key] = value
            self._store.move_to_end(key)
            self._evict_if_needed()

    def __delitem__(self, key):
        """Delete a client IP record from the rate limiter storage."""
        with self.lock:
            del self._store[key]

    def __contains__(self, key):
        """Check if a client IP currently has tracked request timestamps in memory."""
        with self.lock:
            return key in self._store

    def __len__(self):
        """Return the number of unique client IP addresses currently tracked."""
        with self.lock:
            return len(self._store)

    def __iter__(self):
        """Iterate over all tracked client IP address keys."""
        with self.lock:
            return iter(list(self._store.keys()))

    def __repr__(self):
        """Return a string representation of the internal rate limit dictionary."""
        with self.lock:
            return repr(dict(self._store))

    def clear(self):
        """Clear all tracked request records and reset the storage."""
        with self.lock:
            self._store.clear()

    def keys(self):
        """Return a list of all tracked client IP address keys."""
        with self.lock:
            return list(self._store.keys())

    def values(self):
        """Return a list of all timestamp record lists in the storage."""
        with self.lock:
            return list(self._store.values())

    def items(self):
        """Return a list of (client_ip, timestamp_list) tuples."""
        with self.lock:
            return list(self._store.items())

    def get(self, key, default=None):
        """Retrieve request timestamps for an IP or return default without raising KeyError."""
        with self.lock:
            if key in self._store:
                self._store.move_to_end(key)
                return self._store[key]
            return default

    def pop(self, key, *args):
        """Remove and return the timestamp record list for a given IP key."""
        with self.lock:
            return self._store.pop(key, *args)


# Bounded IP-based token bucket rate limiter (120 req/min default, max 10,000 unique client IPs)
_rate_limits = BoundedRateLimitDict(max_size=10000)


def _check_rate_limit(key, limit=120, window=60):
    """
    Evaluate if an incoming request is permitted by the rate limiter.

    Implements a sliding-window token bucket algorithm in thread-safe shared memory.

    Args:
        key (str): The rate limit tracking key (e.g. client IP or authenticated user key).
        limit (int): Maximum allowable requests within the sliding window.
        window (int): The sliding window time span in seconds (default 60s).

    Returns:
        tuple: (
            bool allowed: True if request is permitted, False if rate limited.
            int retry_after: Seconds remaining until the oldest token expires (if blocked).
            int remaining: Number of allowable requests remaining in the window.
            int limit_val: The total quota limit enforced for this window.
        )
    """
    with _rate_limits.lock:
        now = time.time()
        # Automated TTL cleanup: periodically sweep expired timestamps every 5 seconds
        if now - _rate_limits._last_cleanup >= 5.0:
            _rate_limits.purge_expired(window=window)
            _rate_limits._last_cleanup = now

        reqs = _rate_limits.get(key, [])
        # Filter timestamps to retain only those within the active sliding time window
        valid_reqs = [t for t in reqs if now - t < window]
        count = len(valid_reqs)
        if limit <= 0 or count >= limit:
            if not valid_reqs and key in _rate_limits:
                del _rate_limits[key]
            elif valid_reqs:
                _rate_limits[key] = valid_reqs
            oldest = valid_reqs[0] if valid_reqs else now
            retry_after = max(1, int(math.ceil((oldest + window) - now)))
            return False, retry_after, 0, max(0, limit)
        valid_reqs.append(now)
        _rate_limits[key] = valid_reqs
        return True, 0, limit - len(valid_reqs), limit
