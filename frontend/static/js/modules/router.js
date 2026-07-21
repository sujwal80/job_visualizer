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

export const KNOWN_HUB_COORDINATES = {
    'bengaluru': [77.5946, 12.9716],
    'bangalore': [77.5946, 12.9716],
    'san francisco': [-122.4194, 37.7749],
    'london': [-0.1276, 51.5074],
    'singapore': [103.8198, 1.3521],
    'mumbai': [72.8777, 19.0760],
    'pune': [73.8567, 18.5204],
    'delhi': [77.1025, 28.7041],
    'hyderabad': [78.4867, 17.3850],
    'chennai': [80.2707, 13.0827],
    'gurugram': [77.0266, 28.4595],
    'noida': [77.3910, 28.5355]
};

const JOB_KEYWORDS = [
    "engineer", "developer", "designer", "manager", "sales", "marketing", "doctor", "teacher",
    "writer", "architect", "analyst", "consultant", "specialist", "coordinator", "officer",
    "director", "lead", "head", "president", "vp", "intern", "trainee", "support", "admin",
    "recruiter", "hr", "accountant", "counsel", "lawyer", "nurse", "technician", "operator",
    "programmer", "coder", "executive", "representative", "associate", "expert", "principal",
    "staff", "senior", "junior", "internship", "part-time", "contract", "freelance", "fullstack",
    "frontend", "backend", "full-stack", "front-end", "back-end", "mobile", "ios", "android",
    "devops", "cloud", "data", "ai", "ml", "artificial intelligence", "machine learning",
    "deep learning", "nlp", "vision", "robotics", "blockchain", "web3", "crypto", "security",
    "cybersecurity", "networking", "systems", "embedded", "firmware", "hardware", "qa",
    "testing", "automation", "sre", "infrastructure", "database", "dba", "sql", "nosql",
    "big data", "analytics", "business intelligence", "bi", "product", "project", "program",
    "agile", "scrum", "scrummaster", "scrum master", "design", "ux", "ui", "user experience",
    "user interface", "graphics", "illustrator", "animation", "video", "content", "copywriter",
    "editor", "social media", "seo", "sem", "growth", "operations", "ops", "finance", "legal",
    "compliance", "risk", "audit", "tax", "payroll", "salesforce", "sap", "oracle", "it",
    "sysadmin", "helpdesk", "technical writer"
];

