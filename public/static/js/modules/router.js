import { state, lockProgrammaticMove } from './state.js';
import {
    map,
    updateMarkersVisualState,
    drawSearchBoundary,
    clearSearchBoundary
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

export function normalizeLocationQuery(query) {
    if (!query) return '';
    let q = query.trim().toLowerCase();
    
    // Split by comma (e.g. "San Francisco, CA" -> "San Francisco")
    if (q.includes(',')) {
        q = q.split(',')[0].trim();
    }
    
    // Strip trailing space-separated country/state suffixes (but preserve standalone country searches)
    const suffixes = [
        'ca', 'ka', 'in', 'usa', 'us', 'uk', 'india', 'united states', 
        'california', 'karnataka', 'england', 'united kingdom', 'gb', 'us'
    ];
    for (const suffix of suffixes) {
        if (q.endsWith(' ' + suffix)) {
            q = q.substring(0, q.length - (suffix.length + 1)).trim();
            break;
        }
    }
    return q;
}

export const KNOWN_HUB_COORDINATES = {
    'bengaluru': [77.5946, 12.9716],
    'bangalore': [77.5946, 12.9716],
    'san francisco': [-122.4194, 37.7749],
    'london': [-0.1276, 51.5074],
    'singapore': [103.8198, 1.3521],
    'mumbai': [72.8777, 19.0760],
    'pune': [73.8567, 18.5204],
    'delhi': [77.2090, 28.6139],
    'hyderabad': [78.4867, 17.3850],
    'chennai': [80.2707, 13.0827],
    'gurugram': [77.0266, 28.4595],
    'noida': [77.3910, 28.5355],
    'india': [77.5946, 12.9716],
    'in': [77.5946, 12.9716],
    'usa': [-122.4194, 37.7749],
    'us': [-122.4194, 37.7749],
    'united states': [-122.4194, 37.7749],
    'uk': [-0.1276, 51.5074],
    'united kingdom': [-0.1276, 51.5074]
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
        state.boundsOverride = null;
        clearSearchBoundary();
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
        state.searchedCityCenter = null;
        state.hasPannedLocally = false;
        
        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = 'All locations';
        
        const navInput = document.getElementById('unified-search-input');
        if (navInput) {
            navInput.value = '';
            navInput.placeholder = "Search city/location ...";
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
    const normalizedQuery = normalizeLocationQuery(queryTrimmed);
    if (KNOWN_HUB_COORDINATES[normalizedQuery]) {
        state.boundsOverride = null;
        if (state.hubBoundaries && state.hubBoundaries[normalizedQuery]) {
            drawSearchBoundary(state.hubBoundaries[normalizedQuery]);
        } else {
            clearSearchBoundary();
        }
        state.defaultLocation = KNOWN_HUB_COORDINATES[normalizedQuery];
        state.searchedCityCenter = KNOWN_HUB_COORDINATES[normalizedQuery];
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
        state.searchedCity = normalizedQuery;
        state.hasPannedLocally = false;

        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = queryTrimmed;

        const navInput = document.getElementById('unified-search-input');
        if (navInput) {
            navInput.value = queryTrimmed;
            navInput.placeholder = `Search jobs in ${queryTrimmed}...`;
        }

        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Check geocodeCache first to bypass Nominatim completely
    const cachedCoords = state.geocodeCache.get(normalizedQuery);
    if (cachedCoords && Array.isArray(cachedCoords) && cachedCoords.length >= 2) {
        const [lon, lat] = cachedCoords;
        if (cachedCoords.length >= 6 && cachedCoords[2] !== null) {
            state.boundsOverride = [cachedCoords[2], cachedCoords[3], cachedCoords[4], cachedCoords[5]];
        } else {
            state.boundsOverride = null;
        }
        if (cachedCoords.length >= 7 && cachedCoords[6]) {
            drawSearchBoundary(cachedCoords[6]);
        } else {
            clearSearchBoundary();
        }
        state.defaultLocation = [lon, lat];
        state.searchedCityCenter = [lon, lat];
        const isLocalityCached = state.boundsOverride && Math.abs(state.boundsOverride[1] - state.boundsOverride[0]) < 0.2;
        state.defaultZoom = isLocalityCached ? 13.5 : 11;

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
        state.searchedCity = normalizedQuery;
        state.hasPannedLocally = false;

        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = queryTrimmed;

        if (window.WorldTechApp && typeof window.WorldTechApp.fetchFilteredStartups === 'function') {
            window.WorldTechApp.fetchFilteredStartups();
        }
        return;
    }

    // Geocode custom location queries using Nominatim
    const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(queryTrimmed)}&format=json&limit=1&polygon_geojson=1`;
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
                    if (data[0].boundingbox && data[0].boundingbox.length === 4) {
                        state.boundsOverride = [
                            parseFloat(data[0].boundingbox[0]),
                            parseFloat(data[0].boundingbox[1]),
                            parseFloat(data[0].boundingbox[2]),
                            parseFloat(data[0].boundingbox[3])
                        ];
                    } else {
                        state.boundsOverride = null;
                    }
                    if (data[0].geojson) {
                        drawSearchBoundary(data[0].geojson);
                    } else {
                        clearSearchBoundary();
                    }
                    state.defaultLocation = [lon, lat];
                    state.searchedCityCenter = [lon, lat];
                    const isNeighborhood = ['suburb', 'neighbourhood', 'neighborhood', 'quarter', 'residential', 'postcode', 'postal_code'].includes(type) || 
                                           (state.boundsOverride && Math.abs(state.boundsOverride[1] - state.boundsOverride[0]) < 0.2);
                    state.defaultZoom = isNeighborhood ? 13.5 : 11;

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
                    state.searchedCity = normalizedQuery;
                    state.hasPannedLocally = false;
                    let cachedVal = [lon, lat];
                    if (state.boundsOverride) {
                        cachedVal = [lon, lat, ...state.boundsOverride];
                    }
                    if (data[0].geojson) {
                        if (cachedVal.length === 2) {
                            cachedVal.push(null, null, null, null);
                        }
                        cachedVal.push(data[0].geojson);
                    }
                    state.geocodeCache.set(normalizedQuery, cachedVal);

                    const titleEl = document.getElementById('activeMapTitle');
                    if (titleEl) titleEl.textContent = queryTrimmed;

                    const navInput = document.getElementById('unified-search-input');
                    if (navInput) {
                        navInput.value = queryTrimmed;
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
        state.boundsOverride = null;
        canonicalCity = 'San Francisco, CA';
        lowerCity = 'san francisco, ca';
        newLocation = [-122.4194, 37.7749];
        newZoom = 12;
        isNewHub = true;
    } else if (ukTerms.some(term => lowerCity.includes(term))) {
        state.boundsOverride = null;
        canonicalCity = 'London, UK';
        lowerCity = 'london, uk';
        newLocation = [-0.1276, 51.5072];
        newZoom = 12;
        isNewHub = true;
    } else if (indiaTerms.some(term => lowerCity.includes(term))) {
        state.boundsOverride = null;
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
    state.hasPannedLocally = false;

    const handleFlyTo = (coords, zoomVal) => {
        state.defaultLocation = coords;
        state.searchedCityCenter = coords;
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
        const normKey = normalizeLocationQuery(lowerCity);
        if (state.hubBoundaries && state.hubBoundaries[normKey]) {
            drawSearchBoundary(state.hubBoundaries[normKey]);
        } else {
            clearSearchBoundary();
        }
        handleFlyTo(newLocation, newZoom);
    } else {
        const cachedCoords = state.geocodeCache.get(lowerCity);
        if (cachedCoords && Array.isArray(cachedCoords) && cachedCoords.length >= 2) {
            if (cachedCoords.length >= 6 && cachedCoords[2] !== null) {
                state.boundsOverride = [cachedCoords[2], cachedCoords[3], cachedCoords[4], cachedCoords[5]];
            } else {
                state.boundsOverride = null;
            }
            if (cachedCoords.length >= 7 && cachedCoords[6]) {
                drawSearchBoundary(cachedCoords[6]);
            } else {
                clearSearchBoundary();
            }
            handleFlyTo([cachedCoords[0], cachedCoords[1]], 11);
        } else {
            const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(cityTitle)}&format=json&limit=1&polygon_geojson=1`;
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
                        let cachedVal = [lon, lat];
                        if (data[0].boundingbox && data[0].boundingbox.length === 4) {
                            const bbox = [
                                parseFloat(data[0].boundingbox[0]),
                                parseFloat(data[0].boundingbox[1]),
                                parseFloat(data[0].boundingbox[2]),
                                parseFloat(data[0].boundingbox[3])
                            ];
                            state.boundsOverride = bbox;
                            cachedVal = [lon, lat, ...bbox];
                        } else {
                            state.boundsOverride = null;
                        }
                        if (data[0].geojson) {
                            drawSearchBoundary(data[0].geojson);
                            if (cachedVal.length === 2) {
                                cachedVal.push(null, null, null, null);
                            }
                            cachedVal.push(data[0].geojson);
                        } else {
                            clearSearchBoundary();
                        }
                        state.geocodeCache.set(lowerCity, cachedVal);
                        handleFlyTo([lon, lat], 11);
                        return;
                    }
                }
                state.boundsOverride = null;
                handleFlyTo(newLocation, newZoom);
            })
            .catch(err => {
                console.warn('[Geocoder] Failed to geocode custom city query:', err);
                handleFlyTo(newLocation, newZoom);
            });
        }
    }
}


