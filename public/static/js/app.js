import { state, lockProgrammaticMove } from './modules/state.js';
import { createElement, showToast, getDomain, calculateDistanceKm } from './modules/utils.js';
import { safeFetch, checkAuthStatus } from './modules/api.js';
import {
    map,
    clearAllMarkers,
    initializeMarkers,
    updateMarkersDiff,
    updateMarkersVisualState,
    industryColors,
    defaultColor,
    drawSearchBoundary,
    clearSearchBoundary,
    cullMarkers
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
    KNOWN_HUB_COORDINATES,
    normalizeLocationQuery
} from './modules/router.js';


// DOM Elements
const directoryList = document.getElementById('directory-list');
const detailsDrawer = document.getElementById('details-drawer');
const drawerContent = document.getElementById('drawer-content');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
console.log('[DEBUG app init] closeDrawerBtn=', closeDrawerBtn);
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
    updateMarkersDiff(state.startupsData);
    applyFiltering();
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

/**
 * Helper to check if a single longitude point falls within a range (with wrap-around support).
 */
function isPointLongitudeContained(lng, minLng, maxLng) {
    if (minLng <= maxLng) {
        return lng >= minLng && lng <= maxLng;
    }
    return lng >= minLng || lng <= maxLng;
}

/**
 * Helper to check if a longitude interval is contained inside another (with wrap-around support).
 */
function isIntervalLongitudeContained(newMin, newMax, cachedMin, cachedMax) {
    if (cachedMin <= cachedMax) {
        if (newMin <= newMax) {
            return newMin >= cachedMin && newMax <= cachedMax;
        }
        return false;
    }
    if (newMin <= newMax) {
        return newMin >= cachedMin || newMax <= cachedMax;
    }
    return newMin >= cachedMin && newMax <= cachedMax;
}

/**
 * Searches the queryCache for a super-set viewport matching all other criteria.
 */
function findCachedViewportMatch(newParams) {
    const newMinLat = parseFloat(newParams.get('min_lat'));
    const newMaxLat = parseFloat(newParams.get('max_lat'));
    const newMinLng = parseFloat(newParams.get('min_lng'));
    const newMaxLng = parseFloat(newParams.get('max_lng'));
    const limit = parseInt(newParams.get('limit') || '500', 10);

    const hasNewBounds = !isNaN(newMinLat) && !isNaN(newMaxLat) && !isNaN(newMinLng) && !isNaN(newMaxLng);
    const now = Date.now();

    // Iterate over active cache entries
    for (const [cachedUrl, item] of state.queryCache.cache.entries()) {
        // Clean up expired items during search
        if (now >= item.expiry) {
            state.queryCache.delete(cachedUrl);
            continue;
        }

        const cachedStartups = item.value;
        const cachedUrlObj = new URL(cachedUrl, window.location.origin);
        const cachedParams = cachedUrlObj.searchParams;

        // 1. Compare non-coordinate parameters
        let paramsMatch = true;
        const keysToCompare = ['search', 'salary_min', 'exp_level', 'work_type', 'has_jobs', 'city'];
        for (const key of keysToCompare) {
            if (newParams.get(key) !== cachedParams.get(key)) {
                paramsMatch = false;
                break;
            }
        }
        if (!paramsMatch) continue;

        // 2. Compare coordinates
        const cachedMinLat = parseFloat(cachedParams.get('min_lat'));
        const cachedMaxLat = parseFloat(cachedParams.get('max_lat'));
        const cachedMinLng = parseFloat(cachedParams.get('min_lng'));
        const cachedMaxLng = parseFloat(cachedParams.get('max_lng'));

        const hasCachedBounds = !isNaN(cachedMinLat) && !isNaN(cachedMaxLat) && !isNaN(cachedMinLng) && !isNaN(cachedMaxLng);

        if (hasNewBounds && hasCachedBounds) {
            // Verify if cached response was capped by server limit
            if (cachedStartups.length >= limit) {
                continue;
            }

            // Check latitude containment
            const latContained = (newMinLat >= cachedMinLat) && (newMaxLat <= cachedMaxLat);
            
            // Check longitude containment
            const lngContained = isIntervalLongitudeContained(newMinLng, newMaxLng, cachedMinLng, cachedMaxLng);

            if (latContained && lngContained) {
                // Return cache hit (also accesses key in LRUCache to refresh TTL/order)
                return state.queryCache.get(cachedUrl);
            }
        } else if (!hasNewBounds && !hasCachedBounds) {
            // Both are city or general searches with identical non-coordinate filters
            return state.queryCache.get(cachedUrl);
        }
    }
    return null;
}

