import { state, lockProgrammaticMove } from './state.js';
import { createElement, getDomain, showToast } from './utils.js';
import { safeFetch } from './api.js';
import { map, updateMarkersVisualState, createLogoContent } from './map_manager.js';

export function getSafeUrl(url) {
    if (!url || typeof url !== 'string') return null;
    const trimmed = url.trim();
    if (/^https?:\/\//i.test(trimmed)) {
        return trimmed;
    }
    if (/^[a-z0-9.+-]+:/i.test(trimmed)) {
        return null;
    }
    return 'https://' + trimmed;
}

// Global filters reference (resolved lazily)


export function updateDashboardStats(filteredStartups) {
    const statCount = document.getElementById('stat-companies') || document.getElementById('stat-count');
    const statHeadcount = document.getElementById('stat-headcount');
    const statJobs = document.getElementById('stat-jobs');

    if (statCount) statCount.textContent = String(filteredStartups.length);
    
    const totalHeadcount = filteredStartups.reduce((sum, s) => sum + Math.max(0, parseInt(s.head_count, 10) || 0), 0);
    if (statHeadcount) statHeadcount.textContent = totalHeadcount.toLocaleString();
    
    const totalJobs = filteredStartups.reduce((sum, s) => {
        const jobs = Array.isArray(s.jobs) ? s.jobs : (Array.isArray(s.job_openings) ? s.job_openings : []);
        const jCnt = (s.job_count !== undefined && s.job_count !== null && !isNaN(parseInt(s.job_count, 10))) ? Math.max(0, parseInt(s.job_count, 10)) : jobs.length;
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

export function renderDirectory(startups, customEmptyText = null) {
    const directoryList = document.getElementById('directory-list');
    if (!directoryList) return;
    
    const prevScrollTop = directoryList.scrollTop;
    const fragment = document.createDocumentFragment();

    if (!Array.isArray(startups) || startups.length === 0) {
        const emptyText = customEmptyText || 'No companies actively hiring in this location.';
        fragment.appendChild(
            createElement('div', { className: 'about-text', textContent: emptyText })
        );
        directoryList.replaceChildren(fragment);
        return;
    }

    startups.forEach(startup => {
        const isSelected = state.currentSelectedId === startup.id;
        const indClass = startup.industry ? String(startup.industry).toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
        const domain = getDomain(startup);
        const logoUrl = startup.logo_url || '';
        const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);
        const jCnt = (startup.job_count !== undefined && startup.job_count !== null && !isNaN(parseInt(startup.job_count, 10))) ? Math.max(0, parseInt(startup.job_count, 10)) : jobs.length;

        const avatarChildren = [
            createElement('span', { textContent: String(startup.name || 'S').substring(0, 1).toUpperCase() })
        ];
        if (logoUrl) {
            const img = createElement('img', { 
                src: logoUrl, 
                alt: String(startup.name || 'Logo'),
                loading: 'lazy'
            });
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

        const cardTitle = createElement('div', { className: 'card-title font-extrabold text-slate-900', textContent: String(startup.name || 'Unnamed Startup') });
        const jobBadge = createElement('span', { 
            className: 'bg-blue-50 text-[#1a73e8] border border-blue-200/80 px-2 py-0.5 rounded-lg text-[11px] font-extrabold shrink-0 ml-auto shadow-2xs',
            textContent: `💼 ${jCnt} jobs`
        });
        const cardHeader = createElement('div', { className: 'flex items-center justify-between gap-2 w-full' }, [
            cardTitle,
            jobBadge
        ]);

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

        const roleBadges = [];
        if (Array.isArray(startup.job_titles) && startup.job_titles.length > 0) {
            const displayRoles = startup.job_titles.slice(0, 3);
            displayRoles.forEach(roleTitle => {
                roleBadges.push(createElement('span', {
                    className: 'verified-pill',
                    style: 'background: #f5f3ff; color: #5b21b6; border: 1px solid #ddd6fe; font-size: 10px; font-weight: 600; padding: 2px 6px;',
                    textContent: roleTitle
                }));
            });
            if (startup.job_titles.length > 3) {
                roleBadges.push(createElement('span', {
                    className: 'verified-pill',
                    style: 'background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; font-size: 10px; font-weight: 600; padding: 2px 6px;',
                    textContent: `+${startup.job_titles.length - 3} more`
                }));
            }
        }

        const card = createElement('div', {
            className: 'directory-item' + (isSelected ? ' active' : ''),
            id: `directory-item-${startup.id}`
        }, [
            createElement('div', { className: 'card-avatar' }, avatarChildren),
            createElement('div', { className: 'card-body flex-1 min-w-0' }, [
                cardHeader,
                createElement('div', { className: 'card-tags' }, badgeTags),
                roleBadges.length > 0 ? createElement('div', { className: 'flex flex-wrap gap-1 mb-2.5 mt-1.5' }, roleBadges) : null,
                createElement('div', { className: 'card-meta' }, [
                    createElement('span', { textContent: `👥 ${headCount}` }),
                    createElement('span', { textContent: '•' }),
                    createElement('span', { textContent: `📍 ${startup.city ? String(startup.city).split(',')[0] : 'Global'}` })
                ])
            ])
        ]);

        card.addEventListener('click', () => {
            selectAndOpenStartup(startup.id);
        });

        fragment.appendChild(card);
    });

    if (startups.length >= 500) {
        fragment.appendChild(
            createElement('div', {
                className: 'about-text',
                style: 'text-align: center; padding: 12px; background: #fef3c7; color: #92400e; border-radius: 8px; margin-top: 12px; font-size: 13px;',
                textContent: '⚡ Showing top 500 active hiring companies. Zoom in on the map to reveal more local startups!'
            })
        );
    }

    directoryList.replaceChildren(fragment);
    if (prevScrollTop > 0) {
        directoryList.scrollTop = prevScrollTop;
    }
}

export function getJobSourceButtonStyle(source) {
    const s = String(source || '').trim().toLowerCase();
    if (s.includes('linkedin')) {
        return { btnClass: 'job-btn btn-linkedin', iconClass: 'fa-brands fa-linkedin', label: 'LinkedIn Apply ↗' };
    }
    if (s.includes('google')) {
        return { btnClass: 'job-btn btn-google', iconClass: 'fa-brands fa-google', label: 'Google Jobs ↗' };
    }
    if (s.includes('instahyre')) {
        return { btnClass: 'job-btn btn-instahyre', iconClass: 'fa-solid fa-bolt', label: 'Instahyre Apply ↗' };
    }
    if (s === 'yc' || s.includes('y combinator') || s.includes('ycombinator')) {
        return { btnClass: 'job-btn btn-yc', iconClass: 'fa-brands fa-y-combinator', label: 'YC Apply ↗' };
    }
    if (s.includes('Green House') || s.includes('greenhouse') || s.includes('lever')) {
        return { btnClass: 'job-btn btn-ats', iconClass: 'fa-solid fa-file-lines', label: 'Green House ↗' };
    }
    if (s.includes('indeed')) {
        return { btnClass: 'job-btn btn-indeed', iconClass: 'fa-solid fa-briefcase', label: 'Indeed Apply ↗' };
    }
    if (s.includes('wellfound') || s.includes('angellist')) {
        return { btnClass: 'job-btn btn-wellfound', iconClass: 'fa-brands fa-angellist', label: 'Wellfound Apply ↗' };
    }
    if (s.includes('naukri')) {
        return { btnClass: 'job-btn btn-naukri', iconClass: 'fa-solid fa-user-tie', label: 'Naukri Apply ↗' };
    }
    if (s.includes('glassdoor')) {
        return { btnClass: 'job-btn btn-glassdoor', iconClass: 'fa-solid fa-door-open', label: 'Glassdoor Apply ↗' };
    }
    if (s.includes('cutshort')) {
        return { btnClass: 'job-btn btn-cutshort', iconClass: 'fa-solid fa-scissors', label: 'Cutshort Apply ↗' };
    }
    if (s.includes('hirist')) {
        return { btnClass: 'job-btn btn-hirist', iconClass: 'fa-solid fa-layer-group', label: 'Hirist Apply ↗' };
    }
    return { btnClass: 'job-btn btn-direct', iconClass: 'fa-solid fa-up-right-from-square', label: 'Company Site ↗' };
}

export function renderDrawerDetails(startup) {
    const drawerContent = document.getElementById('drawer-content');
    if (!drawerContent) return;
    
    const fragment = document.createDocumentFragment();
    const indClass = startup.industry ? String(startup.industry).toLowerCase().replace(/[^a-z0-9]/g, '') : 'software';
    const domain = getDomain(startup);
    const logoUrl = startup.logo_url || '';
    const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);
    const jCnt = (startup.job_count !== undefined && startup.job_count !== null && !isNaN(parseInt(startup.job_count, 10))) ? Math.max(0, parseInt(startup.job_count, 10)) : jobs.length;

    // Unified Profile Card (Consolidates Hero, Badges, Metrics, and About into one clean card)
    const headCount = Math.max(0, parseInt(startup.head_count, 10) || 0);
    const descText = (startup.description && String(startup.description).trim()) ? String(startup.description).trim() : 'No description provided for this company.';

    const avatarChildren = [
        createElement('span', { className: 'drawer-avatar-letter', textContent: String(startup.name || 'S').substring(0, 1).toUpperCase() })
    ];
    if (logoUrl) {
        const img = createElement('img', { src: logoUrl, className: 'drawer-avatar-img', alt: String(startup.name || 'Logo') });
        img.onerror = () => { img.style.display = 'none'; };
        avatarChildren.push(img);
    }
    const avatarBox = createElement('div', { className: 'drawer-avatar-box' }, avatarChildren);

    const titleRowChildren = [
        createElement('h2', { className: 'drawer-company-name', textContent: String(startup.name || 'Unnamed Startup') })
    ];
    if (startup.website && startup.is_active_website !== false) {
        const safeWebsite = getSafeUrl(startup.website);
        if (safeWebsite) {
            const siteLink = createElement('a', {
                href: safeWebsite,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'drawer-website-btn',
                textContent: 'Website ↗'
            });
            titleRowChildren.push(siteLink);
        }
    }
    const titleRow = createElement('div', { className: 'drawer-title-row' }, titleRowChildren);

    const metaLine = createElement('div', { className: 'drawer-meta-line' }, [
        createElement('span', { textContent: `📍 ${startup.city || 'Bengaluru'}` }),
        createElement('span', { textContent: '•' }),
        createElement('span', { textContent: `👥 ${headCount > 0 ? headCount.toLocaleString() + ' Employees' : 'Growing Team'}` })
    ]);

    const headerTextCol = createElement('div', { className: 'drawer-header-text' }, [
        titleRow,
        metaLine
    ]);

    const headerTopRow = createElement('div', { className: 'drawer-header-top' }, [
        avatarBox,
        headerTextCol
    ]);

    const badgesList = [
        createElement('span', { className: `pill pill-${indClass}`, textContent: startup.industry || 'Technology' }),
        createElement('span', { className: 'verified-pill', textContent: jCnt > 0 ? `💼 ${jCnt} Active Jobs` : 'Hiring Soon' })
    ];
    if (startup.funding_stage && startup.funding_stage !== "N/A") {
        badgesList.push(createElement('span', { className: 'verified-pill', style: 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;', textContent: `🌱 ${startup.funding_stage}` }));
    }
    if (startup.verified_email) {
        badgesList.push(createElement('span', { className: 'verified-pill', style: 'background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe;', textContent: `✉️ Verified HR` }));
    }
    const foundersList = Array.isArray(startup.founders) ? startup.founders : [];
    if (foundersList.length > 0) {
        badgesList.push(createElement('span', { className: 'verified-pill', style: 'background: #faf5ff; color: #6b21a8; border: 1px solid #e9d5ff;', textContent: `✨ Direct Founder Access (${foundersList.length})` }));
    }

    const badgesRow = createElement('div', { className: 'drawer-badges-row' }, badgesList);

    const descriptionBox = createElement('div', { className: 'drawer-description-box' }, [
        createElement('p', { className: 'about-text', textContent: descText })
    ]);

    const profileCard = createElement('div', { className: 'drawer-profile-card' }, [
        headerTopRow,
        badgesRow,
        descriptionBox
    ]);

    fragment.appendChild(profileCard);

    // Founders Section
    if (foundersList.length > 0) {
        const foundersContainer = createElement('div', { className: 'founders-grid' });
        foundersList.forEach(f => {
            const fCardChildren = [
                createElement('span', { className: 'founder-name', textContent: f.name || 'Anonymous Founder' }),
                createElement('span', { className: 'founder-role', textContent: f.role || 'Founder / Leadership' })
            ];
            if (f.linkedin) {
                const safeLinkedin = getSafeUrl(f.linkedin);
                if (safeLinkedin) {
                    fCardChildren.push(
                        createElement('a', {
                            href: safeLinkedin,
                            target: '_blank',
                            rel: 'noopener noreferrer',
                            className: 'founder-link',
                            textContent: 'LinkedIn Profile &rarr;'
                        })
                    );
                }
            }
            foundersContainer.appendChild(createElement('div', { className: 'founder-card' }, fCardChildren));
        });

        fragment.appendChild(
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

            const styleInfo = getJobSourceButtonStyle(j.source);
            const safeJobUrl = getSafeUrl(j.url);
            const applyBtn = safeJobUrl ? createElement('a', {
                href: safeJobUrl,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: styleInfo.btnClass
            }, [
                createElement('i', { className: `${styleInfo.iconClass} mr-1.5` }),
                styleInfo.label
            ]) : null;

            const jCard = createElement('div', { className: 'job-card' }, [
                createElement('div', { className: 'job-info' }, [
                    createElement('h4', { textContent: j.title || 'Open Position' }),
                    createElement('div', { className: 'job-tags' }, tagsChildren)
                ]),
                applyBtn
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

    fragment.appendChild(
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
        fragment.appendChild(
            createElement('div', { className: 'other-loc-box' }, hrBoxChildren)
        );
    }

    drawerContent.replaceChildren(fragment);
}

export function selectAndOpenStartup(id) {
    console.log('[DEBUG selectAndOpenStartup] id=' + id + ' state.currentSelectedId=' + state.currentSelectedId);
    if (state.activeGeocodeController) {
        state.activeGeocodeController.abort();
        state.activeGeocodeController = null;
    }
    state.currentSelectedId = id;
    
    const queryParams = new URLSearchParams();
    if (state.currentFilters.role) queryParams.set('role', state.currentFilters.role);
    if (state.currentFilters.salary_min) queryParams.set('salary_min', state.currentFilters.salary_min);
    if (state.currentFilters.exp_level) queryParams.set('exp_level', state.currentFilters.exp_level);
    if (state.currentFilters.work_type) queryParams.set('work_type', state.currentFilters.work_type);
    
    const queryString = queryParams.toString();
    const cacheKey = queryString ? `${id}_${queryString}` : String(id);

    for (const [pendingId, controller] of state.inFlightRequests.entries()) {
        if (String(pendingId) !== cacheKey) {
            controller.abort();
            state.inFlightRequests.delete(pendingId);
        }
    }

    // 1. Check ProfileCache (0 network calls)
    if (state.profileCache.has(cacheKey)) {
        const cached = state.profileCache.get(cacheKey);
        _processOpenStartup(cached);
        return Promise.resolve(cached);
    }

    // 2. Check Request Coalescing (inFlightPromises / inFlightRequests)
    if (state.inFlightPromises.has(id) || state.inFlightPromises.has(cacheKey) || state.inFlightRequests.has(id) || state.inFlightRequests.has(cacheKey)) {
        const existingPromise = state.inFlightPromises.get(id) || state.inFlightPromises.get(cacheKey);
        if (existingPromise) {
            existingPromise.then(fullStartup => {
                if (state.currentSelectedId === id) {
                    _processOpenStartup(fullStartup);
                }
            }).catch(() => {});
            return existingPromise;
        }
        return;
    }

    // 3. Create fetch promise, store in inFlightPromises, cleanup in .finally()
    const controller = new AbortController();
    state.inFlightRequests.set(id, controller);
    state.inFlightRequests.set(cacheKey, controller);

    const url = `/api/company/${id}${queryString ? '?' + queryString : ''}`;
    const promise = safeFetch(url, { signal: controller.signal })
        .then(fullStartup => {
            if (controller.signal.aborted) return fullStartup;
            if (fullStartup && !fullStartup.error) {
                if (state.profileCache.size >= 50) {
                    const firstKey = state.profileCache.keys().next().value;
                    state.profileCache.delete(firstKey);
                }
                state.profileCache.set(cacheKey, fullStartup);
                if (state.currentSelectedId === id) {
                    _processOpenStartup(fullStartup);
                }
            } else {
                const fallbackStartup = state.startupsData.find(s => String(s.id) === String(id));
                if (fallbackStartup) {
                    _processOpenStartup(fallbackStartup);
                } else {
                    showToast('Could not load company profile. Please try again.', 'error');
                }
            }
            return fullStartup;
        })
        .catch(err => {
            if (err.name === 'AbortError') throw err;
            const fallbackStartup = state.startupsData.find(s => String(s.id) === String(id));
            if (fallbackStartup) {
                _processOpenStartup(fallbackStartup);
                return fallbackStartup;
            } else {
                showToast('Could not load company profile. Please try again.', 'error');
                throw err;
            }
        })
        .finally(() => {
            state.inFlightRequests.delete(id);
            state.inFlightRequests.delete(cacheKey);
            state.inFlightPromises.delete(id);
            state.inFlightPromises.delete(cacheKey);
        });

    state.inFlightPromises.set(id, promise);
    state.inFlightPromises.set(cacheKey, promise);

    return promise;
}

export function _processOpenStartup(fullStartup) {
    if (fullStartup && !fullStartup.error) {
        const id = fullStartup.id;
        console.log('[DEBUG _processOpenStartup] id=' + id + ' state.currentSelectedId=' + state.currentSelectedId);
        const idx = state.startupsData.findIndex(s => s.id === id);
        if (idx !== -1) state.startupsData[idx] = fullStartup;
        else state.startupsData.push(fullStartup);

        if (state.tempRemoteMarker) {
            state.tempRemoteMarker.remove();
            state.tempRemoteMarker = null;
        }

        state.currentSelectedId = id;
        if (window.location.hash !== `#company_id=${id}`) {
            window.location.hash = `company_id=${id}`;
        }

        let flyCenter = [fullStartup.lng || 77.5946, fullStartup.lat || 12.9716];
        let flyZoom = 16;

        if (fullStartup.has_pin === false) {
            const centerLng = state.defaultLocation ? state.defaultLocation[0] : 77.5946;
            const centerLat = state.defaultLocation ? state.defaultLocation[1] : 12.9716;
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

        lockProgrammaticMove(2500);
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
