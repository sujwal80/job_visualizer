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
            const profileLink = document.getElementById('navbar-profile-link');
            const loginLink = document.getElementById('navbar-login-link');
            const authUserAvatar = document.getElementById('auth-user-avatar');
            const authUserName = document.getElementById('auth-user-name');
            const authUserEmail = document.getElementById('auth-user-email');
            
            if (data.authenticated && data.user) {
                if (profileLink) profileLink.classList.remove('hidden');
                if (loginLink) loginLink.classList.add('hidden');
                if (authUserAvatar) authUserAvatar.src = data.user.picture || 'https://lh3.googleusercontent.com/a/default-user';
                if (authUserName) authUserName.textContent = data.user.name || 'Developer Account';
                if (authUserEmail) authUserEmail.textContent = data.user.email || '';
            } else {
                if (profileLink) profileLink.classList.add('hidden');
                if (loginLink) loginLink.classList.remove('hidden');
            }
            return data;
        })
        .catch(err => {
            console.warn('[Auth Status] Failed to query auth session:', err);
        });
}