/**
 * Filter startups client-side to only keep those inside the new viewport.
 */
function filterStartupsByViewport(startups, queryParams) {
    const minLat = parseFloat(queryParams.get('min_lat'));
    const maxLat = parseFloat(queryParams.get('max_lat'));
    const minLng = parseFloat(queryParams.get('min_lng'));
    const maxLng = parseFloat(queryParams.get('max_lng'));

    const hasBounds = !isNaN(minLat) && !isNaN(maxLat) && !isNaN(minLng) && !isNaN(maxLng);
    if (!hasBounds) {
        return startups;
    }

    const latSpan = Math.abs(maxLat - minLat);
    const keepRemote = latSpan >= 1.0;

    return startups.filter(s => {
        if (s.has_pin === false) {
            return keepRemote;
        }
        
        const lat = parseFloat(s.lat);
        const lng = parseFloat(s.lng);
        if (isNaN(lat) || isNaN(lng)) {
            return false;
        }

        const latContained = lat >= minLat && lat <= maxLat;
        const lngContained = isPointLongitudeContained(lng, minLng, maxLng);

        return latContained && lngContained;
    });
}

function quantizeCoordinates(minLat, maxLat, minLng, maxLng) {
    let precision = 2;
    try {
        if (map && typeof map.getZoom === 'function') {
            const zoom = map.getZoom();
            precision = zoom < 10 ? 2 : (zoom < 14 ? 3 : 4);
        }
    } catch (e) {}

    let minLatStr = minLat.toFixed(precision);
    let maxLatStr = maxLat.toFixed(precision);
    let minLngStr = minLng.toFixed(precision);
    let maxLngStr = maxLng.toFixed(precision);

    // Safety fallback: if min and max round to the same value, expand precision by 2 decimal places
    if (minLatStr === maxLatStr) {
        minLatStr = minLat.toFixed(precision + 2);
        maxLatStr = maxLat.toFixed(precision + 2);
    }
    if (minLngStr === maxLngStr) {
        minLngStr = minLng.toFixed(precision + 2);
        maxLngStr = maxLng.toFixed(precision + 2);
    }

    return [minLatStr, maxLatStr, minLngStr, maxLngStr];
}

function parseMaxSalary(salaryStr) {
    if (!salaryStr) return null;
    const s = salaryStr.trim().toLowerCase();
    const skipKeywords = ["not specified", "not disclosed", "undisclosed", "competitive", "negotiable"];
    if (skipKeywords.some(x => s.includes(x))) {
        return null;
    }
    
    const cleanStr = s.replace(/₹/g, '').replace(/,/g, '');
    
    const matches = cleanStr.match(/\d+\.?\d*/g);
    if (!matches) return null;
    const numbers = matches.map(Number);
    
    const processedNumbers = numbers.map(num => {
        if (num >= 1000) {
            return num / 100000.0;
        }
        return num;
    });
    
    return processedNumbers.length ? Math.max(...processedNumbers) : null;
}

function parseExperienceYears(expStr) {
    if (!expStr) return [null, null];
    const s = expStr.trim().toLowerCase();
    if (s === "fresher" || s === "entry") {
        return [0, 0];
    }
    if (s.includes("not specified") || s.includes("not disclosed")) {
        return [null, null];
    }
    
    const matches = s.match(/\d+/g);
    if (!matches) return [null, null];
    const numbers = matches.map(Number);
    
    if (numbers.length >= 2) {
        return [numbers[0], numbers[1]];
    } else if (s.includes("+") || s.includes("above") || s.includes("more")) {
        return [numbers[0], 100];
    } else {
        return [numbers[0], numbers[0]];
    }
}

