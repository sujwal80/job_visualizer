import { state, lockProgrammaticMove } from './state.js';
import {
    map,
    updateMarkersVisualState
} from './map_manager.js';
import { selectAndOpenStartup, showDirectoryLoading } from './ui_manager.js';
import { showToast } from './utils.js';

export function handleHashRouting() {
    const hash = window.location.hash;
    console.log('[DEBUG handleHashRouting] hash="' + hash + '" state.currentSelectedId=' + state.currentSelectedId);
    const urlParams = new URLSearchParams(window.location.search);
    const queryCompanyId = urlParams.get('company_id');

    let targetId = null;
    if (hash.startsWith('#company_id=')) {
        targetId = parseInt(hash.split('=')[1], 10);
    } else if (queryCompanyId) {
        targetId = parseInt(queryCompanyId, 10);
    }

    if (targetId !== null && !isNaN(targetId)) {
        if (state.currentSelectedId === targetId) return;
        selectAndOpenStartup(targetId);
        return;
    }

    if (state.tempRemoteMarker) {
        state.tempRemoteMarker.remove();
        state.tempRemoteMarker = null;
    }
    state.currentSelectedId = null;
    const detailsDrawer = document.getElementById('details-drawer');
    if (detailsDrawer && detailsDrawer.classList.contains('active')) {
        detailsDrawer.classList.remove('active');
        detailsDrawer.setAttribute('aria-hidden', 'true');
        lockProgrammaticMove(2500);
        map.flyTo({
            center: state.defaultLocation,
            zoom: state.defaultZoom,
            speed: 3.0,
            essential: true
        });
        window.WorldTechApp.applyFiltering();
        updateMarkersVisualState();
    }
}

