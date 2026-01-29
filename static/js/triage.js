/**
 * Triage Module
 * Handles notification triage UI and interactions
 */

import { api } from './api.js';

// State
let triageItems = { surfaced: [], expiring_soon: [], pending: [], total_count: 0 };
let isLoading = false;

/**
 * Initialize triage system
 */
export async function initTriage() {
    // Setup tab navigation
    setupTabNavigation();
    
    // Load initial data
    await refreshTriageItems();
    
    // Setup auto-refresh (every 60 seconds)
    setInterval(refreshTriageItems, 60000);
}

/**
 * Setup tab navigation between Chat and Triage
 */
function setupTabNavigation() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            switchTab(tabId);
        });
    });
}

/**
 * Switch between tabs
 * @param {string} tabId - Tab identifier ('chat' or 'triage')
 */
export function switchTab(tabId) {
    // Update button states
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    
    // Update panel visibility
    document.querySelectorAll('.tab-panel').forEach(panel => {
        const isActive = panel.id === `${tabId}-panel`;
        panel.style.display = isActive ? 'flex' : 'none';
        panel.classList.toggle('active', isActive);
    });
    
    // Refresh triage when switching to it
    if (tabId === 'triage') {
        refreshTriageItems();
    }
}

/**
 * Fetch and render triage items
 */
export async function refreshTriageItems() {
    if (isLoading) return;
    isLoading = true;
    
    const container = document.getElementById('triage-container');
    if (!container) {
        isLoading = false;
        return;
    }
    
    try {
        const result = await api.get('/triage/items');
        if (result.success) {
            triageItems = result.data;
            renderTriageList(container);
            updateBadgeCount();
        } else {
            container.innerHTML = renderError(result.error);
        }
    } catch (error) {
        container.innerHTML = renderError(error.message);
    } finally {
        isLoading = false;
    }
}

/**
 * Render the full triage list
 * @param {HTMLElement} container - Container element
 */
function renderTriageList(container) {
    const { surfaced = [], expiring_soon = [], pending = [], total_count = 0 } = triageItems;
    
    if (total_count === 0) {
        container.innerHTML = renderEmptyState();
        return;
    }
    
    let html = '<div class="triage-list">';
    
    // Surfaced (punched through, need confirmation)
    if (surfaced.length > 0) {
        html += renderSection('⚡ Punched Through', surfaced, 'surfaced');
    }
    
    // Expiring soon
    if (expiring_soon.length > 0) {
        html += renderSection('⏳ Expiring Soon', expiring_soon, 'expiring');
    }
    
    // Pending
    if (pending.length > 0) {
        html += renderSection('📬 Needs Triage', pending, 'pending');
    }
    
    html += '</div>';
    container.innerHTML = html;
    
    // Attach event listeners
    attachCardEventListeners(container);
}

/**
 * Render a section with header and cards
 * @param {string} title - Section title
 * @param {Array} items - Triage items
 * @param {string} sectionClass - CSS class modifier
 * @returns {string} HTML string
 */
function renderSection(title, items, sectionClass) {
    return `
        <div class="triage-section triage-section--${sectionClass}">
            <h3 class="triage-section__header">${title} (${items.length})</h3>
            <div class="triage-section__cards">
                ${items.map(item => renderTriageCard(item)).join('')}
            </div>
        </div>
    `;
}

/**
 * Render a single triage card
 * @param {Object} item - Triage item
 * @returns {string} HTML string
 */