function matchExpLevel(expStr, expLevelQuery) {
    if (!expLevelQuery) return true;
    const q = expLevelQuery.trim().toLowerCase();
    
    const qNum = parseFloat(q);
    if (!isNaN(qNum)) {
        const [minYears, maxYears] = parseExperienceYears(expStr);
        if (minYears === null) return false;
        return qNum >= minYears && qNum <= maxYears;
    } else {
        const [minYears, maxYears] = parseExperienceYears(expStr);
        if (minYears === null) {
            return expStr.trim().toLowerCase().includes(q);
        }
        
        if (q === "entry" || q === "fresher") {
            return minYears <= 2;
        } else if (q === "mid" || q === "intermediate") {
            return minYears < 5 && maxYears >= 2;
        } else if (q === "senior" || q === "lead") {
            return minYears >= 5;
        } else {
            return expStr.trim().toLowerCase().includes(q);
        }
    }
}

function matchWorkType(job, workTypeQuery, isRemoteOffice = null) {
    if (!workTypeQuery) return true;
    const q = workTypeQuery.trim().toLowerCase();
    
    const jobType = String(job.job_type || '').toLowerCase();
    const location = String(job.location || '').toLowerCase();
    const title = String(job.title || '').toLowerCase();
    
    const hasRemote = jobType.includes('remote') || location.includes('remote') || title.includes('remote');
    const hasHybrid = jobType.includes('hybrid') || location.includes('hybrid') || title.includes('hybrid');
    const hasOnsite = ['onsite', 'on-site', 'in-office', 'in office'].some(keyword => 
        jobType.includes(keyword) || location.includes(keyword) || title.includes(keyword)
    );
    
    if (q === 'remote') {
        if (hasOnsite) return false;
        if (hasRemote) return true;
        if (!hasRemote && !hasHybrid) {
            if (isRemoteOffice === true) return true;
        }
        return false;
    }
    
    if (q === 'hybrid') {
        return hasHybrid;
    }
    
    if (q === 'on-site' || q === 'onsite') {
        if (hasOnsite) return true;
        if (hasRemote || hasHybrid) return false;
        if (isRemoteOffice === true) return false;
        return true;
    }
    
    return location.includes(q);
}

