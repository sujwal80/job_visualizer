class BoundedRateLimitMap {
  constructor(maxSize = 10000) {
    this.maxSize = maxSize;
    this.store = new Map();
    this.lastCleanup = Date.now() / 1000;
  }

  evictIfNeeded() {
    while (this.store.size > this.maxSize) {
      const oldestKey = this.store.keys().next().value;
      this.store.delete(oldestKey);
    }
  }

  purgeExpired(window = 60) {
    const now = Date.now() / 1000;
    let expiredCount = 0;
    for (const [key, reqs] of this.store.entries()) {
      const validReqs = reqs.filter(t => now - t < window);
      if (validReqs.length === 0) {
        this.store.delete(key);
        expiredCount++;
      } else if (validReqs.length !== reqs.length) {
        this.store.set(key, validReqs);
      }
    }
    return expiredCount;
  }

  get(key) {
    if (!this.store.has(key)) {
      this.store.set(key, []);
      this.evictIfNeeded();
      return [];
    }
    const val = this.store.get(key);
    this.store.delete(key);
    this.store.set(key, val);
    return val;
  }

  set(key, value) {
    this.store.delete(key);
    this.store.set(key, value);
    this.evictIfNeeded();
  }

  delete(key) {
    this.store.delete(key);
  }

  has(key) {
    return this.store.has(key);
  }

  clear() {
    this.store.clear();
  }
}

const rateLimits = new BoundedRateLimitMap(10000);

export function checkRateLimit(key, limit = 120, window = 60) {
  const now = Date.now() / 1000;
  if (now - rateLimits.lastCleanup >= 5.0) {
    rateLimits.purgeExpired(window);
    rateLimits.lastCleanup = now;
  }

  const reqs = rateLimits.get(key);
  const validReqs = reqs.filter(t => now - t < window);
  const count = validReqs.length;

  if (limit <= 0 || count >= limit) {
    if (validReqs.length === 0 && rateLimits.has(key)) {
      rateLimits.delete(key);
    } else if (validReqs.length > 0) {
      rateLimits.set(key, validReqs);
    }
    const oldest = validReqs[0] || now;
    const retryAfter = Math.max(1, Math.ceil((oldest + window) - now));
    return [false, retryAfter, 0, Math.max(0, limit)];
  }

  validReqs.push(now);
  rateLimits.set(key, validReqs);
  return [true, 0, limit - validReqs.length, limit];
}

export { rateLimits };
export default checkRateLimit;