function renderTriageCard(item) {
    const timeAgo = formatTimeAgo(item.created_at);
    const appIcon = getAppIcon(item.app_name);
    const expiresInfo = item.expires_at ? formatExpiresIn(item.expires_at) : '';
    
    return `
        <div class="triage-card" data-id="${item.id}" data-status="${item.triage_status}">
            <div class="triage-card__header">
                <span class="triage-card__app">
                    <span class="triage-card__app-icon">${appIcon}</span>
                    ${escapeHtml(item.app_name || 'Unknown App')}
                    ${item.sender ? ` · ${escapeHtml(item.sender)}` : ''}
                </span>
                <span class="triage-card__time">${timeAgo}</span>
            </div>
            
            <div class="triage-card__content">
                ${item.title ? `<div class="triage-card__title">${escapeHtml(item.title)}</div>` : ''}
                ${item.body ? `<div class="triage-card__body">${escapeHtml(item.body)}</div>` : ''}
            </div>
            
            ${item.rationale ? `
                <div class="triage-card__rationale">
                    <span class="triage-card__score">${(item.relevance_score * 100).toFixed(0)}%</span>
                    ${escapeHtml(item.rationale)}
                </div>
            ` : ''}
            
            ${expiresInfo ? `<div class="triage-card__expires">${expiresInfo}</div>` : ''}
            
            <div class="triage-card__actions">
                <button class="btn btn-sm btn-primary triage-action" data-action="dealt_with">
                    ✓ Deal with
                </button>
                <button class="btn btn-sm btn-secondary triage-action" data-action="dismissed">
                    ✕ Ignore
                </button>
                <button class="btn btn-sm btn-ghost triage-action" data-action="already_handled">
                    Already handled
                </button>
            </div>
            
            <div class="triage-card__feedback">
                <span class="feedback-label">How was this?</span>
                <div class="feedback-reactions">
                    <button class="feedback-btn" data-reaction="👍" title="Good call">👍</button>
                    <button class="feedback-btn" data-reaction="👎" title="Bad call">👎</button>
                    <button class="feedback-btn" data-reaction="⏰" title="Wrong timing">⏰</button>
                    <button class="feedback-btn" data-reaction="❓" title="Need more context">❓</button>
                </div>
            </div>
            
            ${item.suggested_response ? renderSuggestedActions(item.suggested_response) : ''}
        </div>
    `;
}

/**
 * Render suggested actions (collapsed by default)
 * @param {Object} suggestions - Suggested responses
 * @returns {string} HTML string
 */
