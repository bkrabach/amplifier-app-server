/**
 * Header Component
 * Reusable header with branding, user info, and actions
 */

import { logout } from '../js/auth.js';

/**
 * Render header HTML
 * @param {Object} config - Header configuration
 * @param {string} config.title - Main title (default: 'CORTEX')
 * @param {string} config.subtitle - Subtitle text
 * @param {Object} config.user - User object { username, role }
 * @param {boolean} config.showAdminLink - Show admin link for admin users
 * @returns {string} HTML string
 */
export function renderHeader({ 
    title = 'CORTEX', 
    subtitle = 'Intelligent Orchestration',
    user = null,
    showAdminLink = false
}) {
    return `
        <header class="header">
            <div class="header-brand">
                <div>
                    <div class="header-logo">${title}</div>
                    ${subtitle ? `<div class="header-subtitle">${subtitle}</div>` : ''}
                </div>
            </div>
            <div class="header-actions">
                ${showAdminLink ? '<a href="/admin.html" class="btn btn-ghost btn-sm">Admin</a>' : ''}
                ${user ? `<span class="user-info">${user.username}</span>` : ''}
                <button class="btn btn-ghost btn-sm" id="header-logout-btn">Logout</button>
            </div>
        </header>
    `;
}

/**
 * Initialize header by mounting it into a container and setting up event handlers
 * @param {string} containerId - Container element ID or selector
 * @param {Object} config - Header configuration (same as renderHeader)
 */
export function initHeader(containerId, config) {
    const container = typeof containerId === 'string' 
        ? document.querySelector(containerId) 
        : containerId;
    
    if (!container) {
        console.error('Header container not found:', containerId);
        return;
    }
    
    // Render header HTML
    container.innerHTML = renderHeader(config);
    
    // Setup logout button handler
    const logoutBtn = container.querySelector('#header-logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

/**
 * Update header user info dynamically
 * @param {Object} user - User object { username, role }
 */
export function updateHeaderUser(user) {
    const userInfoEl = document.querySelector('.header .user-info');
    if (userInfoEl && user) {
        userInfoEl.textContent = user.username;
    }
}

/**
 * Show/hide admin link dynamically
 * @param {boolean} show - Whether to show the admin link
 */
export function toggleAdminLink(show) {
    const adminLink = document.querySelector('.header a[href="/admin.html"]');
    if (adminLink) {
        adminLink.style.display = show ? 'inline-block' : 'none';
    }
}
