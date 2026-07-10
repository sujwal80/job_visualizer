export class LRUCacheWithTTL {
    constructor({ capacity = 100, defaultTTL = 300000, storage = null, prefix = '' } = {}) {
        this.capacity = capacity;
        this.defaultTTL = defaultTTL;
        this.storage = null;
        if (storage === 'sessionStorage' && typeof window !== 'undefined' && window.sessionStorage) {
            this.storage = window.sessionStorage;
        } else if (storage === 'localStorage' && typeof window !== 'undefined' && window.localStorage) {
            this.storage = window.localStorage;
        } else if (storage && typeof storage.getItem === 'function' && typeof storage.setItem === 'function') {
            this.storage = storage;
        }
        this.prefix = prefix;
        this.cache = new Map();
    }

    _getStorageKey(key) {
        return `${this.prefix}${key}`;
    }

    set(key, value, ttl = this.defaultTTL) {
        const expiry = Date.now() + ttl;
        if (this.cache.has(key)) {
            this.cache.delete(key);
        } else if (this.cache.size >= this.capacity) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
            if (this.storage) {
                try {
                    this.storage.removeItem(this._getStorageKey(firstKey));
                } catch (e) {}
            }
        }
        this.cache.set(key, { value, expiry });

        if (this.storage) {
            try {
                this.storage.setItem(
                    this._getStorageKey(key),
                    JSON.stringify({ value, expiry })
                );
            } catch (e) {}
        }
        return this;
    }

    get(key) {
        const now = Date.now();
        let item = this.cache.get(key);

        if (!item && this.storage) {
            try {
                const stored = this.storage.getItem(this._getStorageKey(key));
                if (stored) {
                    const parsed = JSON.parse(stored);
                    if (parsed && typeof parsed.expiry === 'number') {
                        item = parsed;
                        if (item.expiry > now) {
                            if (this.cache.size >= this.capacity) {
                                const firstKey = this.cache.keys().next().value;
                                this.cache.delete(firstKey);
                            }
                            this.cache.set(key, item);
                        }
                    }
                }
            } catch (e) {}
        }

        if (!item) {
            return undefined;
        }

        if (now >= item.expiry) {
            this.delete(key);
            return undefined;
        }

        this.cache.delete(key);
        this.cache.set(key, item);

        return item.value;
    }

    has(key) {
        return this.get(key) !== undefined;
    }

    delete(key) {
        this.cache.delete(key);
        if (this.storage) {
            try {
                this.storage.removeItem(this._getStorageKey(key));
            } catch (e) {}
        }
    }

    clear() {
        if (this.storage && this.prefix) {
            try {
                const keysToRemove = [];
                for (let i = 0; i < this.storage.length; i++) {
                    const k = this.storage.key(i);
                    if (k && k.startsWith(this.prefix)) {
                        keysToRemove.push(k);
                    }
                }
                keysToRemove.forEach(k => {
                    try { this.storage.removeItem(k); } catch (e) {}
                });
            } catch (e) {}
        }
        this.cache.clear();
    }

    get size() {
        return this.cache.size;
    }

    keys() {
        return this.cache.keys();
    }

    values() {
        return Array.from(this.cache.values()).map(item => item.value);
    }

    entries() {
        return Array.from(this.cache.entries()).map(([k, item]) => [k, item.value]);
    }
}

export const state = {
    searchedCity: '',
    startupsData: [],
    currentSelectedId: null,
    defaultLocation: [77.5946, 12.9716],
    defaultZoom: 11,
    markersMap: new Map(),
    tempRemoteMarker: null,
    rateLimitedUntil: 0,
    activeFetchController: null,
    inFlightRequests: new Map(),
    inFlightPromises: new Map(),
    queryCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 120000, storage: null }),
    profileCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 300000, storage: 'sessionStorage', prefix: 'wtm_profile_' }),
    geocodeCache: new LRUCacheWithTTL({ capacity: 50, defaultTTL: 86400000, storage: 'localStorage', prefix: 'wtm_geocode_' }),
    currentDataVersion: null,
    currentFilters: {
        industry: 'all',
        query: ''
    },
    filterRafId: null,
    inputTimeout: null,
    isProgrammaticMove: false,
    programmaticMoveTimeout: null
};

export function lockProgrammaticMove(durationMs = 2500) {
    state.isProgrammaticMove = true;
    if (state.programmaticMoveTimeout) {
        clearTimeout(state.programmaticMoveTimeout);
    }
    state.programmaticMoveTimeout = setTimeout(() => {
        state.isProgrammaticMove = false;
        state.programmaticMoveTimeout = null;
    }, durationMs);
}
