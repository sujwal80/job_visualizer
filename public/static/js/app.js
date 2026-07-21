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
    updateSearchCity,
    executeUnifiedSearch,
    KNOWN_HUB_COORDINATES
} from './modules/router.js';
import { initResumeBuilder } from './modules/resume_builder.js';

// DOM Elements
const directoryList = document.getElementById('directory-list');
const detailsDrawer = document.getElementById('details-drawer');
const drawerContent = document.getElementById('drawer-content');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
const backDrawerBtn = document.getElementById('back-drawer-btn');
const searchInput = document.getElementById('unified-search-input');

const mobileToggleBtn = document.getElementById('mobile-toggle-btn');
const sidebar = document.getElementById('sidebar');
const resetMapBtn = document.getElementById('reset-map-btn');

const filterWorkType = document.getElementById('filter-work-type');
const filterExpLevel = document.getElementById('filter-exp-level');
const filterSalaryMin = document.getElementById('filter-salary-min');
const clearFiltersBtn = document.getElementById('clear-filters-btn');
const sidebarSearchInput = document.getElementById('sidebar-search-input');

showDirectoryLoading();

function _processFilteredStartupsResult(startups, preventScroll = false) {
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
}

function fetchFilteredStartups(preventScroll = false) {
    const queryParams = new URLSearchParams();
    const urlParams = new URLSearchParams(window.location.search);
    const qParam = urlParams.get('q') || urlParams.get('role');
    const cityParam = urlParams.get('city');

    if (cityParam) {
        state.searchedCity = cityParam.toLowerCase();
        queryParams.set('city', cityParam);
    } else if (state.searchedCity) {
        queryParams.set('city', state.searchedCity);
    }

    if (qParam) {
        queryParams.set('search', qParam);
    }


    if (state.currentFilters.salary_min) {
        queryParams.set('salary_min', state.currentFilters.salary_min);
    }
    if (state.currentFilters.exp_level) {
        queryParams.set('exp_level', state.currentFilters.exp_level);
    }
    if (state.currentFilters.work_type) {
        queryParams.set('work_type', state.currentFilters.work_type);
    }
    if (urlParams.get('has_jobs') === 'true' || urlParams.get('has_jobs') === '1') {
        queryParams.set('has_jobs', 'true');
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

    queryParams.set('has_jobs', 'true');

    const url = `/api/companies?${queryParams.toString()}`;

    // 1. Check QueryCache (0 network calls)
    if (state.queryCache.has(url)) {
        const cachedStartups = state.queryCache.get(url);
        _processFilteredStartupsResult(cachedStartups, preventScroll);
        return Promise.resolve(cachedStartups);
    }

    // 2. Check Request Coalescing (inFlightPromises)
    if (state.inFlightPromises.has(url)) {
        const existingPromise = state.inFlightPromises.get(url);
        existingPromise.then(startups => {
            _processFilteredStartupsResult(startups, preventScroll);
        }).catch(() => {});
        return existingPromise;
    }

    if (state.activeFetchController) {
        state.activeFetchController.abort();
    }
    state.activeFetchController = new AbortController();
    const signal = state.activeFetchController.signal;

    // 3. Dispatch fetch, store in inFlightPromises, populate cache
    const promise = safeFetch(url, { signal })
        .then(startups => {
            if (signal.aborted) return startups;
            if (!Array.isArray(startups)) return startups;

            const ttl = startups.length === 0 ? 60000 : 120000;
            state.queryCache.set(url, startups, ttl);

            _processFilteredStartupsResult(startups, preventScroll);
            return startups;
        })
        .catch(err => {
            if (err.name !== 'AbortError') {
                if (state.startupsData.length === 0) {
                    directoryList.replaceChildren(
                        createElement('div', { className: 'about-text', textContent: 'Failed to load company data.' })
                    );
                }
                throw err;
            }
            return new Promise(() => {});
        })
        .finally(() => {
            state.inFlightPromises.delete(url);
        });

    state.inFlightPromises.set(url, promise);
    return promise;
}

function fetchAndRender() {
    if (map && typeof map.resize === 'function') {
        map.resize();
    }

    const urlParams = new URLSearchParams(window.location.search);
    const cityParam = urlParams.get('city');
    const roleParam = urlParams.get('role');
    const qParam = urlParams.get('q');

    const activeQuery = qParam || roleParam;

    if (activeQuery) {
        // Set search input value
        const navInput = document.getElementById('unified-search-input');
        if (navInput) navInput.value = activeQuery;
    }

    if (cityParam) {
        updateSearchCity(cityParam, { skipPushState: true });
    } else {
        state.searchedCity = '';
        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = 'All locations';
        
        const navInput = document.getElementById('unified-search-input');
        if (navInput) {
            navInput.placeholder = "Search city/location or job title...";
        }
        fetchFilteredStartups();
    }
}




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
    const tokens = searchText.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) {
        return true;
    }

    const name = (startup.name || '').toString().toLowerCase();
    const desc = (startup.description || '').toString().toLowerCase();
    const city = (startup.city || '').toString().toLowerCase();
    const fNames = Array.isArray(startup.founder_names) ? startup.founder_names : [];
    const founders = Array.isArray(startup.founders) ? startup.founders : [];
    const jTitles = Array.isArray(startup.job_titles) ? startup.job_titles : [];
    const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);

    const matchesSearch = tokens.every(token => {
        return name.includes(token) ||
            desc.includes(token) ||
            city.includes(token) ||
            fNames.some(fn => (fn || '').toString().toLowerCase().includes(token)) ||
            founders.some(f => f && (f.name || '').toString().toLowerCase().includes(token)) ||
            jTitles.some(jt => (jt || '').toString().toLowerCase().includes(token)) ||
            jobs.some(j => j && (
                ((j.title || '').toString().toLowerCase().includes(token)) ||
                ((j.department || '').toString().toLowerCase().includes(token)) ||
                (Array.isArray(j.skills) && j.skills.some(s => (s || '').toString().toLowerCase().includes(token))) ||
                ((j.salary || '').toString().toLowerCase().includes(token)) ||
                ((j.experience || '').toString().toLowerCase().includes(token))
            ));
    });

    return matchesSearch;
}