export function executeUnifiedSearch(query, options = {}) {
    const skipPushState = !!options.skipPushState;

    // 1. Close any open details drawer programmatically (updating url hash without triggering hashchange)
    const detailsDrawer = document.getElementById('details-drawer');
    if (detailsDrawer && detailsDrawer.classList.contains('active')) {
        detailsDrawer.classList.remove('active');
        detailsDrawer.setAttribute('aria-hidden', 'true');
    }
    state.currentSelectedId = null;
    if (window.location.hash) {
        const urlWithoutHash = window.location.pathname + window.location.search;
        window.history.replaceState({ path: urlWithoutHash }, '', urlWithoutHash);
    }

    const queryTrimmed = (query || '').trim();
    if (!queryTrimmed) {
        // Clear parameters
        const newUrlParams = new URLSearchParams(window.location.search);
        newUrlParams.delete('city');
        newUrlParams.delete('q');
        const newUrl = `${window.location.pathname}?${newUrlParams.toString()}`;
        if (!skipPushState) {
            window.history.pushState({ path: newUrl }, '', newUrl);
        } else {
            window.history.replaceState({ path: newUrl }, '', newUrl);
        }
        state.lastQueryString = window.location.search;
        state.searchedCity = '';
        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = 'All locations';
        const navInput = document.getElementById('unified-search-input');
        if (navInput) navInput.value = '';
        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Update active title and navbar input value
    const titleEl = document.getElementById('activeMapTitle');
    if (titleEl) titleEl.textContent = queryTrimmed;
    const navInput = document.getElementById('unified-search-input');
    if (navInput) navInput.value = queryTrimmed;

    // Geocode query using Nominatim restricted to India (countrycodes=in)
    const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(queryTrimmed)}&countrycodes=in&format=json&limit=1`;
    
    showDirectoryLoading();

    if (state.activeGeocodeController) {
        state.activeGeocodeController.abort();
    }
    state.activeGeocodeController = new AbortController();
    const signal = state.activeGeocodeController.signal;
    console.log('[DEBUG router.js executeUnifiedSearch geocode] fetching geocode for ' + queryTrimmed);
    fetch(geoUrl, {
        signal,
        headers: {
            'Accept': 'application/json',
            'User-Agent': 'WorldTechMap-JobVisualizer/1.0 (sujwal80@gmail.com)'
        }
    })
    .then(res => {
        if (!res.ok) throw new Error(`HTTP error ${res.status}`);
        return res.json();
    })
    .then(data => {
        if (signal.aborted) return;
        if (Array.isArray(data) && data.length > 0) {
            const lat = parseFloat(data[0].lat);
            const lon = parseFloat(data[0].lon);
            if (!isNaN(lat) && !isNaN(lon)) {
                // On success: zoom and fly map to coordinates
                state.defaultLocation = [lon, lat];
                state.defaultZoom = 11;

                lockProgrammaticMove(2500);
                map.flyTo({
                    center: state.defaultLocation,
                    zoom: state.defaultZoom,
                    speed: 3.0,
                    essential: true
                });

                // set URL parameter city=query (clearing q)
                const newUrlParams = new URLSearchParams(window.location.search);
                newUrlParams.set('city', queryTrimmed);
                newUrlParams.delete('q');
                const currentHash = window.location.hash || '';
                const newUrl = `${window.location.pathname}?${newUrlParams.toString()}${currentHash}`;
                
                if (!skipPushState) {
                    window.history.pushState({ path: newUrl }, '', newUrl);
                } else {
                    window.history.replaceState({ path: newUrl }, '', newUrl);
                }
                state.lastQueryString = window.location.search;

                state.searchedCity = queryTrimmed.toLowerCase();
                
                if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
                    window.WorldTechApp.fetchFilteredStartups();
                }
                return;
            }
        }
        throw new Error('No coordinates returned');
    })
    .catch(err => {
        if (err.name === 'AbortError') return;
        console.warn('[Geocoder] Failed to geocode unified query, falling back to keyword search:', err);
        // On failure: do NOT fly the map. Set URL parameter q=query (clearing city)
        const newUrlParams = new URLSearchParams(window.location.search);
        newUrlParams.set('q', queryTrimmed);
        newUrlParams.delete('city');
        const currentHash = window.location.hash || '';
        const newUrl = `${window.location.pathname}?${newUrlParams.toString()}${currentHash}`;
        
        if (!skipPushState) {
            window.history.pushState({ path: newUrl }, '', newUrl);
        } else {
            window.history.replaceState({ path: newUrl }, '', newUrl);
        }
        state.lastQueryString = window.location.search;

        // clear state.searchedCity (so bounding boxes are sent)
        state.searchedCity = '';

        // show a warning toast using showToast notifying that keyword search is run inside the current viewport
        showToast('Location not found. Showing keyword matches inside current viewport.', 'warning');

        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
    })
    .finally(() => {
        if (state.activeGeocodeController && state.activeGeocodeController.signal === signal) {
            state.activeGeocodeController = null;
        }
    });
}

export function updateSearchCity(cityTitle, options = {}) {
    const skipPushState = !!options.skipPushState;
    const lowerCity = (cityTitle || '').trim().toLowerCase();

    // Update active title and navbar input value
    const titleEl = document.getElementById('activeMapTitle');
    if (titleEl) titleEl.textContent = cityTitle;
    const navInput = document.getElementById('navbar-city-input') || document.getElementById('unified-search-input');
    if (navInput) navInput.value = cityTitle;

    // Update URL query parameters without reloading
    const currentHash = window.location.hash || '';
    const newUrl = `${window.location.pathname}?city=${encodeURIComponent(cityTitle)}${currentHash}`;
    if (!skipPushState) {
        window.history.pushState({ path: newUrl }, '', newUrl);
    } else {
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }
    state.lastQueryString = window.location.search;
    state.searchedCity = lowerCity;

    // Resolve location coordinates (either hub or geocode)
    let newLocation = [77.5946, 12.9716];
    let newZoom = 11;
    let isNewHub = false;

    const usaTerms = ["san", "francisco", "sf", "ca", "usa", "us", "united states", "america", "california"];
    const ukTerms = ["london", "uk", "england", "united kingdom", "gb", "great britain"];

    if (usaTerms.some(term => lowerCity.includes(term))) {
        newLocation = [-122.4194, 37.7749];
        newZoom = 12;
        isNewHub = true;
    } else if (ukTerms.some(term => lowerCity.includes(term))) {
        newLocation = [-0.1276, 51.5072];
        newZoom = 12;
        isNewHub = true;
    } else if (lowerCity.includes('bengaluru') || lowerCity.includes('bangalore') || lowerCity.includes('india') || lowerCity === 'in' || lowerCity === 'blr') {
        newLocation = [77.5946, 12.9716];
        newZoom = 11;
        isNewHub = true;
    }

    const handleFlyTo = (coords, zoomVal) => {
        state.defaultLocation = coords;
        state.defaultZoom = zoomVal;

        showDirectoryLoading();

        const currentCenter = map.getCenter();
        const currentZoom = map.getZoom();
        const dist = Math.hypot(currentCenter.lng - coords[0], currentCenter.lat - coords[1]);
        const zoomDist = Math.abs(currentZoom - zoomVal);

        if (dist > 0.005 || zoomDist > 0.5) {
            lockProgrammaticMove(2500);
            map.flyTo({
                center: state.defaultLocation,
                zoom: state.defaultZoom,
                speed: 3.0,
                essential: true
            });
        }
        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
    };

    if (isNewHub) {
        handleFlyTo(newLocation, newZoom);
    } else {
        const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(cityTitle)}&format=json&limit=1`;
        fetch(geoUrl, {
            headers: {
                'Accept': 'application/json',
                'User-Agent': 'WorldTechMap-JobVisualizer/1.0 (sujwal80@gmail.com)'
            }
        })
        .then(res => {
            if (!res.ok) throw new Error(`HTTP error ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (Array.isArray(data) && data.length > 0) {
                const lat = parseFloat(data[0].lat);
                const lon = parseFloat(data[0].lon);
                if (!isNaN(lat) && !isNaN(lon)) {
                    handleFlyTo([lon, lat], 11);
                    return;
                }
            }
            handleFlyTo(newLocation, newZoom);
        })
        .catch(err => {
            console.warn('[Geocoder] Failed to geocode custom city query:', err);
            handleFlyTo(newLocation, newZoom);
        });
    }
}

