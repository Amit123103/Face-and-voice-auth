/**
 * FaceVoiceAuth — Utility Functions
 * Shared helpers for API calls, DOM manipulation, toast notifications, and state management.
 */

// API_BASE: empty = same origin (works through nginx proxy in Docker)
// Override with window.API_BASE_URL for direct backend dev mode
const API_BASE = window.API_BASE_URL || '';

/* ── Token Management ── */
const TokenStore = {
    get() {
        return sessionStorage.getItem('access_token');
    },
    set(token) {
        sessionStorage.setItem('access_token', token);
    },
    clear() {
        sessionStorage.removeItem('access_token');
        sessionStorage.removeItem('user_data');
    },
    getUserData() {
        const raw = sessionStorage.getItem('user_data');
        return raw ? JSON.parse(raw) : null;
    },
    setUserData(data) {
        sessionStorage.setItem('user_data', JSON.stringify(data));
    }
};

/* ── API Client ── */
async function apiRequest(path, options = {}) {
    const url = `${API_BASE}${path}`;
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
    };

    const token = TokenStore.get();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const csrfToken = getCookie('csrf_token');
    if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken;
    }

    try {
        const response = await fetch(url, {
            ...options,
            headers,
            credentials: 'include',
        });

        if (response.status === 401) {
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${TokenStore.get()}`;
                const retryResponse = await fetch(url, { ...options, headers, credentials: 'include' });
                return await handleResponse(retryResponse);
            } else {
                TokenStore.clear();
                window.location.href = '/login.html';
                return null;
            }
        }

        return await handleResponse(response);
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
        throw error;
    }
}

async function handleResponse(response) {
    const contentType = response.headers.get('content-type') || '';

    if (!response.ok) {
        let errorDetail = `HTTP ${response.status}`;
        if (contentType.includes('application/json')) {
            const body = await response.json();
            errorDetail = body.detail || body.title || errorDetail;
        }
        throw new Error(errorDetail);
    }

    if (contentType.includes('application/json')) {
        return await response.json();
    }
    return await response.text();
}

async function refreshAccessToken() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
        });
        if (response.ok) {
            const data = await response.json();
            TokenStore.set(data.access_token);
            return true;
        }
        return false;
    } catch {
        return false;
    }
}

/* ── Cookie Helpers ── */
function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[2]) : '';
}

/* ── Toast Notification System ── */
let toastContainer = null;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        toastContainer.id = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

function showToast(message, type = 'info', duration = 4000) {
    const container = getToastContainer();

    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span style="font-size: 1.1rem; font-weight: 700;">${icons[type] || 'ℹ'}</span>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/* ── DOM Helpers ── */
function $(selector) {
    return document.querySelector(selector);
}

function $$(selector) {
    return document.querySelectorAll(selector);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showElement(el) {
    if (typeof el === 'string') el = $(el);
    if (el) el.classList.remove('hidden');
}

function hideElement(el) {
    if (typeof el === 'string') el = $(el);
    if (el) el.classList.add('hidden');
}

function toggleElement(el) {
    if (typeof el === 'string') el = $(el);
    if (el) el.classList.toggle('hidden');
}

/* ── Skeleton Loader ── */
function showSkeleton(container, count = 3) {
    if (typeof container === 'string') container = $(container);
    if (!container) return;
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `
            <div class="card" style="margin-bottom: 0.75rem;">
                <div class="skeleton skeleton-title"></div>
                <div class="skeleton skeleton-text" style="width: 80%;"></div>
                <div class="skeleton skeleton-text" style="width: 60%;"></div>
            </div>
        `;
    }
    container.innerHTML = html;
}

function clearSkeleton(container) {
    if (typeof container === 'string') container = $(container);
    if (container) container.innerHTML = '';
}

/* ── Password Strength Meter ── */
function checkPasswordStrength(password) {
    let score = 0;
    const feedback = [];

    if (password.length >= 8) score++;
    else feedback.push('At least 8 characters');

    if (password.length >= 12) score++;

    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
    else feedback.push('Mix upper and lowercase');

    if (/\d/.test(password)) score += 0.5;
    else feedback.push('Add numbers');

    if (/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password)) score += 0.5;
    else feedback.push('Add special characters');

    score = Math.min(Math.floor(score), 4);
    const labels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];

    return { score, label: labels[score], feedback };
}

function renderPasswordStrength(barEl, labelEl, password) {
    const { score, label, feedback } = checkPasswordStrength(password);
    if (barEl) {
        barEl.className = `password-strength-bar strength-${score}`;
    }
    if (labelEl) {
        labelEl.textContent = password.length > 0 ? label : '';
        const colors = ['var(--danger)', 'var(--danger)', 'var(--warning)', 'var(--accent-teal)', 'var(--success)'];
        labelEl.style.color = password.length > 0 ? colors[score] : '';
    }
}

/* ── Confidence Bar Renderer ── */
function renderConfidence(containerEl, value) {
    if (typeof containerEl === 'string') containerEl = $(containerEl);
    if (!containerEl) return;

    const percent = Math.round(value * 100);
    let colorClass = 'confidence-low';
    if (percent >= 70) colorClass = 'confidence-high';
    else if (percent >= 40) colorClass = 'confidence-medium';

    containerEl.innerHTML = `
        <div class="confidence-bar">
            <div class="confidence-fill ${colorClass}" style="width: ${percent}%;"></div>
        </div>
        <span class="confidence-label">${percent}%</span>
    `;
}

/* ── Auth State Pipeline Renderer ── */
function renderAuthPipeline(containerEl, stages) {
    if (typeof containerEl === 'string') containerEl = $(containerEl);
    if (!containerEl) return;

    const html = stages.map((stage, i) => {
        let stateClass = '';
        if (stage.state === 'active') stateClass = 'active';
        else if (stage.state === 'complete') stateClass = 'complete';
        else if (stage.state === 'failed') stateClass = 'failed';

        const arrow = i < stages.length - 1 ? '<span class="pipeline-arrow">→</span>' : '';
        return `<span class="pipeline-stage ${stateClass}">${stage.icon || ''} ${stage.label}</span>${arrow}`;
    }).join('');

    containerEl.innerHTML = html;
}

/* ── Security Score Ring ── */
function renderSecurityRing(containerEl, score) {
    if (typeof containerEl === 'string') containerEl = $(containerEl);
    if (!containerEl) return;

    const circumference = 2 * Math.PI * 45;
    const offset = circumference - (score / 100) * circumference;

    let color = 'var(--danger)';
    if (score >= 70) color = 'var(--success)';
    else if (score >= 40) color = 'var(--warning)';

    containerEl.innerHTML = `
        <svg width="120" height="120" viewBox="0 0 120 120">
            <circle class="security-ring-bg" cx="60" cy="60" r="45" fill="none" stroke-width="8"/>
            <circle class="security-ring-fill" cx="60" cy="60" r="45" fill="none"
                stroke="${color}" stroke-width="8" stroke-linecap="round"
                stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"/>
        </svg>
        <div class="security-ring-value">
            <span style="color: ${color};">${Math.round(score)}</span>
            <span class="security-ring-label">Score</span>
        </div>
    `;
}

/* ── Format Helpers ── */
function formatDate(isoString) {
    if (!isoString) return 'Never';
    const d = new Date(isoString);
    return d.toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function formatTimeAgo(isoString) {
    if (!isoString) return 'Never';
    const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

/* ── Auth Guard ── */
function requireAuth() {
    const token = TokenStore.get();
    if (!token) {
        window.location.href = '/login.html';
        return false;
    }
    return true;
}

function requireAdmin() {
    const userData = TokenStore.getUserData();
    if (!userData || userData.role !== 'admin') {
        showToast('Admin access required', 'error');
        window.location.href = '/dashboard.html';
        return false;
    }
    return true;
}

/* ── Debounce ── */
function debounce(fn, delay = 300) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}