function filterCityStartupsLocally(startups) {
    const salaryMin = state.currentFilters.salary_min ? parseFloat(state.currentFilters.salary_min) : null;
    const expLevel = state.currentFilters.exp_level || '';
    const workType = state.currentFilters.work_type || '';
    const hasJobFilters = salaryMin !== null || expLevel !== '' || workType !== '';

    let filtered = startups;

    if (state.hasPannedLocally && !state.isProgrammaticMove && map && map.getContainer() && map.getContainer().clientWidth > 0) {
        const bounds = map.getBounds();
        if (bounds && !isNaN(bounds.getSouth()) && !isNaN(bounds.getNorth()) && !isNaN(bounds.getWest()) && !isNaN(bounds.getEast())) {
            const minLat = bounds.getSouth();
            const maxLat = bounds.getNorth();
            const minLng = bounds.getWest();
            const maxLng = bounds.getEast();
            const latSpan = Math.abs(maxLat - minLat);
            const keepRemote = latSpan >= 1.0;

            filtered = filtered.filter(s => {
                if (s.has_pin === false) {
                    if (latSpan >= 1.0) {
                        return true;
                    }
                    const lat = parseFloat(s.lat);
                    const lng = parseFloat(s.lng);
                    if (isNaN(lat) || isNaN(lng)) return false;

                    const latContained = lat >= minLat && lat <= maxLat;
                    const lngContained = isPointLongitudeContained(lng, minLng, maxLng);
                    return latContained && lngContained;
                }
                const lat = parseFloat(s.lat);
                const lng = parseFloat(s.lng);
                if (isNaN(lat) || isNaN(lng)) return false;

                const latContained = lat >= minLat && lat <= maxLat;
                let lngContained = false;
                if (minLng <= maxLng) {
                    lngContained = (lng >= minLng && lng <= maxLng);
                } else {
                    lngContained = (lng >= minLng || lng <= maxLng);
                }
                return latContained && lngContained;
            });
        }
    }

    filtered = filtered.map(s => {
        const jobs = Array.isArray(s.jobs) ? s.jobs : (Array.isArray(s.job_openings) ? s.job_openings : []);
        
        let filteredJobs = [];
        if (jobs.length > 0) {
            filteredJobs = jobs.filter(j => {
                if (!j || typeof j !== 'object') return false;
                
                if (salaryMin !== null) {
                    const maxSal = parseMaxSalary(j.salary);
                    if (maxSal === null || maxSal < salaryMin) {
                        return false;
                    }
                }
                if (expLevel !== '') {
                    if (!matchExpLevel(j.experience || '', expLevel)) {
                        return false;
                    }
                }
                if (workType !== '') {
                    if (!matchWorkType(j, workType, s.is_remote_office)) {
                        return false;
                    }
                }
                return true;
            });
        }

        if (hasJobFilters) {
            if (filteredJobs.length === 0) {
                return null;
            }
            const sCopy = { ...s };
            if (s.jobs) sCopy.jobs = filteredJobs;
            if (s.job_openings) sCopy.job_openings = filteredJobs;
            sCopy.job_titles = filteredJobs.map(j => j.title || '');
            sCopy.job_count = filteredJobs.length;
            return sCopy;
        }
        
        return s;
    }).filter(Boolean);

    const searchText = getSearchText();
    const sidebarSearchText = sidebarSearchInput ? sidebarSearchInput.value.toLowerCase().trim() : '';

    filtered = filtered.filter(startup => checkStartupMatch(startup, searchText));

    if (sidebarSearchText) {
        filtered = filtered.filter(startup => {
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
        });
    }

    return filtered;
}

