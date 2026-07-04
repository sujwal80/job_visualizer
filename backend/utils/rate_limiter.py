import time
import math
from collections import defaultdict

# Simple IP-based token bucket rate limiter (120 req/min default)
_rate_limits = defaultdict(list)

def _check_rate_limit(ip, limit=120, window=60):
    now = time.time()
    reqs = _rate_limits[ip]
    _rate_limits[ip] = [t for t in reqs if now - t < window]
    count = len(_rate_limits[ip])
    if limit <= 0 or count >= limit:
        oldest = _rate_limits[ip][0] if _rate_limits[ip] else now
        retry_after = max(1, int(math.ceil((oldest + window) - now)))
        return False, retry_after, 0, max(0, limit)
    _rate_limits[ip].append(now)
    return True, 0, limit - len(_rate_limits[ip]), limit
