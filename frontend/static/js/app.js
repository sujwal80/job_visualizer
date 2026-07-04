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
                const lower = String(val).trim().toLowerCase();
                if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:')) {
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
            console.error(`API Fetch Error (${url}):`, err);
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
        if (startup.name === 'Google') return 'google.com';
        if (startup.name === 'Microsoft') return 'microsoft.com';
        if (startup.name === 'Amazon') return 'amazon.com';
        if (startup.name === 'Flipkart') return 'flipkart.com';
        if (startup.name === 'Swiggy') return 'swiggy.com';
        if (startup.name === 'Zomato') return 'zomato.com';

        let domain = startup.logo_domain || '';
        if (domain === 'news.microsoft.com') domain = 'microsoft.com';
        if (domain === 'aboutamazon.com') domain = 'amazon.com';
        if (domain === 'careers.linkedin.com') domain = 'linkedin.com';

        if (!domain && startup.website) {
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
            (startup.name || 'S').substring(0, 1).toUpperCase()
        ]);
        fallback.style.backgroundColor = color;
        fallback.style.border = '2px solid #ffffff';
        container.appendChild(fallback);

        if (logoUrl) {
            const img = createElement('img', {
                src: logoUrl,
                className: 'logo-marker-thumbnail',
                alt: startup.name || 'Startup Logo'
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
    map.on('moveend', () => {
        if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
        viewportDebounceTimer = setTimeout(() => {
            if (isFetchingViewport) return;
            const bounds = map.getBounds();
            if (!bounds) return;
            isFetchingViewport = true;
            const url = `/api/startups?min_lat=${bounds.getSouth()}&max_lat=${bounds.getNorth()}&min_lng=${bounds.getWest()}&max_lng=${bounds.getEast()}&limit=500`;
            safeFetch(url)
                .then(newStartups => {
                    isFetchingViewport = false;
                    if (Array.isArray(newStartups)) {
                        const existingIds = new Set(startupsData.map(s => s.id));
                        let addedNew = false;
                        newStartups.forEach(s => {
                            if (!existingIds.has(s.id)) {
                                startupsData.push(s);
                                addedNew = true;
                            }
                        });
                        if (addedNew) {
                            clearAllMarkers();
                            initializeMarkers(startupsData);
                            scheduleFiltering();
                        }
                    }
                })
                .catch(err => {
                    isFetchingViewport = false;
                    console.error('Error fetching viewport startups:', err);
                });
        }, 300);
    });

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

            markerEl.title = startup.name;
            markersMap[startup.id] = marker;
        });
    }

    function updateDashboardStats(filteredStartups) {
        statCount.textContent = String(filteredStartups.length);
        const totalHeadcount = filteredStartups.reduce((sum, s) => sum + (s.head_count || 0), 0);
        statHeadcount.textContent = totalHeadcount.toLocaleString();
        const totalJobs = filteredStartups.reduce((sum, s) => sum + (s.job_count !== undefined ? s.job_count : (s.job_openings ? s.job_openings.length : 0)), 0);
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
            const indClass = startup.industry ? startup.industry.toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
            const domain = getDomain(startup);
            const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
            const jCnt = startup.job_count !== undefined ? startup.job_count : ((startup.jobs || startup.job_openings) ? (startup.jobs || startup.job_openings).length : 0);

            const avatarChildren = [
                createElement('span', { textContent: (startup.name || 'S').substring(0, 1).toUpperCase() })
            ];
            if (logoUrl) {
                const img = createElement('img', { src: logoUrl, alt: startup.name });
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
                createElement('span', { className: 'card-title', textContent: startup.name }),
                createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry })
            ];
            if (startup.has_pin === false) {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #fef9c3; color: #854d0e; border: 1px solid #fde047; margin-left: 6px;', textContent: '📍 Remote / Hub' }));
            }
            if (startup.funding_stage && startup.funding_stage !== "N/A") {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; margin-left: 6px;', textContent: `🌱 ${startup.funding_stage}` }));
            }
            if (startup.verified_email || (startup.founder_names && startup.founder_names.length > 0)) {
                topTags.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; margin-left: 6px;', textContent: '✨ Direct Access' }));
            }

            const card = createElement('div', {
                className: 'directory-item' + (isSelected ? ' active' : ''),
                id: `directory-item-${startup.id}`
            }, [
                createElement('div', { className: 'card-avatar' }, avatarChildren),
                createElement('div', { className: 'card-body' }, [
                    createElement('div', { className: 'card-top' }, topTags),
                    createElement('div', { className: 'card-meta' }, [
                        createElement('span', { textContent: `👥 ${startup.head_count || 0}` }),
                        createElement('span', { textContent: '•' }),
                        createElement('span', { textContent: `📍 ${startup.city ? startup.city.split(',')[0] : 'Global'}` }),
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
        const indClass = startup.industry ? startup.industry.toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
        const domain = getDomain(startup);
        const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
        const jCnt = startup.job_count !== undefined ? startup.job_count : ((startup.jobs || startup.job_openings) ? (startup.jobs || startup.job_openings).length : 0);

        // Hero Header
        const heroAvatarChildren = [
            createElement('span', { textContent: (startup.name || 'S').substring(0, 1).toUpperCase() })
        ];
        if (logoUrl) {
            const img = createElement('img', { src: logoUrl, className: 'drawer-logo', alt: startup.name });
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
            createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry }),
            createElement('span', { className: 'verified-pill', textContent: jCnt > 0 ? `💼 ${jCnt} Active Jobs` : 'Hiring Soon' })
        ];
        if (startup.funding_stage && startup.funding_stage !== "N/A") {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `🌱 ${startup.funding_stage} (${startup.total_raised || 'Active'})` }));
        }
        if (startup.verified_email) {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: `✉️ Verified HR: ${startup.verified_email}` }));
        }
        if (startup.founders && startup.founders.length > 0) {
            heroTagsList.push(createElement('span', { className: 'verified-pill', style: 'background: #faf5ff; color: #6b21a8; border: 1px solid #e9d5ff;', textContent: `✨ Direct Founder Access (${startup.founders.length} profiles)` }));
        }

        const heroSection = createElement('div', { className: 'drawer-hero' }, [
            createElement('div', { className: 'card-avatar' }, heroAvatarChildren),
            createElement('div', { className: 'drawer-hero-text' }, [
                createElement('h2', { textContent: startup.name }),
                createElement('div', { className: 'hero-tags' }, heroTagsList)
            ])
        ]);

        // Key Metrics Grid
        const metricsSection = createElement('div', { className: 'meta-box-grid' }, [
            createElement('div', { className: 'meta-item' }, [
                createElement('span', { className: 'meta-item-lbl', textContent: 'Headcount' }),
                createElement('span', { className: 'meta-item-val', textContent: `${startup.head_count || 0} Employees` })
            ]),
            createElement('div', { className: 'meta-item' }, [
                createElement('span', { className: 'meta-item-lbl', textContent: 'City / Hub' }),
                createElement('span', { className: 'meta-item-val', textContent: startup.city || 'Bengaluru' })
            ])
        ]);

        // About & Website
        const aboutSection = createElement('div', {}, [
            createElement('div', { className: 'section-title', textContent: 'About Company' }),
            createElement('p', { className: 'about-text', textContent: startup.description || 'No description provided.' })
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
        if (startup.founders && startup.founders.length > 0) {
            const foundersContainer = createElement('div', { className: 'founders-grid' });
            startup.founders.forEach(f => {
                const fCardChildren = [
                    createElement('span', { className: 'founder-name', textContent: f.name || 'Anonymous' }),
                    createElement('span', { className: 'founder-role', textContent: f.role || 'Founder' })
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

        const blrJobs = (startup.jobs || startup.job_openings || []).filter(j => {
            if (j.location) {
                const loc = j.location.toLowerCase();
                if (!(loc.includes('bengaluru') || loc.includes('bangalore') || loc.includes('india'))) {
                    return false;
                }
            }
            if (selectedDept && !(j.department && j.department.toLowerCase().includes(selectedDept))) {
                return false;
            }
            if (selectedExp && !((j.experience && j.experience.toLowerCase().includes(selectedExp)) || (j.job_type && j.job_type.toLowerCase().includes(selectedExp)))) {
                return false;
            }
            if (selectedSkill && !(j.skills && j.skills.some(s => s.toLowerCase().includes(selectedSkill)))) {
                return false;
            }
            return true;
        });

        const jobsContainer = createElement('div', { className: 'jobs-list' });
        if (blrJobs.length > 0) {
            blrJobs.forEach(j => {
                const tagsChildren = [
                    createElement('span', { className: 'job-tag badge-attr', textContent: j.department || 'General' }),
                    createElement('span', { className: 'job-tag badge-attr', textContent: j.source || 'Direct' })
                ];
                if (j.job_type) {
                    const jtTag = createElement('span', { className: 'job-tag badge-attr', textContent: `📌 ${j.job_type}` });
                    jtTag.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (expFilter) {
                            for (let opt of expFilter.options) {
                                if (opt.value && (j.job_type.toLowerCase().includes(opt.value.toLowerCase()) || opt.value.toLowerCase().includes(j.job_type.toLowerCase()))) {
                                    expFilter.value = opt.value;
                                    applyFiltering();
                                    break;
                                }
                            }
                        }
                    });
                    tagsChildren.push(jtTag);
                }
                if (j.experience && j.experience !== "Not specified") {
                    const expTag = createElement('span', { className: 'job-tag badge-attr', textContent: `⏳ ${j.experience}` });
                    expTag.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (expFilter) {
                            for (let opt of expFilter.options) {
                                if (opt.value && (j.experience.toLowerCase().includes(opt.value.toLowerCase()) || opt.value.toLowerCase().includes(j.experience.toLowerCase()))) {
                                    expFilter.value = opt.value;
                                    applyFiltering();
                                    break;
                                }
                            }
                        }
                    });
                    tagsChildren.push(expTag);
                }
                if (j.salary && j.salary !== "Not disclosed") {
                    tagsChildren.push(createElement('span', { className: 'job-tag badge-attr', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `💰 ${j.salary}` }));
                }
                if (j.skills && Array.isArray(j.skills) && j.skills.length > 0) {
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
            jobsContainer.appendChild(createElement('p', { className: 'about-text', textContent: 'No active job openings.' }));
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
        const matchesSearch = searchText === '' ||
            startup.name.toLowerCase().includes(searchText) ||
            (startup.description && startup.description.toLowerCase().includes(searchText)) ||
            (startup.city && startup.city.toLowerCase().includes(searchText)) ||
            (startup.founder_names && startup.founder_names.some(fn => fn.toLowerCase().includes(searchText))) ||
            (startup.founders && startup.founders.some(f => f.name && f.name.toLowerCase().includes(searchText))) ||
            (startup.job_titles && startup.job_titles.some(jt => jt.toLowerCase().includes(searchText))) ||
            ((startup.jobs || startup.job_openings) && (startup.jobs || startup.job_openings).some(j =>
                (j.title && j.title.toLowerCase().includes(searchText)) ||
                (j.department && j.department.toLowerCase().includes(searchText)) ||
                (j.skills && j.skills.some(s => s.toLowerCase().includes(searchText))) ||
                (j.salary && j.salary.toLowerCase().includes(searchText)) ||
                (j.experience && j.experience.toLowerCase().includes(searchText))
            ));
        const matchesIndustry = currentSelectedIndustry === '' || startup.industry === currentSelectedIndustry;
        const matchesDept = selectedDept === '' || ((startup.jobs || startup.job_openings) && (startup.jobs || startup.job_openings).some(j => j.department && j.department.toLowerCase().includes(selectedDept.toLowerCase())));
        const matchesExp = selectedExp === '' || ((startup.jobs || startup.job_openings) && (startup.jobs || startup.job_openings).some(j =>
            (j.experience && j.experience.toLowerCase().includes(selectedExp.toLowerCase())) ||
            (j.job_type && j.job_type.toLowerCase().includes(selectedExp.toLowerCase()))
        ));
        const matchesSkill = selectedSkill === '' || ((startup.jobs || startup.job_openings) && (startup.jobs || startup.job_openings).some(j => j.skills && j.skills.some(s => s.toLowerCase().includes(selectedSkill.toLowerCase()))));
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
        if (profileCache.has(id)) {
            _processOpenStartup(profileCache.get(id));
            return;
        }
        if (inFlightRequests.has(id)) {
            return; // Coalesce redundant concurrent fetch attempts
        }

        const fetchPromise = safeFetch(`/api/startups/${id}`)
            .then(fullStartup => {
                inFlightRequests.delete(id);
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
                showToast('Could not load company profile. Please try again.', 'error');
            });

        inFlightRequests.set(id, fetchPromise);
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
});
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
});
