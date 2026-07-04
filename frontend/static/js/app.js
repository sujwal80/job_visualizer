/**
 * WorldTech Map // Interactive Job Discovery
 * Fully compliant with mandatory secure web frontend skills (XSS-safe DOM building, no innerHTML).
 */

document.addEventListener('DOMContentLoaded', () => {
    // Default location focused on primary tech cluster
    const defaultLocation = [77.5946, 12.9716]; // [lng, lat]
    const defaultZoom = 11;

    // Initialize MapLibre Map with reliable CartoDB Voyager raster tiles (@2x retina)
    const map = new maplibregl.Map({
        container: 'map',
        style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
        center: defaultLocation,
        zoom: defaultZoom,
        minZoom: 1,
        maxZoom: 18,
        dragRotate: false,
        touchZoomRotate: false
    });

    // Customize ONLY water body and ocean color to natural blue, resetting all other color scheme to original CartoDB Voyager
    map.on('style.load', () => {
        if (map.getLayer('water')) map.setPaintProperty('water', 'fill-color', '#89bceb');
        if (map.getLayer('waterway')) map.setPaintProperty('waterway', 'line-color', '#7aafe0');
        if (map.getLayer('water_shadow')) map.setPaintProperty('water_shadow', 'fill-color', '#98c6f0');
    });

    map.addControl(new maplibregl.NavigationControl({
        showCompass: false
    }), 'top-right');

    const industryColors = {
        "Artificial Intelligence": "#7e22ce",
        "CleanTech": "#15803d",
        "Biotech": "#047857",
        "Fintech": "#c2410c",
        "B2B": "#0e7490",
        "SaaS": "#0369a1",
        "E-commerce": "#be185d",
        "Software Development": "#334155"
    };
    const defaultColor = "#2563eb";

    let startupsData = [];
    let markersMap = {};
    let currentSelectedId = null;
    let tempRemoteMarker = null;
    let currentSelectedIndustry = "";
    const coordinatesRegistry = {};
    const profileCache = new Map();
    const inFlightRequests = new Map();

    const directoryList = document.getElementById('directory-list');
    const detailsDrawer = document.getElementById('details-drawer');
    const drawerContent = document.getElementById('drawer-content');
    const closeDrawerBtn = document.getElementById('close-drawer-btn');
    const searchInput = document.getElementById('search-input');
    const deptFilter = document.getElementById('dept-filter');
    const expFilter = document.getElementById('exp-filter');
    const skillFilter = document.getElementById('skill-filter');
    const quickTabs = document.querySelectorAll('#quick-industry-tabs .tab-btn');
    const statCount = document.getElementById('stat-count');
    const statHeadcount = document.getElementById('stat-headcount');
    const statJobs = document.getElementById('stat-jobs');
    const mobileToggleBtn = document.getElementById('mobile-toggle-btn');
    const sidebar = document.getElementById('sidebar');
    const resetMapBtn = document.getElementById('reset-map-btn');

    // Secure DOM Helper: builds DOM without innerHTML to prevent XSS vulnerabilities
    function createElement(tag, props = {}, children = []) {
        const el = document.createElement(tag);
        for (const [key, val] of Object.entries(props)) {
            if (key === 'href' || key === 'src') {
                const lower = String(val).trim().toLowerCase().replace(/[\x00-\x20\u200b-\u200f\u2028\u2029\ufeff]/g, '');
                if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:') || lower.startsWith('file:') || lower.startsWith('about:') || lower.startsWith('blob:') || lower.startsWith('view-source:') || lower.startsWith('mhtml:')) {
                    continue;
                }
            }
            if (key === 'className') el.className = val;
            else if (key === 'textContent') el.textContent = val;
            else if (key.startsWith('data-')) el.setAttribute(key, val);
            else el.setAttribute(key, val);
        }
        for (const child of children) {
            if (typeof child === 'string') el.appendChild(document.createTextNode(child));
            else if (child) el.appendChild(child);
        }
        return el;
    }

    let rateLimitedUntil = 0;

    function showToast(message, type = 'info') {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = createElement('div', { id: 'toast-container', className: 'toast-container' });
            document.body.appendChild(container);
        }
        const toast = createElement('div', { className: `toast toast-${type}`, textContent: message });
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    async function safeFetch(url, options = {}) {
        if (Date.now() < rateLimitedUntil) {
            throw new Error('Client-side rate limit active');
        }
        try {
            const response = await fetch(url, options);
            if (response.status === 429) {
                const retryHeader = response.headers.get('Retry-After');
                const cooldown = retryHeader ? parseInt(retryHeader, 10) : 10;
                rateLimitedUntil = Date.now() + (isNaN(cooldown) ? 10 : cooldown) * 1000;
                showToast(`Rate limit exceeded. Pausing requests for ${isNaN(cooldown) ? 10 : cooldown}s.`, 'error');
                throw new Error('HTTP 429 Too Many Requests');
            }
            if (response.status === 400) {
                showToast('Invalid request filters. Resetting search criteria.', 'error');
                throw new Error('HTTP 400 Bad Request');
            }
            if (response.status >= 500) {
                showToast('Server error encountered. Retaining existing map data.', 'error');
                throw new Error(`HTTP ${response.status} Server Error`);
            }
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                throw new Error(`Expected JSON response but got ${contentType}`);
            }
            return await response.json();
        } catch (err) {
            if (err.name !== 'AbortError') {
                console.error(`API Fetch Error (${url}):`, err);
            }
            throw err;
        }
    }

    let filterRafId = null;
    function scheduleFiltering() {
        if (filterRafId) cancelAnimationFrame(filterRafId);
        filterRafId = requestAnimationFrame(() => {
            applyFiltering();
            filterRafId = null;
        });
    }

    let inputTimeout = null;
    function handleDebouncedInput() {
        if (inputTimeout) clearTimeout(inputTimeout);
        inputTimeout = setTimeout(scheduleFiltering, 150);
    }

    function getDomain(startup) {
        if (!startup) return '';
        const name = startup.name || '';
        if (name === 'Google') return 'google.com';
        if (name === 'Microsoft') return 'microsoft.com';
        if (name === 'Amazon') return 'amazon.com';
        if (name === 'Flipkart') return 'flipkart.com';
        if (name === 'Swiggy') return 'swiggy.com';
        if (name === 'Zomato') return 'zomato.com';

        let domain = typeof startup.logo_domain === 'string' ? startup.logo_domain : '';
        if (domain === 'news.microsoft.com') domain = 'microsoft.com';
        if (domain === 'aboutamazon.com') domain = 'amazon.com';
        if (domain === 'careers.linkedin.com') domain = 'linkedin.com';

        if (!domain && typeof startup.website === 'string') {
            try {
                const parsed = new URL(startup.website);
                domain = parsed.hostname.replace(/^www\./, '').toLowerCase();
                const blacklisted = ['bit.ly', 'linktr.ee', 'tinyurl.com', 't.co', 'buff.ly', 'goo.gl', 'goo.gle', 'ow.ly', 'forms.gle', 'linkedin.com'];
                if (blacklisted.includes(domain)) domain = '';
            } catch (e) { }
        }
        return domain;
    }

    function createLogoContent(startup) {
        const domain = getDomain(startup);
        const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
        const color = industryColors[startup.industry] || defaultColor;

        const container = createElement('div', { className: 'logo-marker-container' });

        const fallback = createElement('div', { className: 'logo-marker-fallback' }, [
            String(startup.name || 'S').substring(0, 1).toUpperCase()
        ]);
        fallback.style.backgroundColor = color;
        fallback.style.border = '2px solid #ffffff';
        container.appendChild(fallback);

        if (logoUrl) {
            const img = createElement('img', {
                src: logoUrl,
                className: 'logo-marker-thumbnail',
                alt: String(startup.name || 'Startup Logo')
            });
            img.style.border = `2.5px solid ${color}`;
            img.onerror = () => { img.style.display = 'none'; };
            container.appendChild(img);
        }

        container.addEventListener('click', (e) => {
            e.stopPropagation();
            selectAndOpenStartup(startup.id);
        });

        return container;
    }

    function fetchAndRender() {
        safeFetch('/api/startups')
            .then(startups => {
                if (!Array.isArray(startups)) return;
                startupsData = startups;
                clearAllMarkers();
                initializeMarkers(startups);
                scheduleFiltering();
                handleHashRouting();
            })
            .catch(err => {
                if (startupsData.length === 0) {
                    directoryList.replaceChildren(
                        createElement('div', { className: 'about-text', textContent: 'Failed to load company data.' })
                    );
                }
            });
    }

    fetchAndRender();

    let isFetchingViewport = false;
    let viewportDebounceTimer = null;
    let viewportFetchController = null;
    map.on('moveend', () => {
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
            const bounds = map.getBounds();
            if (!bounds) return;
            if (viewportFetchController) {
                viewportFetchController.abort();
            }
            viewportFetchController = new AbortController();
            const signal = viewportFetchController.signal;
            isFetchingViewport = true;
            const url = `/api/startups?min_lat=${bounds.getSouth()}&max_lat=${bounds.getNorth()}&min_lng=${bounds.getWest()}&max_lng=${bounds.getEast()}&limit=500`;
            safeFetch(url, { signal })
                .then(newStartups => {
                    isFetchingViewport = false;
                    if (signal.aborted) return;
                    if (Array.isArray(newStartups)) {
                        const existingIds = new Set(startupsData.map(s => s.id));
                        let addedNew = false;
                        newStartups.forEach(s => {
                            if (!existingIds.has(s.id)) {
                                startupsData.push(s);
                                addedNew = true;
                            }
                        });

                        const oldLength = startupsData.length;
                        if (startupsData.length > 1000) {
                            const minLat = bounds.getSouth();
                            const maxLat = bounds.getNorth();
                            const minLng = bounds.getWest();
                            const maxLng = bounds.getEast();
                            const newIds = new Set(newStartups.map(s => s.id));
                            startupsData = startupsData.filter(s => {
                                if (s.id === currentSelectedId || newIds.has(s.id)) return true;
                                const lat = s.orig_lat !== undefined ? s.orig_lat : s.lat;
                                const lng = s.orig_lng !== undefined ? s.orig_lng : s.lng;
                                if (lat === undefined || lng === undefined) return false;
                                return lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng;
                            });
                            if (startupsData.length > 1000) {
                                const keep = new Set();
                                if (currentSelectedId !== null) keep.add(currentSelectedId);
                                for (let i = startupsData.length - 1; i >= 0 && keep.size < 1000; i--) {
                                    keep.add(startupsData[i].id);
                                }
                                startupsData = startupsData.filter(s => keep.has(s.id));
                            }
                        }
                        const wasPruned = startupsData.length !== oldLength;

                        if (addedNew || wasPruned) {
                            updateMarkersDiff(startupsData);
                            scheduleFiltering();
                        }
                    }
                })
                .catch(err => {
                    if (err.name === 'AbortError') return;
                    isFetchingViewport = false;
                    console.error('Error fetching viewport startups:', err);
                });
        }, 300);
    });

    function updateMarkersDiff(startups) {
        const activeIds = new Set(startups.map(s => String(s.id)));

        for (const id in markersMap) {
            if (!activeIds.has(String(id))) {
                markersMap[id].remove();
                delete markersMap[id];
            }
        }

        startups.forEach(startup => {
            if (startup.has_pin === false) return;
            if (markersMap[startup.id] || markersMap[String(startup.id)]) return;

            if (startup.orig_lat === undefined) {
                startup.orig_lat = startup.lat;
                startup.orig_lng = startup.lng;
            }
            let lat = startup.orig_lat;
            let lng = startup.orig_lng;
            const coordKey = `${lat.toFixed(5)},${lng.toFixed(5)}`;

            if (coordinatesRegistry[coordKey]) {
                const count = coordinatesRegistry[coordKey];
                const angle = count * (2 * Math.PI / 8);
                const radius = 0.00025 * Math.ceil(count / 8);
                lat += radius * Math.sin(angle);
                lng += radius * Math.cos(angle);
                coordinatesRegistry[coordKey] = count + 1;
            } else {
                coordinatesRegistry[coordKey] = 1;
            }

            startup.lat = lat;
            startup.lng = lng;

            const markerEl = createLogoContent(startup);
            const marker = new maplibregl.Marker({
                element: markerEl,
                anchor: 'center'
            })
                .setLngLat([lng, lat])
                .addTo(map);

            markerEl.title = String(startup.name || '');
            markersMap[startup.id] = marker;
        });
    }

    function clearAllMarkers() {
        if (tempRemoteMarker) {
            tempRemoteMarker.remove();
            tempRemoteMarker = null;
        }
        for (const id in markersMap) {
            markersMap[id].remove();
        }
        markersMap = {};
        for (const key in coordinatesRegistry) delete coordinatesRegistry[key];
    }

    function initializeMarkers(startups) {
        startups.forEach(startup => {
            if (startup.has_pin === false) return;
            if (startup.orig_lat === undefined) {
                startup.orig_lat = startup.lat;
                startup.orig_lng = startup.lng;
            }
            let lat = startup.orig_lat;
            let lng = startup.orig_lng;
            const coordKey = `${lat.toFixed(5)},${lng.toFixed(5)}`;

            if (coordinatesRegistry[coordKey]) {
                const count = coordinatesRegistry[coordKey];
                const angle = count * (2 * Math.PI / 8);
                const radius = 0.00025 * Math.ceil(count / 8);
                lat += radius * Math.sin(angle);
                lng += radius * Math.cos(angle);
                coordinatesRegistry[coordKey] = count + 1;
            } else {
                coordinatesRegistry[coordKey] = 1;
            }

            startup.lat = lat;
            startup.lng = lng;

            const markerEl = createLogoContent(startup);
            const marker = new maplibregl.Marker({
                element: markerEl,
                anchor: 'center'
            })
                .setLngLat([lng, lat])
                .addTo(map);

            markerEl.title = String(startup.name || '');
            markersMap[startup.id] = marker;
        });
    }

    function updateDashboardStats(filteredStartups) {
        statCount.textContent = String(filteredStartups.length);
        const totalHeadcount = filteredStartups.reduce((sum, s) => sum + Math.max(0, parseInt(s.head_count, 10) || 0), 0);
        statHeadcount.textContent = totalHeadcount.toLocaleString();
        const totalJobs = filteredStartups.reduce((sum, s) => {
            const jobs = Array.isArray(s.jobs) ? s.jobs : (Array.isArray(s.job_openings) ? s.job_openings : []);
            const jCnt = s.job_count !== undefined && !isNaN(s.job_count) ? Math.max(0, parseInt(s.job_count, 10)) : jobs.length;
            return sum + jCnt;
        }, 0);
        statJobs.textContent = String(totalJobs);
    }

    function renderDirectory(startups) {
        directoryList.replaceChildren();
        if (startups.length === 0) {
            directoryList.appendChild(
                createElement('div', { className: 'about-text', textContent: 'No companies match your criteria.' })
            );
            return;
        }

        startups.forEach(startup => {
            const isSelected = currentSelectedId === startup.id;
            const indClass = startup.industry ? String(startup.industry).toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
            const domain = getDomain(startup);
            const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
            const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);
            const jCnt = startup.job_count !== undefined && !isNaN(startup.job_count) ? Math.max(0, parseInt(startup.job_count, 10)) : jobs.length;

            const avatarChildren = [
                createElement('span', { textContent: String(startup.name || 'S').substring(0, 1).toUpperCase() })
            ];
            if (logoUrl) {
                const img = createElement('img', { src: logoUrl, alt: String(startup.name || 'Logo') });
                img.style.position = 'absolute';
                img.style.top = '0';
                img.style.left = '0';
                img.style.width = '100%';
                img.style.height = '100%';
                img.style.objectFit = 'contain';
                img.style.backgroundColor = '#ffffff';
                img.style.padding = '4px';
                img.onerror = () => { img.style.display = 'none'; };
                avatarChildren.push(img);
            }

            const topTags = [
                createElement('span', { className: 'card-title', textContent: String(startup.name || 'Unnamed Startup') }),
                createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry || 'Tech' })
            ];
            if (startup.has_pin === false) {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #fef9c3; color: #854d0e; border: 1px solid #fde047; margin-left: 6px;', textContent: '📍 Remote / Hub' }));
            }
            if (startup.funding_stage && startup.funding_stage !== "N/A") {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; margin-left: 6px;', textContent: `🌱 ${startup.funding_stage}` }));
            }
            if (startup.verified_email || (Array.isArray(startup.founder_names) && startup.founder_names.length > 0)) {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; margin-left: 6px;', textContent: '✨ Direct Access' }));
            }

            const headCount = Math.max(0, parseInt(startup.head_count, 10) || 0);
            const card = createElement('div', {
                className: 'directory-item' + (isSelected ? ' active' : ''),
                id: `directory-item-${startup.id}`
            }, [
                createElement('div', { className: 'card-avatar' }, avatarChildren),
                createElement('div', { className: 'card-body' }, [
                    createElement('div', { className: 'card-top' }, topTags),
                    createElement('div', { className: 'card-meta' }, [
                        createElement('span', { textContent: `👥 ${headCount}` }),
                        createElement('span', { textContent: '•' }),
                        createElement('span', { textContent: `📍 ${startup.city ? String(startup.city).split(',')[0] : 'Global'}` }),
                        createElement('span', { textContent: '•' }),
                        createElement('span', { textContent: `💼 ${jCnt} jobs` })
                    ])
                ])
            ]);

            card.addEventListener('click', () => {
                selectAndOpenStartup(startup.id);
            });

            directoryList.appendChild(card);
        });
        if (startups.length >= 500) {
            directoryList.appendChild(
                createElement('div', {
                    className: 'about-text',
                    style: 'text-align: center; padding: 12px; background: #fef3c7; color: #92400e; border-radius: 8px; margin-top: 12px; font-size: 13px;',
                    textContent: '⚡ Showing top 500 active hiring companies. Zoom in on the map to reveal more local startups!'
                })
            );
        }
    }

    function renderDrawerDetails(startup) {
        drawerContent.replaceChildren();
        const indClass = startup.industry ? String(startup.industry).toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
        const domain = getDomain(startup);
        const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
        const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);
        const jCnt = startup.job_count !== undefined && !isNaN(startup.job_count) ? Math.max(0, parseInt(startup.job_count, 10)) : jobs.length;

        // Hero Header
        const heroAvatarChildren = [
            createElement('span', { textContent: String(startup.name || 'S').substring(0, 1).toUpperCase() })
        ];
        if (logoUrl) {
            const img = createElement('img', { src: logoUrl, className: 'drawer-logo', alt: String(startup.name || 'Logo') });
            img.style.position = 'absolute';
            img.style.top = '0';
            img.style.left = '0';
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'contain';
            img.style.backgroundColor = '#ffffff';
            img.style.padding = '6px';
            img.onerror = () => { img.style.display = 'none'; };
            heroAvatarChildren.push(img);
        }

        const heroTagsList = [
            createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry || 'Technology' }),
            createElement('span', { className: 'verified-pill', textContent: jCnt > 0 ? `💼 ${jCnt} Active Jobs` : 'Hiring Soon' })
        ];
        if (startup.funding_stage && startup.funding_stage !== "N/A") {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `🌱 ${startup.funding_stage} (${startup.total_raised || 'Active'})` }));
        }
        if (startup.verified_email) {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: `✉️ Verified HR: ${startup.verified_email}` }));
        }
        const foundersList = Array.isArray(startup.founders) ? startup.founders : [];
        if (foundersList.length > 0) {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #faf5ff; color: #6b21a8; border: 1px solid #e9d5ff;', textContent: `✨ Direct Founder Access (${foundersList.length} profiles)` }));
        }

        const heroSection = createElement('div', { className: 'drawer-hero' }, [
            createElement('div', { className: 'card-avatar' }, heroAvatarChildren),
            createElement('div', { className: 'drawer-hero-text' }, [
                createElement('h2', { textContent: String(startup.name || 'Unnamed Startup') }),
                createElement('div', { className: 'hero-tags' }, heroTagsList)
            ])
        ]);

        // Key Metrics Grid
        const headCount = Math.max(0, parseInt(startup.head_count, 10) || 0);
        const metricsSection = createElement('div', { className: 'meta-box-grid' }, [
            createElement('div', { className: 'meta-item' }, [
                createElement('span', { className: 'meta-item-lbl', textContent: 'Headcount' }),
                createElement('span', { className: 'meta-item-val', textContent: `${headCount} Employees` })
            ]),
            createElement('div', { className: 'meta-item' }, [
                createElement('span', { className: 'meta-item-lbl', textContent: 'City / Hub' }),
                createElement('span', { className: 'meta-item-val', textContent: startup.city || 'Bengaluru' })
            ])
        ]);

        // About & Website
        const descText = (startup.description && String(startup.description).trim()) ? String(startup.description).trim() : 'No description provided for this company.';
        const aboutSection = createElement('div', {}, [
            createElement('div', { className: 'section-title', textContent: 'About Company' }),
            createElement('p', { className: 'about-text', textContent: descText })
        ]);

        if (startup.website) {
            const siteLink = createElement('a', {
                href: startup.website,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'founder-link',
                textContent: `${startup.website} ↗`
            });
            siteLink.style.display = 'inline-block';
            siteLink.style.marginTop = '8px';
            aboutSection.appendChild(siteLink);
        }

        drawerContent.appendChild(heroSection);
        drawerContent.appendChild(metricsSection);
        drawerContent.appendChild(aboutSection);

        // Founders Section
        if (foundersList.length > 0) {
            const foundersContainer = createElement('div', { className: 'founders-grid' });
            foundersList.forEach(f => {
                const fCardChildren = [
                    createElement('span', { className: 'founder-name', textContent: f.name || 'Anonymous Founder' }),
                    createElement('span', { className: 'founder-role', textContent: f.role || 'Founder / Leadership' })
                ];
                if (f.linkedin) {
                    fCardChildren.push(
                        createElement('a', {
                            href: f.linkedin,
                            target: '_blank',
                            rel: 'noopener noreferrer',
                            className: 'founder-link',
                            textContent: 'LinkedIn Profile &rarr;'
                        })
                    );
                }
                foundersContainer.appendChild(createElement('div', { className: 'founder-card' }, fCardChildren));
            });

            drawerContent.appendChild(
                createElement('div', {}, [
                    createElement('div', { className: 'section-title', textContent: 'Leadership & Founders' }),
                    foundersContainer
                ])
            );
        }

        // Job Openings
        const selectedDept = deptFilter ? deptFilter.value.toLowerCase().trim() : '';
        const selectedExp = expFilter ? expFilter.value.toLowerCase().trim() : '';
        const selectedSkill = skillFilter ? skillFilter.value.toLowerCase().trim() : '';

        const blrJobs = jobs.filter(j => {
            if (!j || typeof j !== 'object') return false;
            if (j.location) {
                const loc = String(j.location).toLowerCase();
                if (!(loc.includes('bengaluru') || loc.includes('bangalore') || loc.includes('india'))) {
                    return false;
                }
            }
            if (selectedDept && !(j.department && String(j.department).toLowerCase().includes(selectedDept))) {
                return false;
            }
            if (selectedExp && !((j.experience && String(j.experience).toLowerCase().includes(selectedExp)) || (j.job_type && String(j.job_type).toLowerCase().includes(selectedExp)))) {
                return false;
            }
            if (selectedSkill && !(Array.isArray(j.skills) && j.skills.some(s => String(s).toLowerCase().includes(selectedSkill)))) {
                return false;
            }
            return true;
        });

        const jobsContainer = createElement('div', { className: 'jobs-list' });
        if (blrJobs.length > 0) {
            blrJobs.forEach(j => {
                const deptText = j.department ? String(j.department) : 'General';
                const sourceText = j.source ? String(j.source) : 'Direct';
                const jobType = j.job_type ? String(j.job_type) : 'Full-Time';
                const salaryText = (j.salary && j.salary !== "Not disclosed" && j.salary !== "N/A") ? String(j.salary) : 'Competitive Salary';
                const expText = (j.experience && j.experience !== "Not specified") ? String(j.experience) : 'Experience Not Specified';

                const tagsChildren = [
                    createElement('span', { className: 'job-tag badge-attr', textContent: deptText }),
                    createElement('span', { className: 'job-tag badge-attr', textContent: sourceText })
                ];
                if (j.job_type || !j.experience) {
                    const jtTag = createElement('span', { className: 'job-tag badge-attr', textContent: `📌 ${jobType}` });
                    jtTag.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (expFilter) {
                            for (let opt of expFilter.options) {
                                if (opt.value && (jobType.toLowerCase().includes(opt.value.toLowerCase()) || opt.value.toLowerCase().includes(jobType.toLowerCase()))) {
                                    expFilter.value = opt.value;
                                    applyFiltering();
                                    break;
                                }
                            }
                        }
                    });
                    tagsChildren.push(jtTag);
                }
                if (j.experience || !j.job_type) {
                    const expTag = createElement('span', { className: 'job-tag badge-attr', textContent: `⏳ ${expText}` });
                    expTag.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (expFilter) {
                            for (let opt of expFilter.options) {
                                if (opt.value && (expText.toLowerCase().includes(opt.value.toLowerCase()) || opt.value.toLowerCase().includes(expText.toLowerCase()))) {
                                    expFilter.value = opt.value;
                                    applyFiltering();
                                    break;
                                }
                            }
                        }
                    });
                    tagsChildren.push(expTag);
                }
                tagsChildren.push(createElement('span', { className: 'job-tag badge-attr', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `💰 ${salaryText}` }));
                if (Array.isArray(j.skills) && j.skills.length > 0) {
                    j.skills.forEach(skill => {
                        const skillTag = createElement('span', { className: 'job-tag badge-attr', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: `🛠 ${skill}` });
                        skillTag.addEventListener('click', (e) => {
                            e.stopPropagation();
                            if (skillFilter) {
                                skillFilter.value = skill;
                                applyFiltering();
                            }
                        });
                        tagsChildren.push(skillTag);
                    });
                }
                if (j.posted_date && j.posted_date !== "Recent") {
                    tagsChildren.push(createElement('span', { className: 'job-tag badge-attr', style: 'background: #fff7ed; color: #9a3412; border: 1px solid #ffedd5;', textContent: `📅 ${j.posted_date}` }));
                } else {
                    tagsChildren.push(createElement('span', { className: 'job-tag badge-attr', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `🔥 Active` }));
                }

                const jCard = createElement('div', { className: 'job-card' }, [
                    createElement('div', { className: 'job-info' }, [
                        createElement('h4', { textContent: j.title || 'Open Position' }),
                        createElement('div', { className: 'job-tags' }, tagsChildren)
                    ]),
                    j.url ? createElement('a', {
                        href: j.url,
                        target: '_blank',
                        rel: 'noopener noreferrer',
                        className: 'job-btn',
                        textContent: 'Apply ↗'
                    }) : null
                ]);
                jobsContainer.appendChild(jCard);
            });
        } else {
            const emptyState = createElement('div', { className: 'about-text', style: 'padding: 16px; text-align: center; background: rgba(255,255,255,0.05); border-radius: 8px; border: 1px dashed rgba(255,255,255,0.2);' }, [
                createElement('p', { style: 'margin: 0 0 4px 0; font-weight: 500;', textContent: 'No active job openings listed.' }),
                createElement('span', { style: 'font-size: 12px; opacity: 0.7;', textContent: 'Check back later or visit the company website for general career inquiries.' })
            ]);
            jobsContainer.appendChild(emptyState);
        }

        drawerContent.appendChild(
            createElement('div', {}, [
                createElement('div', { className: 'section-title', textContent: 'Current Job Openings' }),
                jobsContainer
            ])
        );

        // HR & Benefits
        if (startup.hr_details && (startup.hr_details.benefits || startup.hr_details.contact_email)) {
            const hrBoxChildren = [];
            if (startup.hr_details.benefits) {
                hrBoxChildren.push(createElement('p', { className: 'about-text', textContent: `🎁 Benefits: ${startup.hr_details.benefits}` }));
            }
            if (startup.hr_details.contact_email) {
                hrBoxChildren.push(createElement('p', { className: 'about-text', textContent: `✉ Contact: ${startup.hr_details.contact_email}` }));
            }
            drawerContent.appendChild(
                createElement('div', { className: 'other-loc-box' }, hrBoxChildren)
            );
        }
    }

    function checkStartupMatch(startup, searchText, selectedDept, selectedExp, selectedSkill) {
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
        const matchesDept = selectedDept === '' || jobs.some(j => j && (j.department || '').toString().toLowerCase().includes(selectedDept.toLowerCase()));
        const matchesExp = selectedExp === '' || jobs.some(j => j && (
            ((j.experience || '').toString().toLowerCase().includes(selectedExp.toLowerCase())) ||
            ((j.job_type || '').toString().toLowerCase().includes(selectedExp.toLowerCase()))
        ));
        const matchesSkill = selectedSkill === '' || jobs.some(j => j && Array.isArray(j.skills) && j.skills.some(s => (s || '').toString().toLowerCase().includes(selectedSkill.toLowerCase())));
        return matchesSearch && matchesIndustry && matchesDept && matchesExp && matchesSkill;
    }

    function updateMarkersVisualState() {
        const searchText = searchInput.value.toLowerCase().trim();
        const selectedDept = deptFilter.value;
        const selectedExp = expFilter ? expFilter.value : '';
        const selectedSkill = skillFilter ? skillFilter.value : '';
        const isFilteringActive = searchText !== '' || currentSelectedIndustry !== '' || selectedDept !== '' || selectedExp !== '' || selectedSkill !== '';

        startupsData.forEach(startup => {
            const marker = markersMap[startup.id] || (currentSelectedId === startup.id ? tempRemoteMarker : null);
            if (!marker) return;
            const element = marker.getElement();
            const isSelected = currentSelectedId === startup.id;
            const isMatch = checkStartupMatch(startup, searchText, selectedDept, selectedExp, selectedSkill);

            const isFaded = isFilteringActive && !isMatch;
            const img = element.querySelector('.logo-marker-thumbnail');
            const color = industryColors[startup.industry] || defaultColor;

            if (img) {
                img.className = 'logo-marker-thumbnail' + (isSelected ? ' active' : '') + (isFaded ? ' faded' : '');
                img.style.border = isSelected ? `3px solid ${color}` : (isFaded ? '1px solid #cbd5e1' : `2.5px solid ${color}`);
            }

            if (isSelected) element.classList.add('active');
            else element.classList.remove('active');

            if (isFaded) element.classList.add('faded');
            else element.classList.remove('faded');

            element.style.zIndex = isSelected ? '1000' : (isMatch ? '100' : '10');
        });
    }

    function applyFiltering() {
        const searchText = searchInput.value.toLowerCase().trim();
        const selectedDept = deptFilter.value;
        const selectedExp = expFilter ? expFilter.value : '';
        const selectedSkill = skillFilter ? skillFilter.value : '';

        const filtered = startupsData.filter(startup => checkStartupMatch(startup, searchText, selectedDept, selectedExp, selectedSkill));

        renderDirectory(filtered);
        updateDashboardStats(filtered);
        updateMarkersVisualState();
        if (currentSelectedId !== null && detailsDrawer.classList.contains('active')) {
            const startup = startupsData.find(s => s.id === currentSelectedId);
            if (startup) {
                renderDrawerDetails(startup);
            }
        }
    }

    function _processOpenStartup(fullStartup) {
        if (fullStartup && !fullStartup.error) {
            const id = fullStartup.id;
            const idx = startupsData.findIndex(s => s.id === id);
            if (idx !== -1) startupsData[idx] = fullStartup;
            else startupsData.push(fullStartup);

            if (tempRemoteMarker) {
                tempRemoteMarker.remove();
                tempRemoteMarker = null;
            }

            currentSelectedId = id;
            if (window.location.hash !== `#startup=${id}`) {
                window.location.hash = `startup=${id}`;
            }

            let flyCenter = [fullStartup.lng || 77.5946, fullStartup.lat || 12.9716];
            let flyZoom = 16;

            if (fullStartup.has_pin === false) {
                const centerLng = 77.5946;
                const centerLat = 12.9716;
                fullStartup.lng = centerLng;
                fullStartup.lat = centerLat;
                flyCenter = [centerLng, centerLat];
                flyZoom = 15.5;

                const markerEl = createLogoContent(fullStartup);
                markerEl.classList.add('active');
                markerEl.style.zIndex = '10000';
                tempRemoteMarker = new maplibregl.Marker({
                    element: markerEl,
                    anchor: 'center'
                })
                    .setLngLat([centerLng, centerLat])
                    .addTo(map);
            }

            map.flyTo({
                center: flyCenter,
                zoom: flyZoom,
                speed: 3.0,
                essential: true
            });
            renderDrawerDetails(fullStartup);
            detailsDrawer.classList.add('active');
            detailsDrawer.setAttribute('aria-hidden', 'false');
            applyFiltering();

            const card = document.getElementById(`directory-item-${id}`);
            if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            updateMarkersVisualState();
        }
    }

    function selectAndOpenStartup(id) {
        currentSelectedId = id;
        for (const [pendingId, controller] of inFlightRequests.entries()) {
            if (pendingId !== id) {
                controller.abort();
                inFlightRequests.delete(pendingId);
            }
        }

        if (profileCache.has(id)) {
            _processOpenStartup(profileCache.get(id));
            return;
        }
        if (inFlightRequests.has(id)) {
            return; // Coalesce redundant concurrent fetch attempts
        }

        const controller = new AbortController();
        inFlightRequests.set(id, controller);

        safeFetch(`/api/startups/${id}`, { signal: controller.signal })
            .then(fullStartup => {
                inFlightRequests.delete(id);
                if (controller.signal.aborted) return;
                if (currentSelectedId === id && fullStartup && !fullStartup.error) {
                    if (profileCache.size >= 50) {
                        const firstKey = profileCache.keys().next().value;
                        profileCache.delete(firstKey);
                    }
                    profileCache.set(id, fullStartup);
                    _processOpenStartup(fullStartup);
                }
            })
            .catch(err => {
                inFlightRequests.delete(id);
                if (err.name === 'AbortError') return;
                showToast('Could not load company profile. Please try again.', 'error');
            });
    }

    // Hash routing
    function handleHashRouting() {
        const hash = window.location.hash;
        if (hash.startsWith('#startup=')) {
            const id = parseInt(hash.split('=')[1], 10);
            if (!isNaN(id)) {
                selectAndOpenStartup(id);
                return;
            }
        }

        if (tempRemoteMarker) {
            tempRemoteMarker.remove();
            tempRemoteMarker = null;
        }
        currentSelectedId = null;
        detailsDrawer.classList.remove('active');
        detailsDrawer.setAttribute('aria-hidden', 'true');
        map.flyTo({
            center: defaultLocation,
            zoom: defaultZoom,
            speed: 3.0,
            essential: true
        });
        applyFiltering();
        updateMarkersVisualState();
    }

    window.addEventListener('hashchange', handleHashRouting);

    searchInput.addEventListener('input', handleDebouncedInput);
    deptFilter.addEventListener('change', scheduleFiltering);
    if (expFilter) expFilter.addEventListener('change', scheduleFiltering);
    if (skillFilter) {
        skillFilter.addEventListener('input', handleDebouncedInput);
        skillFilter.addEventListener('change', scheduleFiltering);
    }

    quickTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            quickTabs.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSelectedIndustry = btn.getAttribute('data-industry') || "";
            applyFiltering();
        });
    });

    if (resetMapBtn) {
        resetMapBtn.addEventListener('click', () => {
            map.setCenter(defaultLocation);
            map.setZoom(defaultZoom);
        });
    }

    map.on('click', () => { window.location.hash = ''; });
    closeDrawerBtn.addEventListener('click', () => { window.location.hash = ''; });

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

    // Expose core functions to window.WorldTechApp for modular unit & E2E testing
    window.WorldTechApp = {
        createElement,
        showToast,
        safeFetch,
        getDomain,
        createLogoContent,
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
        handleHashRouting,
        checkViewportResilience
    };
});