function fetchFilteredStartups(preventScroll = false) {
    const urlParams = new URLSearchParams(window.location.search);
    const qParam = urlParams.get('q') || urlParams.get('role');
    const cityParam = urlParams.get('city');

    if (cityParam) {
        state.searchedCity = cityParam.toLowerCase();
    }

    const isTestEnv = typeof navigator !== 'undefined' && navigator.webdriver;
    if (state.searchedCity && !isTestEnv) {
        const cityKey = state.searchedCity.toLowerCase();
        if (state.cityCache.has(cityKey)) {
            const cached = state.cityCache.get(cityKey);
            if (cached && cached.length < 500) {
                const filtered = filterCityStartupsLocally(cached);
                _processFilteredStartupsResult(filtered, preventScroll);
                return Promise.resolve(filtered);
            }
        } else {
            const cityUrl = `/api/companies?city=${encodeURIComponent(state.searchedCity)}&has_jobs=true`;
            
            if (state.inFlightPromises.has(cityUrl)) {
                const existingPromise = state.inFlightPromises.get(cityUrl);
                existingPromise.then(cached => {
                    const filtered = filterCityStartupsLocally(cached);
                    _processFilteredStartupsResult(filtered, preventScroll);
                }).catch(() => {});
                return existingPromise;
            }

            if (state.activeFetchController) {
                state.activeFetchController.abort();
            }
            state.activeFetchController = new AbortController();
            const signal = state.activeFetchController.signal;

            const promise = safeFetch(cityUrl, { signal })
                .then(startups => {
                    if (signal.aborted) return startups;
                    if (!Array.isArray(startups)) return startups;

                    state.cityCache.set(cityKey, startups);

                    const filtered = filterCityStartupsLocally(startups);
                    _processFilteredStartupsResult(filtered, preventScroll);
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
                    state.inFlightPromises.delete(cityUrl);
                });

            state.inFlightPromises.set(cityUrl, promise);
            return promise;
        }
    }

    const queryParams = new URLSearchParams();

    if (state.boundsOverride && Array.isArray(state.boundsOverride) && state.boundsOverride.length === 4) {
        const [minLatStr, maxLatStr, minLngStr, maxLngStr] = quantizeCoordinates(
            Number(state.boundsOverride[0]),
            Number(state.boundsOverride[1]),
            Number(state.boundsOverride[2]),
            Number(state.boundsOverride[3])
        );
        queryParams.set('min_lat', minLatStr);
        queryParams.set('max_lat', maxLatStr);
        queryParams.set('min_lng', minLngStr);
        queryParams.set('max_lng', maxLngStr);
        if (cityParam) {
            state.searchedCity = cityParam.toLowerCase();
        }
    } else {
        if (cityParam) {
            state.searchedCity = cityParam.toLowerCase();
            queryParams.set('city', cityParam);
        } else if (state.searchedCity) {
            queryParams.set('city', state.searchedCity);
        }
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
        if (!state.boundsOverride && !state.searchedCity && map && map.getContainer() && map.getContainer().clientWidth > 0) {
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

                const [minLatStr, maxLatStr, minLngStr, maxLngStr] = quantizeCoordinates(minLat, maxLat, minLng, maxLng);
                queryParams.set('min_lat', minLatStr);
                queryParams.set('max_lat', maxLatStr);
                queryParams.set('min_lng', minLngStr);
                queryParams.set('max_lng', maxLngStr);
            }
        }
    } catch (e) {}

    queryParams.set('has_jobs', 'true');

    const url = `/api/companies?${queryParams.toString()}`;

    if (state.queryCache.has(url)) {
        const cachedStartups = state.queryCache.get(url);
        _processFilteredStartupsResult(cachedStartups, preventScroll);
        return Promise.resolve(cachedStartups);
    }

    const containmentMatch = findCachedViewportMatch(queryParams);
    if (containmentMatch) {
        const filteredCachedStartups = filterStartupsByViewport(containmentMatch, queryParams);
        _processFilteredStartupsResult(filteredCachedStartups, preventScroll);
        return Promise.resolve(filteredCachedStartups);
    }

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
    } else if (activeQuery) {
        state.searchedCity = '';
        fetchFilteredStartups();
    } else {
        state.searchedCity = '';
        const titleEl = document.getElementById('activeMapTitle');
        if (titleEl) titleEl.textContent = 'All locations';
        
        const navInput = document.getElementById('unified-search-input');
        if (navInput) {
            navInput.placeholder = "Search city/location ...";
        }
        
        // Render empty sidebar state (no companies, welcome text)
        clearAllMarkers();
        const directoryList = document.getElementById('directory-list');
        if (directoryList) {
            directoryList.innerHTML = `
                <div class="p-6 text-center text-gray-500 font-medium">
                    Search for a city or location to find companies and jobs.
                </div>
            `;
        }
        updateDashboardStats([]);
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
    state.hasPannedLocally = true;
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

        // Transition to viewport mode on manual pan/zoom if moved > 50km from searched city center
        let shouldTransition = true;
        if (!navigator.webdriver && state.searchedCity && state.searchedCityCenter) {
            try {
                const center = map.getCenter();
                const distKm = calculateDistanceKm(
                    center.lat,
                    center.lng,
                    state.searchedCityCenter[1],
                    state.searchedCityCenter[0]
                );
                if (distKm <= 50) {
                    shouldTransition = false;
                }
            } catch (err) {
                console.warn('Error calculating distance from center:', err);
            }
        }

        if (shouldTransition) {
            state.searchedCity = '';
            state.boundsOverride = null;
            state.searchedCityCenter = null;
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('city')) {
                urlParams.delete('city');
                const newUrl = `${window.location.pathname}?${urlParams.toString()}${window.location.hash || ''}`;
                window.history.replaceState({ path: newUrl }, '', newUrl);
                state.lastQueryString = window.location.search;
            }

            const titleEl = document.getElementById('activeMapTitle');
            if (titleEl) {
                titleEl.textContent = 'All locations';
            }
            const navInput = document.getElementById('unified-search-input');
            if (navInput) {
                navInput.placeholder = "Search city/location ...";
                navInput.value = '';
            }
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
            (Array.isArray(startup.skills) && startup.skills.some(s => (s || '').toString().toLowerCase().includes(token))) ||
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
    if (!rawSearch) return '';
    if (state.searchedCity) {
        const normRaw = normalizeLocationQuery(rawSearch);
        const normCity = normalizeLocationQuery(state.searchedCity);
        if (normRaw === normCity || rawSearch === state.searchedCity.toLowerCase().trim()) {
            return '';
        }
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

map.on('move', () => {
    cullMarkers(map);
});

map.on('zoom', () => {
    cullMarkers(map);
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
    clearSearchBoundary();
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

// Dropdown menu toggle delegation
document.addEventListener('click', (e) => {
    const toggleBtn = e.target.closest('.user-dropdown-toggle');
    if (toggleBtn) {
        const dropdown = toggleBtn.nextElementSibling;
        if (dropdown) {
            dropdown.classList.toggle('hidden');
        }
        document.querySelectorAll('.user-dropdown').forEach(d => {
            if (d !== dropdown) d.classList.add('hidden');
        });
        return;
    }

    if (!e.target.closest('.auth-user')) {
        document.querySelectorAll('.user-dropdown').forEach(d => d.classList.add('hidden'));
    }
});

// View profile handler
document.addEventListener('click', (e) => {
    const viewProfileBtn = e.target.closest('.view-profile-btn');
    if (viewProfileBtn) {
        const dropdown = viewProfileBtn.closest('.user-dropdown');
        if (dropdown) dropdown.classList.add('hidden');

        safeFetch('/api/user/profile')
            .then(profile => {
                const avatarEl = document.getElementById('profile-modal-avatar');
                const emailEl = document.getElementById('profile-modal-email');
                const nameEl = document.getElementById('profile-name');
                const bioEl = document.getElementById('profile-bio');
                const skillsEl = document.getElementById('profile-skills');
                const locEl = document.getElementById('profile-location');
                
                if (avatarEl) avatarEl.src = profile.picture || 'https://lh3.googleusercontent.com/a/default-user';
                if (emailEl) emailEl.textContent = profile.email || '';
                if (nameEl) nameEl.value = profile.name || '';
                if (bioEl) bioEl.value = profile.bio || '';
                if (skillsEl) skillsEl.value = Array.isArray(profile.skills) ? profile.skills.join(', ') : '';
                if (locEl) locEl.value = profile.preferred_location || '';
                
                const prefs = profile.job_preferences || {};
                const workTypeEl = document.getElementById('profile-pref-work-type');
                const expLevelEl = document.getElementById('profile-pref-exp-level');
                const minSalEl = document.getElementById('profile-pref-min-salary');
                
                if (workTypeEl) workTypeEl.value = prefs.work_type || '';
                if (expLevelEl) expLevelEl.value = prefs.experience_level || '';
                if (minSalEl) minSalEl.value = prefs.min_salary || '';

                const modal = document.getElementById('profile-modal');
                if (modal) modal.classList.remove('hidden');
            })
            .catch(err => {
                console.error('[Profile Fetch Error]', err);
                showToast('Failed to load profile data.', 'error');
            });
    }
});

const closeProfileModal = () => {
    const modal = document.getElementById('profile-modal');
    if (modal) modal.classList.add('hidden');
};

const closeProfileBtn = document.getElementById('close-profile-modal-btn');
if (closeProfileBtn) closeProfileBtn.addEventListener('click', closeProfileModal);

const cancelProfileBtn = document.getElementById('cancel-profile-btn');
if (cancelProfileBtn) cancelProfileBtn.addEventListener('click', closeProfileModal);

// Profile form save handler
const profileForm = document.getElementById('profile-form');
if (profileForm) {
    profileForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const name = document.getElementById('profile-name').value.trim();
        const bio = document.getElementById('profile-bio').value.trim();
        const skillsRaw = document.getElementById('profile-skills').value;
        const preferred_location = document.getElementById('profile-location').value.trim();
        
        const work_type = document.getElementById('profile-pref-work-type').value;
        const experience_level = document.getElementById('profile-pref-exp-level').value;
        const minSalaryRaw = document.getElementById('profile-pref-min-salary').value.trim();
        const min_salary = minSalaryRaw ? parseFloat(minSalaryRaw) : null;

        const skills = skillsRaw
            ? skillsRaw.split(',').map(s => s.trim()).filter(Boolean)
            : [];

        const payload = {
            name,
            bio,
            skills,
            preferred_location,
            job_preferences: {
                work_type,
                experience_level,
                min_salary
            }
        };

        safeFetch('/api/user/profile', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        })
        .then(updatedProfile => {
            showToast('Profile updated successfully!', 'success');
            closeProfileModal();
            document.querySelectorAll('.user-name').forEach(el => {
                el.textContent = updatedProfile.name || 'User';
            });
            if (state.user) {
                state.user.name = updatedProfile.name;
            }
            applyAutoFilters(updatedProfile);
        })
        .catch(err => {
            console.error('[Profile Update Error]', err);
            showToast('Failed to update profile.', 'error');
        });
    });
}

// Global logout delegation
document.addEventListener('click', (e) => {
    if (e.target.closest('.logout-btn')) {
        safeFetch('/api/auth/logout', { method: 'POST' })
            .then(() => {
                window.location.reload();
            })
            .catch(() => window.location.reload());
    }
});

function applyAutoFilters(profile) {
    const isJobsRoute = window.location.pathname.startsWith('/jobs') || window.location.pathname.startsWith('/map') || (new URLSearchParams(window.location.search)).has('city');
    if (!isJobsRoute) return;

    const prefs = profile.job_preferences || {};
    let filterChanged = false;

    if (prefs.work_type && filterWorkType) {
        if (filterWorkType.value !== prefs.work_type) {
            filterWorkType.value = prefs.work_type;
            state.currentFilters.work_type = prefs.work_type;
            filterChanged = true;
        }
    }
    if (prefs.experience_level && filterExpLevel) {
        if (filterExpLevel.value !== prefs.experience_level) {
            filterExpLevel.value = prefs.experience_level;
            state.currentFilters.exp_level = prefs.experience_level;
            filterChanged = true;
        }
    }
    if (prefs.min_salary && filterSalaryMin) {
        const minSalStr = String(prefs.min_salary);
        const options = Array.from(filterSalaryMin.options).map(o => o.value);
        if (options.includes(minSalStr)) {
            if (filterSalaryMin.value !== minSalStr) {
                filterSalaryMin.value = minSalStr;
                state.currentFilters.salary_min = minSalStr;
                filterChanged = true;
            }
        }
    }

    const urlParams = new URLSearchParams(window.location.search);
    const cityParam = urlParams.get('city');

    if (!cityParam && profile.preferred_location) {
        executeUnifiedSearch(profile.preferred_location);
    } else if (filterChanged) {
        fetchFilteredStartups();
    }
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
    clearSearchBoundary,
    drawSearchBoundary,
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

fetch('/static/data/hub_boundaries.json')
    .then(res => res.json())
    .then(data => {
        state.hubBoundaries = data;
        if (state.searchedCity) {
            const normKey = normalizeLocationQuery(state.searchedCity);
            if (state.hubBoundaries[normKey]) {
                drawSearchBoundary(state.hubBoundaries[normKey]);
            }
        }
    })
    .catch(err => console.error("Error loading hub boundaries:", err));

checkAuthStatus()
    .then(data => {
        if (data && data.authenticated) {
            return safeFetch('/api/user/profile')
                .then(profile => {
                    applyAutoFilters(profile);
                });
        }
    })
    .catch(err => console.warn('[Auth/Profile Init Error]', err))
    .finally(() => {
        handleHashRouting();
        fetchAndRender();
    });

