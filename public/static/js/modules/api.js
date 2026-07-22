import { state } from './state.js';
import { showToast } from './utils.js';

export async function safeFetch(url, options = {}) {
    if (Date.now() < state.rateLimitedUntil) {
        throw new Error('Client-side rate limit active');
    }
    try {
        const response = await fetch(url, options);
        if (response.status === 429) {
            const retryHeader = response.headers.get('Retry-After');
            const cooldown = retryHeader ? parseInt(retryHeader, 10) : 10;
            state.rateLimitedUntil = Date.now() + (isNaN(cooldown) ? 10 : cooldown) * 1000;
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
        if (typeof url === 'string' && (url.includes('/api/company') || url.includes('/api/companies'))) {
            const dataVersion = response.headers && typeof response.headers.get === 'function' ? response.headers.get('X-Data-Version') : null;
            if (dataVersion !== null && dataVersion !== undefined && dataVersion !== '') {
                if (state.currentDataVersion !== null && state.currentDataVersion !== undefined && state.currentDataVersion !== dataVersion) {
                    if (state.queryCache && typeof state.queryCache.clear === 'function') {
                        state.queryCache.clear();
                    }
                    if (state.profileCache && typeof state.profileCache.clear === 'function') {
                        state.profileCache.clear();
                    }
                }
                state.currentDataVersion = dataVersion;
            }
        }
        return response.json();
    } catch (err) {
        if (err.name === 'AbortError') throw err;
        console.error('[API Fetch Error]:', err);
        throw err;
    }
}

export function checkAuthStatus() {
    return fetch('/api/auth/status')
        .then(r => r.json())
        .then(data => {
            const anonBlocks = document.querySelectorAll('.auth-anon');
            const userBlocks = document.querySelectorAll('.auth-user');
            const userAvatars = document.querySelectorAll('.user-avatar');
            const userNames = document.querySelectorAll('.user-name');
            
            if (data.authenticated && data.user) {
                anonBlocks.forEach(el => el.classList.add('hidden'));
                userBlocks.forEach(el => el.classList.remove('hidden'));
                userAvatars.forEach(el => {
                    el.src = data.user.picture || 'https://lh3.googleusercontent.com/a/default-user';
                });
                userNames.forEach(el => {
                    el.textContent = data.user.name || 'Developer Account';
                });
                state.user = data.user;
            } else {
                anonBlocks.forEach(el => el.classList.remove('hidden'));
                userBlocks.forEach(el => el.classList.add('hidden'));
                state.user = null;
            }
            return data;
        })
        .catch(err => {
            console.warn('[Auth Status] Failed to query auth session:', err);
        });
}