function renderSuggestedActions(suggestions) {
    if (!suggestions) return '';
    
    const { quick_replies, detailed_response, actions } = suggestions;
    if (!quick_replies?.length && !detailed_response && !actions?.length) return '';
    
    return `
        <details class="triage-card__suggestions">
            <summary>💡 Suggested responses</summary>
            <div class="suggestions-content">
                ${quick_replies?.length ? `
                    <div class="suggestions-section">
                        <label>Quick replies:</label>
                        <div class="quick-replies">
                            ${quick_replies.map(r => `<button class="btn btn-sm btn-secondary quick-reply">${escapeHtml(r)}</button>`).join('')}
                        </div>
                    </div>
                ` : ''}
                
                ${detailed_response ? `
                    <div class="suggestions-section">
                        <label>Drafted response:</label>
                        <div class="drafted-response">${escapeHtml(detailed_response)}</div>
                    </div>
                ` : ''}
                
                ${actions?.length ? `
                    <div class="suggestions-section">
                        <label>Actions:</label>
                        <div class="suggested-actions">
                            ${actions.map(a => `<button class="btn btn-sm btn-ghost suggested-action">${escapeHtml(a.label || a.type)}</button>`).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        </details>
    `;
}

/**
 * Render empty state
 * @returns {string} HTML string
 */
function renderEmptyState() {
    return `
        <div class="triage-empty">
            <div class="triage-empty__icon">✨</div>
            <h3 class="triage-empty__title">All caught up!</h3>
            <p class="triage-empty__text">No notifications need your attention right now.</p>
        </div>
    `;
}

/**
 * Render error state
 * @param {string} message - Error message
 * @returns {string} HTML string
 */
function renderError(message) {
    return `
        <div class="triage-error">
            <div class="alert alert-error">
                <strong>Error loading triage items:</strong> ${escapeHtml(message)}
            </div>
            <button class="btn btn-secondary" onclick="window.triageModule.refreshTriageItems()">
                Try Again
            </button>
        </div>
    `;
}

/**
 * Attach event listeners to card buttons
 * @param {HTMLElement} container - Container element
 */
function attachCardEventListeners(container) {
    // Action buttons (Deal with, Ignore, Already handled)
    container.querySelectorAll('.triage-action').forEach(btn => {
        btn.addEventListener('click', handleTriageAction);
    });
    
    // Feedback reactions
    container.querySelectorAll('.feedback-btn').forEach(btn => {
        btn.addEventListener('click', handleFeedbackReaction);
    });
}

/**
 * Handle triage action (deal with, ignore, already handled)
 * @param {Event} event - Click event
 */
async function handleTriageAction(event) {
    const btn = event.target.closest('.triage-action');
    if (!btn) return;
    
    const card = btn.closest('.triage-card');
    const itemId = card.dataset.id;
    const action = btn.dataset.action;
    
    // Get any selected feedback
    const selectedReaction = card.querySelector('.feedback-btn.selected');
    const quickReaction = selectedReaction?.dataset.reaction || null;
    
    // Disable buttons while processing
    card.classList.add('is-loading');
    
    try {
        const result = await api.post(`/triage/items/${itemId}/action`, {
            action: action,
            quick_reaction: quickReaction
        });
        
        if (result.success) {
            // Animate card removal
            card.classList.add('triage-card--removing');
            setTimeout(() => {
                refreshTriageItems();
            }, 300);
        } else {
            showCardError(card, result.error);
            card.classList.remove('is-loading');
        }
    } catch (error) {
        showCardError(card, error.message);
        card.classList.remove('is-loading');
    }
}

/**
 * Show error on a card
 * @param {HTMLElement} card - Card element
 * @param {string} message - Error message
 */
function showCardError(card, message) {
    // Remove any existing error
    const existingError = card.querySelector('.triage-card__error');
    if (existingError) {
        existingError.remove();
    }
    
    // Add error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'triage-card__error alert alert-error';
    errorDiv.textContent = `Error: ${message}`;
    card.appendChild(errorDiv);
    
    // Remove after 5 seconds
    setTimeout(() => {
        errorDiv.remove();
    }, 5000);
}

/**
 * Handle feedback reaction selection
 * @param {Event} event - Click event
 */
function handleFeedbackReaction(event) {
    const btn = event.target.closest('.feedback-btn');
    if (!btn) return;
    
    const card = btn.closest('.triage-card');
    
    // Toggle selection
    card.querySelectorAll('.feedback-btn').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
}

/**
 * Update the badge count on the Triage tab
 */
function updateBadgeCount() {
    const badge = document.getElementById('triage-badge');
    if (!badge) return;
    
    const count = triageItems.total_count || 0;
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-flex' : 'none';
}

// ==================== Helper Functions ====================

/**
 * Format a date as relative time ago
 * @param {string} dateStr - ISO date string
 * @returns {string} Formatted time ago
 */
function formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
}

/**
 * Format expiration time
 * @param {string} dateStr - ISO date string
 * @returns {string} Formatted expiration
 */
function formatExpiresIn(dateStr) {
    if (!dateStr) return '';
    
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = date - now;
    
    if (diffMs < 0) return 'Expired';
    
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    
    if (diffMins < 60) return `Expires in ${diffMins}m`;
    if (diffHours < 24) return `Expires in ${diffHours}h`;
    return `Expires in ${Math.floor(diffHours / 24)}d`;
}

/**
 * Get icon for app name
 * @param {string} appName - Application name
 * @returns {string} Emoji icon
 */
function getAppIcon(appName) {
    const name = (appName || '').toLowerCase();
    if (name.includes('teams')) return '👥';
    if (name.includes('outlook') || name.includes('mail')) return '📧';
    if (name.includes('whatsapp')) return '💬';
    if (name.includes('calendar')) return '📅';
    if (name.includes('slack')) return '💼';
    if (name.includes('github')) return '🐙';
    if (name.includes('jira')) return '📋';
    return '🔔';
}

/**
 * Escape HTML to prevent XSS
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ==================== Initialization ====================

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTriage);
} else {
    initTriage();
}

// Export for global access
window.triageModule = { refreshTriageItems, switchTab };
