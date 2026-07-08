import { state } from './state.js';
import { createElement, getDomain, showToast } from './utils.js';
import { safeFetch } from './api.js';
import { map, updateMarkersVisualState, createLogoContent } from './map_manager.js';

// Global filters reference (resolved lazily)


export function updateDashboardStats(filteredStartups) {
    const statCount = document.getElementById('stat-count');
    const statHeadcount = document.getElementById('stat-headcount');
    const statJobs = document.getElementById('stat-jobs');

    if (statCount) statCount.textContent = String(filteredStartups.length);
    
    const totalHeadcount = filteredStartups.reduce((sum, s) => sum + Math.max(0, parseInt(s.head_count, 10) || 0), 0);
    if (statHeadcount) statHeadcount.textContent = totalHeadcount.toLocaleString();
    
    const totalJobs = filteredStartups.reduce((sum, s) => {
        const jobs = Array.isArray(s.jobs) ? s.jobs : (Array.isArray(s.job_openings) ? s.job_openings : []);
        const jCnt = s.job_count !== undefined && !isNaN(s.job_count) ? Math.max(0, parseInt(s.job_count, 10)) : jobs.length;
        return sum + jCnt;
    }, 0);
    if (statJobs) statJobs.textContent = String(totalJobs);
}

export function showDirectoryLoading() {
    const directoryList = document.getElementById('directory-list');
    if (!directoryList) return;
    directoryList.replaceChildren(
        createElement('div', { 
            className: 'flex flex-col items-center justify-center py-12 text-slate-400 gap-3 font-semibold text-sm',
            children: [
                createElement('i', { className: 'fa-solid fa-circle-notch animate-spin text-2xl text-[#1a73e8]' }),
                createElement('span', { textContent: 'Finding jobs in neighborhood...' })
            ]
        })
    );
}

export function renderDirectory(startups) {
    const directoryList = document.getElementById('directory-list');
    if (!directoryList) return;
    
    directoryList.replaceChildren();
    if (startups.length === 0) {
        directoryList.appendChild(
            createElement('div', { className: 'about-text', textContent: 'No companies match your criteria.' })
        );
        return;
    }

    startups.forEach(startup => {
        const isSelected = state.currentSelectedId === startup.id;
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

        const cardTitle = createElement('div', { className: 'card-title', textContent: String(startup.name || 'Unnamed Startup') });
        const badgeTags = [
            createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry || 'Tech' })
        ];
        if (startup.has_pin === false) {
            badgeTags.push(createElement('span', { className: 'verified-pill', style: 'background: #fef9c3; color: #854d0e; border: 1px solid #fde047;', textContent: '📍 Remote / Hub' }));
        }
        if (startup.funding_stage && startup.funding_stage !== "N/A") {
            badgeTags.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `🌱 ${startup.funding_stage}` }));
        }
        if (startup.verified_email || (Array.isArray(startup.founder_names) && startup.founder_names.length > 0)) {
            badgeTags.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: '✨ Direct Access' }));
        }

        const headCount = Math.max(0, parseInt(startup.head_count, 10) || 0);
        const card = createElement('div', {
            className: 'directory-item' + (isSelected ? ' active' : ''),
            id: `directory-item-${startup.id}`
        }, [
            createElement('div', { className: 'card-avatar' }, avatarChildren),
            createElement('div', { className: 'card-body' }, [
                cardTitle,
                createElement('div', { className: 'card-tags' }, badgeTags),
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

export function renderDrawerDetails(startup) {
    const drawerContent = document.getElementById('drawer-content');
    if (!drawerContent) return;
    
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
    const urlParams = new URLSearchParams(window.location.search);
    const searchedCity = (urlParams.get('city') || '').toLowerCase();

    const blrJobs = jobs.filter(j => {
        if (!j || typeof j !== 'object') return false;
        if (j.location) {
            const loc = String(j.location).toLowerCase();
            let locMatch = false;
            if (searchedCity) {
                const cleanSearchCity = searchedCity.split(',')[0].trim();
                if (cleanSearchCity && loc.includes(cleanSearchCity)) {
                    locMatch = true;
                }
            }
            if (loc.includes('bengaluru') || loc.includes('bangalore') || loc.includes('india')) {
                locMatch = true;
            }
            const startupCityClean = (startup.city || '').toLowerCase().split(',')[0].trim();
            if (startupCityClean && loc.includes(startupCityClean)) {
                locMatch = true;
            }
            if (!locMatch) {
                return false;
            }
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
                tagsChildren.push(jtTag);
            }
            if (j.experience || !j.job_type) {
                const expTag = createElement('span', { className: 'job-tag badge-attr', textContent: `⏳ ${expText}` });
                tagsChildren.push(expTag);
            }
            tagsChildren.push(createElement('span', { className: 'job-tag badge-attr', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `💰 ${salaryText}` }));
            if (Array.isArray(j.skills) && j.skills.length > 0) {
                j.skills.forEach(skill => {
                    const skillTag = createElement('span', { className: 'job-tag badge-attr', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: `🛠 ${skill}` });
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

export function selectAndOpenStartup(id) {
    state.currentSelectedId = id;
    for (const [pendingId, controller] of state.inFlightRequests.entries()) {
        if (pendingId !== id) {
            controller.abort();
            state.inFlightRequests.delete(pendingId);
        }
    }

    if (state.profileCache.has(id)) {
        _processOpenStartup(state.profileCache.get(id));
        return;
    }
    if (state.inFlightRequests.has(id)) {
        return;
    }

    const controller = new AbortController();
    state.inFlightRequests.set(id, controller);

    safeFetch(`/api/startups/${id}`, { signal: controller.signal })
        .then(fullStartup => {
            state.inFlightRequests.delete(id);
            if (controller.signal.aborted) return;
            if (state.currentSelectedId === id && fullStartup && !fullStartup.error) {
                if (state.profileCache.size >= 50) {
                    const firstKey = state.profileCache.keys().next().value;
                    state.profileCache.delete(firstKey);
                }
                state.profileCache.set(id, fullStartup);
                _processOpenStartup(fullStartup);
            }
        })
        .catch(err => {
            state.inFlightRequests.delete(id);
            if (err.name === 'AbortError') return;
            showToast('Could not load company profile. Please try again.', 'error');
        });
}

export function _processOpenStartup(fullStartup) {
    if (fullStartup && !fullStartup.error) {
        const id = fullStartup.id;
        const idx = state.startupsData.findIndex(s => s.id === id);
        if (idx !== -1) state.startupsData[idx] = fullStartup;
        else state.startupsData.push(fullStartup);

        if (state.tempRemoteMarker) {
            state.tempRemoteMarker.remove();
            state.tempRemoteMarker = null;
        }

        state.currentSelectedId = id;
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
            state.tempRemoteMarker = new maplibregl.Marker({
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
        const detailsDrawer = document.getElementById('details-drawer');
        if (detailsDrawer) {
            detailsDrawer.classList.add('active');
            detailsDrawer.setAttribute('aria-hidden', 'false');
        }
        
        window.WorldTechApp.applyFiltering();

        setTimeout(() => {
            scrollToCard(id);
        }, 50);
        updateMarkersVisualState();
    }
}

export function scrollToCard(id) {
    const container = document.getElementById('directory-list');
    const card = document.getElementById(`directory-item-${id}`);
    if (!container || !card) return;

    requestAnimationFrame(() => {
        const relativeTop = card.offsetTop - container.offsetTop;
        const targetScrollTop = relativeTop - (container.clientHeight / 2) + (card.clientHeight / 2);
        container.scrollTo({
            top: targetScrollTop,
            behavior: 'auto'
        });
    });
}
