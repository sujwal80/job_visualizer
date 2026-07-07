export const state = {
    startupsData: [],
    currentSelectedId: null,
    defaultLocation: [77.5946, 12.9716],
    defaultZoom: 11,
    markersMap: new Map(),
    tempRemoteMarker: null,
    rateLimitedUntil: 0,
    activeFetchController: null,
    inFlightRequests: new Map(),
    profileCache: new Map(),
    currentFilters: {
        industry: 'all',
        query: ''
    },
    filterDebounceTimer: null,
    filterRafId: null,
    inputTimeout: null
};
