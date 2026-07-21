import { state } from './state.js';
import { createElement, showToast } from './utils.js';

export function initResumeBuilder() {
    const modal = document.getElementById('resume-builder-modal');
    const openBtn = document.getElementById('open-resume-builder-btn');
    const closeBtn = document.getElementById('close-resume-modal-btn');
    const autofillBtn = document.getElementById('autofill-job-btn');
    const printBtn = document.getElementById('print-resume-btn');
    const copyBtn = document.getElementById('copy-resume-btn');

    if (!modal) return;

    if (openBtn) {
        openBtn.addEventListener('click', () => {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            updateResumePreview();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        });
    }

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        }
    });

    // Inputs change listeners for live preview update
    const formInputs = [
        'res-fullname', 'res-title', 'res-email', 'res-phone', 'res-location',
        'res-summary', 'res-exp-company', 'res-exp-role', 'res-exp-period',
        'res-exp-details', 'res-edu-school', 'res-edu-[#res-edu-degree]', 'res-edu-degree',
        'res-edu-year', 'res-skills'
    ];

    formInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateResumePreview);
        }
    });

    // Template style switcher
    const tmplModern = document.getElementById('tmpl-btn-modern');
    const tmplMinimal = document.getElementById('tmpl-btn-minimal');
    const tmplClassic = document.getElementById('tmpl-btn-classic');

    let currentTemplate = 'modern';

    if (tmplModern) {
        tmplModern.addEventListener('click', () => {
            currentTemplate = 'modern';
            setActiveTemplateBtn(tmplModern);
            updateResumePreview();
        });
    }
    if (tmplMinimal) {
        tmplMinimal.addEventListener('click', () => {
            currentTemplate = 'minimal';
            setActiveTemplateBtn(tmplMinimal);
            updateResumePreview();
        });
    }
    if (tmplClassic) {
        tmplClassic.addEventListener('click', () => {
            currentTemplate = 'classic';
            setActiveTemplateBtn(tmplClassic);
            updateResumePreview();
        });
    }

    function setActiveTemplateBtn(activeBtn) {
        [tmplModern, tmplMinimal, tmplClassic].forEach(btn => {
            if (!btn) return;
            if (btn === activeBtn) {
                btn.className = 'px-2.5 py-1 text-xs font-extrabold rounded-lg bg-white text-blue-600 shadow-xs';
            } else {
                btn.className = 'px-2.5 py-1 text-xs font-bold rounded-lg text-slate-600 hover:text-slate-900';
            }
        });
    }

    if (autofillBtn) {
        autofillBtn.addEventListener('click', () => {
            if (state.currentSelectedId !== null && state.startupsData) {
                const startup = state.startupsData.find(s => s.id === state.currentSelectedId);
                if (startup) {
                    const jobs = Array.isArray(startup.jobs) ? startup.jobs : (Array.isArray(startup.job_openings) ? startup.job_openings : []);
                    const firstJob = jobs.length > 0 ? jobs[0] : null;

                    const titleEl = document.getElementById('res-title');
                    const compEl = document.getElementById('res-exp-company');
                    const roleEl = document.getElementById('res-exp-role');
                    const locEl = document.getElementById('res-location');
                    const skillsEl = document.getElementById('res-skills');

                    if (firstJob && titleEl) titleEl.value = firstJob.title || 'Software Engineer';
                    if (compEl) compEl.value = startup.name || '';
                    if (roleEl && firstJob) roleEl.value = firstJob.title || '';
                    if (locEl) locEl.value = startup.city || 'Bengaluru, India';
                    if (skillsEl && firstJob && Array.isArray(firstJob.skills)) {
                        skillsEl.value = firstJob.skills.join(', ');
                    }

                    updateResumePreview();
                    showToast(`Autofilled details from ${startup.name}`, 'success');
                    return;
                }
            }
            showToast('Select a company from the map or directory to autofill details.', 'info');
        });
    }

    if (printBtn) {
        printBtn.addEventListener('click', () => {
            const previewEl = document.getElementById('resume-live-preview');
            if (!previewEl) return;
            const printWindow = window.open('', '_blank');
            printWindow.document.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Resume - ${document.getElementById('res-fullname')?.value || 'JobMap'}</title>
                    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
                    <style>
                        body { font-family: system-ui, -apple-system, sans-serif; padding: 20px; }
                        @media print { body { padding: 0; } }
                    </style>
                </head>
                <body>
                    ${previewEl.innerHTML}
                    <script>
                        window.onload = function() { window.print(); window.close(); }
                    </script>
                </body>
                </html>
            `);
            printWindow.document.close();
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            const previewEl = document.getElementById('resume-live-preview');
            if (previewEl) {
                navigator.clipboard.writeText(previewEl.innerText).then(() => {
                    showToast('Resume text copied to clipboard!', 'success');
                });
            }
        });
    }

    function updateResumePreview() {
        const previewEl = document.getElementById('resume-live-preview');
        if (!previewEl) return;

        const fullname = document.getElementById('res-fullname')?.value || 'Alex Morgan';
        const title = document.getElementById('res-title')?.value || 'Senior Software Engineer';
        const email = document.getElementById('res-email')?.value || 'alex.morgan@example.com';
        const phone = document.getElementById('res-phone')?.value || '+1 (555) 019-2834';
        const location = document.getElementById('res-location')?.value || 'San Francisco, CA';
        const summary = document.getElementById('res-summary')?.value || 'Impact-driven software engineer with 5+ years of experience building scalable full-stack web applications and microservices.';
        const company = document.getElementById('res-exp-company')?.value || 'TechCorp Systems';
        const expRole = document.getElementById('res-exp-role')?.value || 'Lead Frontend Developer';
        const period = document.getElementById('res-exp-period')?.value || '2022 - Present';
        const details = document.getElementById('res-exp-details')?.value || 'Architected high-throughput reactive dashboards serving over 500,000 active users.';
        const school = document.getElementById('res-edu-school')?.value || 'Stanford University';
        const degree = document.getElementById('res-edu-degree')?.value || 'B.S. Computer Science';
        const year = document.getElementById('res-edu-year')?.value || '2021';
        const rawSkills = document.getElementById('res-skills')?.value || 'JavaScript, React, Node.js, Python, PostgreSQL, TailWind CSS';

        const skillsArr = rawSkills.split(',').map(s => s.trim()).filter(Boolean);

        let previewHTML = '';

        if (currentTemplate === 'minimal') {
            previewHTML = `
                <div class="bg-white p-8 rounded-2xl shadow-sm border border-slate-200 text-slate-800 space-y-6">
                    <div class="border-b border-slate-200 pb-4">
                        <h1 class="text-2xl font-black text-slate-900 tracking-tight">${fullname}</h1>
                        <p class="text-sm font-semibold text-slate-600">${title}</p>
                        <div class="flex flex-wrap gap-3 text-xs text-slate-400 mt-2 font-medium">
                            <span>📧 ${email}</span>
                            <span>📞 ${phone}</span>
                            <span>📍 ${location}</span>
                        </div>
                    </div>
                    <div>
                        <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">About</h2>
                        <p class="text-xs text-slate-600 leading-relaxed">${summary}</p>
                    </div>
                    <div>
                        <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Experience</h2>
                        <div class="flex justify-between items-baseline mb-1">
                            <span class="text-xs font-bold text-slate-800">${expRole} • ${company}</span>
                            <span class="text-[11px] text-slate-400 font-mono">${period}</span>
                        </div>
                        <p class="text-xs text-slate-600 leading-relaxed">${details}</p>
                    </div>
                    <div>
                        <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Education</h2>
                        <p class="text-xs font-bold text-slate-800">${degree} — <span class="font-normal text-slate-600">${school} (${year})</span></p>
                    </div>
                    <div>
                        <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Skills</h2>
                        <div class="flex flex-wrap gap-1.5">
                            ${skillsArr.map(s => `<span class="bg-slate-100 text-slate-700 text-[11px] font-bold px-2 py-0.5 rounded-md">${s}</span>`).join('')}
                        </div>
                    </div>
                </div>
            `;
        } else if (currentTemplate === 'classic') {
            previewHTML = `
                <div class="bg-white p-8 rounded-2xl shadow-sm border border-slate-200 text-slate-800 space-y-6">
                    <div class="text-center border-b-2 border-slate-900 pb-4">
                        <h1 class="text-3xl font-serif font-bold text-slate-900">${fullname}</h1>
                        <p class="text-xs uppercase tracking-widest font-bold text-slate-600 mt-1">${title}</p>
                        <div class="flex justify-center gap-4 text-xs text-slate-500 mt-2 font-serif">
                            <span>${email}</span> | <span>${phone}</span> | <span>${location}</span>
                        </div>
                    </div>
                    <div>
                        <h2 class="text-xs font-serif font-bold uppercase tracking-wider text-slate-900 border-b border-slate-300 pb-1 mb-2">Professional Summary</h2>
                        <p class="text-xs text-slate-700 leading-relaxed font-serif">${summary}</p>
                    </div>
                    <div>
                        <h2 class="text-xs font-serif font-bold uppercase tracking-wider text-slate-900 border-b border-slate-300 pb-1 mb-2">Experience</h2>
                        <div class="flex justify-between font-serif mb-1">
                            <span class="text-xs font-bold text-slate-900">${expRole}, ${company}</span>
                            <span class="text-xs text-slate-500">${period}</span>
                        </div>
                        <p class="text-xs text-slate-700 font-serif leading-relaxed">${details}</p>
                    </div>
                    <div>
                        <h2 class="text-xs font-serif font-bold uppercase tracking-wider text-slate-900 border-b border-slate-300 pb-1 mb-2">Education</h2>
                        <p class="text-xs text-slate-900 font-serif font-bold">${degree}, ${school} <span class="font-normal text-slate-500">(${year})</span></p>
                    </div>
                    <div>
                        <h2 class="text-xs font-serif font-bold uppercase tracking-wider text-slate-900 border-b border-slate-300 pb-1 mb-2">Technical Skills</h2>
                        <p class="text-xs text-slate-700 font-serif">${skillsArr.join(' • ')}</p>
                    </div>
                </div>
            `;
        } else {
            // Default: Modern Template
            previewHTML = `
                <div class="bg-white p-8 rounded-2xl shadow-md border border-blue-100 text-slate-800 space-y-6">
                    <div class="bg-gradient-to-r from-blue-600 to-indigo-700 -m-8 p-8 mb-4 rounded-t-2xl text-white">
                        <h1 class="text-2xl font-extrabold tracking-tight">${fullname}</h1>
                        <p class="text-blue-100 text-xs font-semibold mt-0.5">${title}</p>
                        <div class="flex flex-wrap gap-4 text-[11px] text-blue-200 mt-3 font-medium">
                            <span class="flex items-center gap-1"><i class="fa-solid fa-envelope text-[10px]"></i> ${email}</span>
                            <span class="flex items-center gap-1"><i class="fa-solid fa-phone text-[10px]"></i> ${phone}</span>
                            <span class="flex items-center gap-1"><i class="fa-solid fa-location-dot text-[10px]"></i> ${location}</span>
                        </div>
                    </div>
                    <div>
                        <h2 class="text-xs font-black uppercase tracking-wider text-blue-600 mb-1 flex items-center gap-1">
                            <i class="fa-solid fa-user text-[10px]"></i> Profile Summary
                        </h2>
                        <p class="text-xs text-slate-600 leading-relaxed font-medium">${summary}</p>
                    </div>
                    <div>
                        <h2 class="text-xs font-black uppercase tracking-wider text-blue-600 mb-2 flex items-center gap-1">
                            <i class="fa-solid fa-briefcase text-[10px]"></i> Professional Experience
                        </h2>
                        <div class="bg-blue-50/50 p-3 rounded-xl border border-blue-100">
                            <div class="flex justify-between items-baseline mb-1">
                                <span class="text-xs font-extrabold text-slate-900">${expRole}</span>
                                <span class="text-[10px] font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded-full">${period}</span>
                            </div>
                            <span class="text-xs font-bold text-blue-600 block mb-1.5">${company}</span>
                            <p class="text-xs text-slate-600 leading-relaxed">${details}</p>
                        </div>
                    </div>
                    <div>
                        <h2 class="text-xs font-black uppercase tracking-wider text-blue-600 mb-2 flex items-center gap-1">
                            <i class="fa-solid fa-graduation-cap text-[10px]"></i> Education
                        </h2>
                        <p class="text-xs font-bold text-slate-900">${degree} <span class="text-slate-500 font-medium">— ${school} (${year})</span></p>
                    </div>
                    <div>
                        <h2 class="text-xs font-black uppercase tracking-wider text-blue-600 mb-2 flex items-center gap-1">
                            <i class="fa-solid fa-code text-[10px]"></i> Key Skills & Expertise
                        </h2>
                        <div class="flex flex-wrap gap-1.5">
                            ${skillsArr.map(s => `<span class="bg-blue-50 text-blue-700 border border-blue-200 text-[11px] font-extrabold px-2.5 py-0.5 rounded-lg shadow-xs">${s}</span>`).join('')}
                        </div>
                    </div>
                </div>
            `;
        }

        previewEl.innerHTML = previewHTML;
    }
}