function getSearchText() {
    const rawSearch = searchInput.value.toLowerCase().trim();
    if (state.searchedCity && rawSearch === state.searchedCity.toLowerCase().trim()) {
        return '';
    }
    return rawSearch;
}

function updateLocalMarkersVisualState() {
    const searchText = getSearchText();
    const sidebarSearchText = sidebarSearchInput ? sidebarSearchInput.value.toLowerCase().trim() : '';
    const isFilteringActive = searchText !== '' || sidebarSearchText !== '';

    state.startupsData.forEach(startup => {
        const marker = state.markersMap.get(startup.id) || (state.currentSelectedId === startup.id ? state.tempRemoteMarker : null);
        if (!marker || typeof marker.getElement !== 'function') return;
        const element = marker.getElement();
        if (!element) return;
        const isSelected = state.currentSelectedId === startup.id;
        
        let isMatch = checkStartupMatch(startup, searchText);
        if (isMatch && sidebarSearchText) {
            const name = (startup.name || '').toLowerCase();
            const desc = (startup.description || '').toLowerCase();
            const industry = (startup.industry || '').toLowerCase();
            const skills = Array.isArray(startup.skills) ? startup.skills.map(s => String(s).toLowerCase()) : [];
            const titles = Array.isArray(startup.job_titles) ? startup.job_titles.map(t => String(t).toLowerCase()) : [];
            
            isMatch = name.includes(sidebarSearchText) ||
                      desc.includes(sidebarSearchText) ||
                      industry.includes(sidebarSearchText) ||
                      skills.some(s => s.includes(sidebarSearchText)) ||
                      titles.some(t => t.includes(sidebarSearchText));
        }

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
    const searchText = getSearchText();
    const sidebarSearchText = sidebarSearchInput ? sidebarSearchInput.value.toLowerCase().trim() : '';

    const filtered = state.startupsData.filter(startup => checkStartupMatch(startup, searchText)).filter(startup => {
        if (sidebarSearchText) {
            const name = (startup.name || '').toLowerCase();
            const desc = (startup.description || '').toLowerCase();
            const industry = (startup.industry || '').toLowerCase();
            const skills = Array.isArray(startup.skills) ? startup.skills.map(s => String(s).toLowerCase()) : [];
            const titles = Array.isArray(startup.job_titles) ? startup.job_titles.map(t => String(t).toLowerCase()) : [];
            
            return name.includes(sidebarSearchText) ||
                   desc.includes(sidebarSearchText) ||
                   industry.includes(sidebarSearchText) ||
                   skills.some(s => s.includes(sidebarSearchText)) ||
                   titles.some(t => t.includes(sidebarSearchText));
        }
        return true;
    });

    console.log(`[DEBUG applyFiltering] searchText="${searchText}" sidebarSearchText="${sidebarSearchText}" startupsData.length=${state.startupsData.length} filtered.length=${filtered.length}`);

    renderDirectory(filtered, (searchText || sidebarSearchText) ? 'No companies match your criteria' : null);
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

function handleFiltersChange() {
    state.currentFilters.work_type = filterWorkType ? filterWorkType.value : '';
    state.currentFilters.exp_level = filterExpLevel ? filterExpLevel.value : '';
    state.currentFilters.salary_min = filterSalaryMin ? filterSalaryMin.value : '';
    
    fetchFilteredStartups().then(() => {
        if (state.currentSelectedId !== null) {
            selectAndOpenStartup(state.currentSelectedId);
        }
    });
}

let filtersTimeout = null;
function handleDebouncedFiltersChange() {
    if (filtersTimeout) clearTimeout(filtersTimeout);
    filtersTimeout = setTimeout(handleFiltersChange, 200);
}

// Attach Event Listeners
window.addEventListener('hashchange', handleHashRouting);

if (searchInput) searchInput.addEventListener('input', handleDebouncedInput);
if (sidebarSearchInput) sidebarSearchInput.addEventListener('input', handleDebouncedInput);

if (filterWorkType) filterWorkType.addEventListener('change', handleFiltersChange);
if (filterExpLevel) filterExpLevel.addEventListener('change', handleFiltersChange);
if (filterSalaryMin) filterSalaryMin.addEventListener('change', handleFiltersChange);

if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener('click', () => {
        if (filterWorkType) filterWorkType.value = '';
        if (filterExpLevel) filterExpLevel.value = '';
        if (filterSalaryMin) filterSalaryMin.value = '';
        
        state.currentFilters.work_type = '';
        state.currentFilters.exp_level = '';
        state.currentFilters.salary_min = '';
        
        handleFiltersChange();
    });
}


map.on('click', () => {
    console.log('[DEBUG map click] clearing hash');
    window.location.hash = '';
});

if (closeDrawerBtn) {
    closeDrawerBtn.addEventListener('click', () => {
        console.log('[DEBUG closeDrawerBtn click] clearing hash');
        window.location.hash = '';
    });
}

if (backDrawerBtn) {
    backDrawerBtn.addEventListener('click', () => {
        console.log('[DEBUG backDrawerBtn click] clearing hash');
        window.location.hash = '';
    });
}

function resetMapView() {
    lockProgrammaticMove(2500);
    map.flyTo({
        center: state.defaultLocation,
        zoom: state.defaultZoom,
        speed: 3.0,
        essential: true
    });
}

if (resetMapBtn) {
    resetMapBtn.addEventListener('click', resetMapView);
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


window.addEventListener('popstate', () => {
    console.log('[DEBUG popstate event] window.location.search="' + window.location.search + '" state.lastQueryString="' + state.lastQueryString + '" hash="' + window.location.hash + '" currentSelectedId=' + state.currentSelectedId);
    if (window.location.search === state.lastQueryString) {
        console.log('[DEBUG popstate event] search matches lastQueryString, calling handleHashRouting');
        handleHashRouting();
        return;
    }
    console.log('[DEBUG popstate event] search changed, processing full search popstate');
    state.lastQueryString = window.location.search;
    const urlParams = new URLSearchParams(window.location.search);
    const cityParam = urlParams.get('city');
    const qParam = urlParams.get('q');
    const query = cityParam || qParam || '';

    const unifiedInput = document.getElementById('unified-search-input');
    if (unifiedInput) {
        unifiedInput.value = query;
    }

    const titleEl = document.getElementById('activeMapTitle');
    if (titleEl) {
        titleEl.textContent = query || 'All locations';
    }

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

    if (cityParam) {
        executeUnifiedSearch(cityParam, { skipPushState: true });
    } else if (qParam) {
        executeUnifiedSearch(qParam, { skipPushState: true });
    } else {
        state.searchedCity = '';
        fetchFilteredStartups(true);
    }
});

// Expose interface to window for E2E tests and index.html compatibility
window.updateSearchCity = updateSearchCity;
window.resetMapView = resetMapView;
window.executeUnifiedSearch = executeUnifiedSearch;

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
    getTempRemoteMarker: () => state.tempRemoteMarker,
    resetMapView,
    executeUnifiedSearch,
    state
};

checkAuthStatus();
handleHashRouting();
initResumeBuilder();
fetchAndRender();

