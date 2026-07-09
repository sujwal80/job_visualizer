import { state, lockProgrammaticMove } from './modules/state.js';
import { createElement, showToast, getDomain } from './modules/utils.js';
import { safeFetch, checkAuthStatus } from './modules/api.js';
import {
    map,
    clearAllMarkers,
    initializeMarkers,
    updateMarkersDiff,
    updateMarkersVisualState,
    industryColors,
    defaultColor
} from './modules/map_manager.js';
import {
    updateDashboardStats,
    showDirectoryLoading,
    renderDirectory,
    renderDrawerDetails,
    selectAndOpenStartup,
    _processOpenStartup,
    scrollToCard,
    getJobSourceButtonStyle
} from './modules/ui_manager.js';
import {
    handleHashRouting,
    updateSearchCity
} from './modules/router.js';

// DOM Elements
const directoryList = document.getElementById('directory-list');
const detailsDrawer = document.getElementById('details-drawer');
const drawerContent = document.getElementById('drawer-content');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
const searchInput = document.getElementById('search-input');

const quickTabs = document.querySelectorAll('#quick-industry-tabs .tab-btn');
const mobileToggleBtn = document.getElementById('mobile-toggle-btn');
const sidebar = document.getElementById('sidebar');
const resetMapBtn = document.getElementById('reset-map-btn');

let currentSelectedIndustry = "";

// Initialize geocode/hub routing on load
const urlParams = new URLSearchParams(window.location.search);
state.searchedCity = (urlParams.get('city') || '').toLowerCase();

const usaTerms = ["san", "francisco", "sf", "ca", "usa", "us", "united states", "america", "california"];
const ukTerms = ["london", "uk", "england", "united kingdom", "gb", "great britain"];

let isHub = false;
if (usaTerms.some(term => state.searchedCity.includes(term))) {
    state.defaultLocation = [-122.4194, 37.7749];
    state.defaultZoom = 12;
    isHub = true;
} else if (ukTerms.some(term => state.searchedCity.includes(term))) {
    state.defaultLocation = [-0.1276, 51.5072];
    state.defaultZoom = 12;
    isHub = true;
} else if (state.searchedCity.includes('bengaluru') || state.searchedCity.includes('bangalore') || state.searchedCity.includes('india') || state.searchedCity === 'in' || state.searchedCity === 'blr') {
    state.defaultLocation = [77.5946, 12.9716];
    state.defaultZoom = 11;
    isHub = true;
}

showDirectoryLoading();