function isJobQuery(q) {
    const lower = q.toLowerCase().trim();
    return JOB_KEYWORDS.some(k => new RegExp(`\\b${k}\\b`, 'i').test(lower));
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
        if (navInput) {
            navInput.value = '';
            navInput.placeholder = "Search city/location or job title...";
        }
        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Heuristic: Check if this is a job title/keyword query rather than a location
    if (isJobQuery(queryTrimmed)) {
        const newUrlParams = new URLSearchParams(window.location.search);
        newUrlParams.set('q', queryTrimmed);
        const currentHash = window.location.hash || '';
        const newUrl = `${window.location.pathname}?${newUrlParams.toString()}${currentHash}`;

        if (!skipPushState) {
            window.history.pushState({ path: newUrl }, '', newUrl);
        } else {
            window.history.replaceState({ path: newUrl }, '', newUrl);
        }
        state.lastQueryString = window.location.search;

        const navInput = document.getElementById('unified-search-input');
        if (navInput) navInput.value = queryTrimmed;

        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Treat as location query
    const lowerQuery = queryTrimmed.toLowerCase();
    if (KNOWN_HUB_COORDINATES[lowerQuery]) {
        state.defaultLocation = KNOWN_HUB_COORDINATES[lowerQuery];
        state.defaultZoom = 11;

        lockProgrammaticMove(2500);
        map.flyTo({
            center: state.defaultLocation,
            zoom: state.defaultZoom,
            speed: 3.0,
            essential: true
        });

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
        state.searchedCity = lowerQuery;

        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = queryTrimmed;

        const navInput = document.getElementById('unified-search-input');
        if (navInput) {
            navInput.value = ''; // clear for next keyword search
            navInput.placeholder = `Search jobs in ${queryTrimmed}...`;
        }

        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Geocode custom location queries using Nominatim
    const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(queryTrimmed)}&format=json&limit=1`;
    showDirectoryLoading();

    if (state.activeGeocodeController) {
        state.activeGeocodeController.abort();
    }
    state.activeGeocodeController = new AbortController();
    const signal = state.activeGeocodeController.signal;

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
            const importance = parseFloat(data[0].importance || '0');
            const type = data[0].type || '';
            const cls = data[0].class || '';

            // Robust validation to ensure it's a real location and not a job title/office
            const isPostal = type === 'postcode' || type === 'postal_code';
            const isCityOrRegion = ['city', 'town', 'village', 'suburb', 'county', 'state', 'country', 'administrative'].includes(type);

            if (importance >= 0.1 && (isPostal || isCityOrRegion)) {
                const lat = parseFloat(data[0].lat);
                const lon = parseFloat(data[0].lon);
                if (!isNaN(lat) && !isNaN(lon)) {
                    state.defaultLocation = [lon, lat];
                    state.defaultZoom = 11;

                    lockProgrammaticMove(2500);
                    map.flyTo({
                        center: state.defaultLocation,
                        zoom: state.defaultZoom,
                        speed: 3.0,
                        essential: true
                    });

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
                    state.searchedCity = lowerQuery;

                    const titleEl = document.getElementById('activeMapTitle');
                    if (titleEl) titleEl.textContent = queryTrimmed;

                    const navInput = document.getElementById('unified-search-input');
                    if (navInput) {
                        navInput.value = '';
                        navInput.placeholder = `Search jobs in ${queryTrimmed}...`;
                    }

                    if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
                        window.WorldTechApp.fetchFilteredStartups();
                    }
                    return;
                }
            }
        }
        throw new Error('Not a valid location');
    })
    .catch(err => {
        if (err.name === 'AbortError') return;
        console.warn('[Geocoder] Failed to geocode unified query as location, falling back to keyword search:', err);

        // Fallback: treat the query as a keyword/job search rather than a location
        const newUrlParams = new URLSearchParams(window.location.search);
        newUrlParams.set('q', queryTrimmed);
        const currentHash = window.location.hash || '';
        const newUrl = `${window.location.pathname}?${newUrlParams.toString()}${currentHash}`;

        if (!skipPushState) {
            window.history.pushState({ path: newUrl }, '', newUrl);
        } else {
            window.history.replaceState({ path: newUrl }, '', newUrl);
        }
        state.lastQueryString = window.location.search;

        const navInput = document.getElementById('unified-search-input');
        if (navInput) navInput.value = queryTrimmed;

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
    let lowerCity = (cityTitle || '').trim().toLowerCase();

    // Map synonyms/countries to their corresponding canonical hub titles
    const usaTerms = ["san", "francisco", "sf", "ca", "usa", "us", "united states", "america", "california"];
    const ukTerms = ["london", "uk", "england", "united kingdom", "gb", "great britain"];
    const indiaTerms = ["india", "in", "bengaluru", "bangalore", "karnataka", "blr"];

    let canonicalCity = cityTitle;
    let newLocation = [77.5946, 12.9716];
    let newZoom = 11;
    let isNewHub = false;

    if (usaTerms.some(term => lowerCity.includes(term))) {
        canonicalCity = 'San Francisco, CA';
        lowerCity = 'san francisco, ca';
        newLocation = [-122.4194, 37.7749];
        newZoom = 12;
        isNewHub = true;
    } else if (ukTerms.some(term => lowerCity.includes(term))) {
        canonicalCity = 'London, UK';
        lowerCity = 'london, uk';
        newLocation = [-0.1276, 51.5072];
        newZoom = 12;
        isNewHub = true;
    } else if (indiaTerms.some(term => lowerCity.includes(term))) {
        canonicalCity = 'Bengaluru, KA';
        lowerCity = 'bengaluru, ka';
        newLocation = [77.5946, 12.9716];
        newZoom = 11;
        isNewHub = true;
    }

    // Update active title and navbar input value
    const titleEl = document.getElementById('activeMapTitle');
    if (titleEl) titleEl.textContent = canonicalCity;
    const navInput = document.getElementById('navbar-city-input') || document.getElementById('unified-search-input');
    if (navInput) navInput.value = canonicalCity;

    // Update URL query parameters without reloading
    const currentHash = window.location.hash || '';
    const newUrl = `${window.location.pathname}?city=${encodeURIComponent(canonicalCity)}${currentHash}`;
    if (!skipPushState) {
        window.history.pushState({ path: newUrl }, '', newUrl);
    } else {
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }
    state.lastQueryString = window.location.search;
    state.searchedCity = lowerCity;

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
        const cachedCoords = state.geocodeCache.get(lowerCity);
        if (cachedCoords && Array.isArray(cachedCoords) && cachedCoords.length === 2) {
            handleFlyTo(cachedCoords, 11);
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
                        state.geocodeCache.set(lowerCity, [lon, lat]);
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
}


