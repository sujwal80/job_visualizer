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
    profileCache: new Map(),
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