if (isHub || !state.searchedCity) {
    map.once('load', () => {
        lockProgrammaticMove(2500);
        map.flyTo({
            center: state.defaultLocation,
            zoom: state.defaultZoom,
            speed: 3.0,
            essential: true
        });
    });
} else {
    const geoUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(state.searchedCity)}&format=json&limit=1`;
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
                state.defaultLocation = [lon, lat];
                state.defaultZoom = 11;
                lockProgrammaticMove(2500);
                map.flyTo({
                    center: state.defaultLocation,
                    zoom: state.defaultZoom,
                    speed: 3.0,
                    essential: true
                });
            }
        }
    })
    .catch(err => {
        console.warn('[Geocoder] Failed to geocode custom city query:', err);
        lockProgrammaticMove(2500);
        map.flyTo({
            center: state.defaultLocation,
            zoom: state.defaultZoom,
            speed: 3.0,
            essential: true
        });
    });
}

function fetchFilteredStartups(preventScroll = false) {
    if (state.activeFetchController) {
        state.activeFetchController.abort();
    }
    state.activeFetchController = new AbortController();
    const signal = state.activeFetchController.signal;

    const queryParams = new URLSearchParams();
    if (state.searchedCity) {
        queryParams.set('city', state.searchedCity);
    }

    const searchText = searchInput.value.trim();
    if (searchText) {
        queryParams.set('search', searchText);
    }



    if (currentSelectedIndustry) {
        queryParams.set('industry', currentSelectedIndustry);
    }

    try {
        if (!state.searchedCity && map && map.getContainer() && map.getContainer().clientWidth > 0) {
            const bounds = map.getBounds();
            if (bounds && !isNaN(bounds.getSouth()) && !isNaN(bounds.getNorth()) && !isNaN(bounds.getWest()) && !isNaN(bounds.getEast())) {
                let minLat = Math.max(-90, Math.min(90, bounds.getSouth()));
                let maxLat = Math.max(-90, Math.min(90, bounds.getNorth()));
                let minLng = bounds.getWest();
                let maxLng = bounds.getEast();

                if (maxLng - minLng >= 360) {
                    minLng = -180;
                    maxLng = 180;
                } else {
                    const wrapLng = (lng) => {
                        let w = (lng + 180) % 360;
                        if (w < 0) w += 360;
                        return w - 180;
                    };
                    minLng = wrapLng(minLng);
                    maxLng = wrapLng(maxLng);
                }

                queryParams.set('min_lat', minLat);
                queryParams.set('max_lat', maxLat);
                queryParams.set('min_lng', minLng);
                queryParams.set('max_lng', maxLng);
            }
        }
    } catch (e) {}

    queryParams.set('limit', '500');

    const url = `/api/startups?${queryParams.toString()}`;
    return safeFetch(url, { signal })
        .then(startups => {
            if (signal.aborted) return;
            if (!Array.isArray(startups)) return;

            state.startupsData = startups;
            applyFiltering();
            
            updateMarkersDiff(state.startupsData);
            updateMarkersVisualState();

            if (state.currentSelectedId !== null && detailsDrawer.classList.contains('active')) {
                const cached = state.profileCache.get(state.currentSelectedId);
                if (cached) {
                    renderDrawerDetails(cached);
                } else {
                    const startup = state.startupsData.find(s => s.id === state.currentSelectedId);
                    if (startup) {
                        renderDrawerDetails(startup);
                    }
                }
                if (!preventScroll) {
                    scrollToCard(state.currentSelectedId);
                }
            }
            handleHashRouting();
        })
        .catch(err => {
            if (err.name !== 'AbortError') {
                if (state.startupsData.length === 0) {
                    directoryList.replaceChildren(
                        createElement('div', { className: 'about-text', textContent: 'Failed to load company data.' })
                    );
                }
            }
        });
}

function fetchAndRender() {
    fetchFilteredStartups();
}

fetchAndRender();

let viewportDebounceTimer = null;
map.on('moveend', (e) => {
    if (state.isProgrammaticMove || (e && !e.originalEvent)) {
        state.isProgrammaticMove = false;
        if (state.programmaticMoveTimeout) {
            clearTimeout(state.programmaticMoveTimeout);
            state.programmaticMoveTimeout = null;
        }
        return;
    }
    if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
    viewportDebounceTimer = setTimeout(() => {
        try {
            if (!map || !map.getContainer()) return;
            const container = map.getContainer();
            if (container.clientWidth === 0 || container.clientHeight === 0) return;
            const bounds = map.getBounds();
            if (!bounds || isNaN(bounds.getSouth()) || isNaN(bounds.getNorth()) || isNaN(bounds.getWest()) || isNaN(bounds.getEast())) return;
        } catch (err) {
            return;
        }
        fetchFilteredStartups(true);
    }, 300);
});

function checkStartupMatch(startup, searchText) {
    if (!startup || typeof startup !== 'object') return false;
    const name = (startup.name || '').toString().toLowerCase();
    const desc = (startup.description || '').toString().toLowerCase();
    const city = (startup.city || '').toString().toLowerCase();
    const fNames = Array.isArray(startup.founder_names) ? startup.founder_names : [];
    const founders = Array.isArray(startup.founders) ? startup.founders : [];
    const jTitles = Array.isArray(startup.job_titles) ? startup.job_titles : [];
    const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);

    const matchesSearch = searchText === '' ||
        name.includes(searchText) ||
        desc.includes(searchText) ||
        city.includes(searchText) ||
        fNames.some(fn => (fn || '').toString().toLowerCase().includes(searchText)) ||
        founders.some(f => f && (f.name || '').toString().toLowerCase().includes(searchText)) ||
        jTitles.some(jt => (jt || '').toString().toLowerCase().includes(searchText)) ||
        jobs.some(j => j && (
            ((j.title || '').toString().toLowerCase().includes(searchText)) ||
            ((j.department || '').toString().toLowerCase().includes(searchText)) ||
            (Array.isArray(j.skills) && j.skills.some(s => (s || '').toString().toLowerCase().includes(searchText))) ||
            ((j.salary || '').toString().toLowerCase().includes(searchText)) ||
            ((j.experience || '').toString().toLowerCase().includes(searchText))
        ));
    const matchesIndustry = currentSelectedIndustry === '' || (startup.industry || '') === currentSelectedIndustry;
    return matchesSearch && matchesIndustry;
}

function updateLocalMarkersVisualState() {
    const searchText = searchInput.value.toLowerCase().trim();
    const isFilteringActive = searchText !== '' || currentSelectedIndustry !== '';

    state.startupsData.forEach(startup => {
        const marker = state.markersMap.get(startup.id) || (state.currentSelectedId === startup.id ? state.tempRemoteMarker : null);
        if (!marker || typeof marker.getElement !== 'function') return;
        const element = marker.getElement();
        if (!element) return;
        const isSelected = state.currentSelectedId === startup.id;
        const isMatch = checkStartupMatch(startup, searchText);

        const isFaded = isFilteringActive && !isMatch;
        const img = element.querySelector('.logo-marker-thumbnail');
        const color = industryColors[startup.industry] || defaultColor;

        if (img) {
            img.className = 'logo-marker-thumbnail' + (isSelected ? ' active' : '') + (isFaded ? ' faded' : '');
            img.style.border = isSelected ? `3px solid ${color}` : (isFaded ? '1px solid #cbd5e1' : `2.5px solid ${color}`);
        }

        if (isSelected) element.classList.add('active');
        else element.classList.remove('active');

        if (isFaded) {
            element.classList.add('faded');
            element.style.display = 'none';
        } else {
            element.classList.remove('faded');
            element.style.display = '';
        }

        element.style.zIndex = isSelected ? '1000' : (isMatch ? '100' : '10');
    });
}

function applyFiltering() {
    const searchText = searchInput.value.toLowerCase().trim();

    const filtered = state.startupsData.filter(startup => checkStartupMatch(startup, searchText));

    renderDirectory(filtered);
    updateDashboardStats(filtered);
    updateLocalMarkersVisualState();
    if (state.currentSelectedId !== null && detailsDrawer.classList.contains('active')) {
        const startup = state.profileCache.get(state.currentSelectedId) || state.startupsData.find(s => s.id === state.currentSelectedId);
        if (startup) {
            renderDrawerDetails(startup);
        }
    }
}

let filterRafId = null;
let inputTimeout = null;

function scheduleFiltering() {
    if (filterRafId) cancelAnimationFrame(filterRafId);
    filterRafId = requestAnimationFrame(() => {
        applyFiltering();
    });
}

function handleDebouncedInput() {
    if (inputTimeout) clearTimeout(inputTimeout);
    inputTimeout = setTimeout(scheduleFiltering, 150);
}

// Attach Event Listeners
window.addEventListener('hashchange', handleHashRouting);

searchInput.addEventListener('input', handleDebouncedInput);


quickTabs.forEach(btn => {
    btn.addEventListener('click', () => {
        quickTabs.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentSelectedIndustry = btn.getAttribute('data-industry') || "";
        applyFiltering();
    });
});

map.on('click', () => {
    window.location.hash = '';
});

if (closeDrawerBtn) {
    closeDrawerBtn.addEventListener('click', () => {
        window.location.hash = '';
    });
}

if (resetMapBtn) {
    resetMapBtn.addEventListener('click', () => {
        lockProgrammaticMove(2500);
        map.flyTo({
            center: state.defaultLocation,
            zoom: state.defaultZoom,
            speed: 3.0,
            essential: true
        });
    });
}

if (mobileToggleBtn) {
    mobileToggleBtn.addEventListener('click', () => {
        const isOpen = sidebar.classList.contains('active');
        if (isOpen) {
            sidebar.classList.remove('active');
            mobileToggleBtn.textContent = 'Show Directory';
        } else {
            sidebar.classList.add('active');
            mobileToggleBtn.textContent = 'Show Map';
        }
    });
}

function checkViewportResilience(width, height) {
    const result = {
        viewport: `${width}x${height}`,
        valid: true,
        errors: [],
        elements: {}
    };
    try {
        const isMobile = width <= 900;
        const isTablet = width > 480 && width <= 900;
        const isDesktop = width > 900;

        if (sidebar) {
            const sidebarRect = sidebar.getBoundingClientRect();
            result.elements.sidebar = { visible: sidebarRect.width > 0, width: sidebarRect.width };
            if (isDesktop && sidebarRect.width === 0 && sidebar.style.display !== 'none') {
                result.valid = false;
                result.errors.push('Sidebar unexpectedly hidden on desktop viewport');
            }
        }
        if (detailsDrawer) {
            const drawerRect = detailsDrawer.getBoundingClientRect();
            result.elements.detailsDrawer = { active: detailsDrawer.classList.contains('active'), width: drawerRect.width };
            if (detailsDrawer.classList.contains('active')) {
                if (isMobile && drawerRect.width > width + 1) {
                    result.valid = false;
                    result.errors.push(`Details drawer width (${drawerRect.width}px) exceeds mobile viewport (${width}px)`);
                }
            }
        }
        const nav = document.querySelector('.top-navbar');
        if (nav) {
            const navRect = nav.getBoundingClientRect();
            if (navRect.width > width + 1) {
                result.valid = false;
                result.errors.push(`Navbar overflow: width (${navRect.width}px) exceeds viewport (${width}px)`);
            }
        }
    } catch (e) {
        result.valid = false;
        result.errors.push(`Exception during layout check: ${e.message}`);
    }
    return result;
}

window.addEventListener('resize', () => {
    try {
        if (map && typeof map.resize === 'function') map.resize();
        const width = window.innerWidth || document.documentElement.clientWidth || (document.body && document.body.clientWidth) || 0;
        if (width > 900 && sidebar && sidebar.classList.contains('active')) {
            sidebar.classList.remove('active');
            if (mobileToggleBtn) mobileToggleBtn.textContent = 'Show Directory';
        }
    } catch (err) {
        console.warn('Resize adaptation handled safely:', err);
    }
});

// Setup auth logout click handler
const navLogoutBtn = document.getElementById('nav-logout-btn');
if (navLogoutBtn) {
    navLogoutBtn.addEventListener('click', () => {
        safeFetch('/api/auth/logout', { method: 'POST' })
            .then(() => {
                window.location.reload();
            })
            .catch(() => window.location.reload());
    });
}

// Initial checks
checkAuthStatus();
handleHashRouting();

// Expose interface to window for E2E tests and index.html compatibility
window.updateSearchCity = updateSearchCity;

window.WorldTechApp = {
    createElement,
    showToast,
    safeFetch,
    getDomain,
    createLogoContent: (startup) => {
        const domain = getDomain(startup);
        const color = industryColors[startup.industry] || defaultColor;
        const container = createElement('div', { className: 'logo-marker-container' });
        const fallback = createElement('div', { className: 'logo-marker-fallback' }, [
            String(startup.name || 'S').substring(0, 1).toUpperCase()
        ]);
        fallback.style.backgroundColor = color;
        fallback.style.border = '2px solid #ffffff';
        container.appendChild(fallback);
        return container;
    },
    checkStartupMatch,
    updateDashboardStats,
    clearAllMarkers,
    initializeMarkers,
    updateMarkersDiff,
    applyFiltering,
    scheduleFiltering,
    renderDirectory,
    renderDrawerDetails,
    selectAndOpenStartup,
    _processOpenStartup,
    scrollToCard,
    handleHashRouting,
    checkViewportResilience,
    checkAuthStatus,
    map,
    fetchFilteredStartups,
    getJobSourceButtonStyle,
    lockProgrammaticMove,
    getTempRemoteMarker: () => state.tempRemoteMarker
};
