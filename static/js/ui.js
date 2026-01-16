/**
 * UI utilities
 * Toast notifications, loading states, empty states
 */

// Toast system
let toastContainer = null;

function ensureToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        toastContainer.style.cssText = `
            position: fixed;
            top: var(--spacing-4);
            right: var(--spacing-4);
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: var(--spacing-2);
        `;
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

export function showToast(message, type = 'info', duration = 3000) {
    const container = ensureToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `alert alert-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        min-width: 250px;
        max-width: 400px;
        animation: slideInRight 0.3s ease-out;
    `;
    
    container.appendChild(toast);
    
    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => {
            toast.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    
    return toast;
}

// Loading overlay
let loadingOverlay = null;

export function showLoading(message = 'Loading...') {
    if (loadingOverlay) return;
    
    loadingOverlay = document.createElement('div');
    loadingOverlay.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    
    loadingOverlay.innerHTML = `
        <div style="text-align: center; color: var(--color-text-primary);">
            <div style="font-size: 2rem; margin-bottom: var(--spacing-4);">⏳</div>
            <div>${message}</div>
        </div>
    `;
    
    document.body.appendChild(loadingOverlay);
}

export function hideLoading() {
    if (loadingOverlay) {
        loadingOverlay.remove();
        loadingOverlay = null;
    }
}

export function setButtonLoading(button, loading = true, loadingText = 'Loading...') {
    if (loading) {
        button.dataset.originalText = button.textContent;
        button.textContent = loadingText;
        button.disabled = true;
    } else {
        button.textContent = button.dataset.originalText || button.textContent;
        button.disabled = false;
        delete button.dataset.originalText;
    }
}

export function renderEmptyState({ icon, title, message, action }) {
    return `
        <div class="empty-state" style="
            text-align: center;
            padding: var(--spacing-12) var(--spacing-4);
            color: var(--color-text-secondary);
        ">
            ${icon ? `<div style="font-size: 3rem; margin-bottom: var(--spacing-4);">${icon}</div>` : ''}
            <h3 style="color: var(--color-text-primary); margin-bottom: var(--spacing-2);">${title}</h3>
            <p style="margin-bottom: var(--spacing-6);">${message}</p>
            ${action ? `<div>${action}</div>` : ''}
        </div>
    `;
}

/**
 * Render skeleton loading state
 * @param {string} type - Skeleton type (table, card, list, text)
 * @param {number} count - Number of skeleton items (default: 3)
 * @returns {string} HTML string
 */
export function renderSkeleton(type = 'text', count = 3) {
    switch (type) {
        case 'table':
            return renderTableSkeleton(count);
        case 'card':
            return renderCardSkeleton(count);
        case 'list':
            return renderListSkeleton(count);
        case 'text':
        default:
            return renderTextSkeleton(count);
    }
}

function renderTableSkeleton(rows = 3) {
    const skeletonRows = Array.from({ length: rows }, () => `
        <tr>
            <td><div class="skeleton skeleton-text"></div></td>
            <td><div class="skeleton skeleton-text"></div></td>
            <td><div class="skeleton skeleton-text"></div></td>
            <td><div class="skeleton skeleton-text"></div></td>
        </tr>
    `).join('');

    return `
        <div class="table-wrapper">
            <table class="table">
                <thead>
                    <tr>
                        <th><div class="skeleton skeleton-text" style="width: 60%;"></div></th>
                        <th><div class="skeleton skeleton-text" style="width: 60%;"></div></th>
                        <th><div class="skeleton skeleton-text" style="width: 60%;"></div></th>
                        <th><div class="skeleton skeleton-text" style="width: 60%;"></div></th>
                    </tr>
                </thead>
                <tbody>
                    ${skeletonRows}
                </tbody>
            </table>
        </div>
    `;
}

function renderCardSkeleton(count = 3) {
    const skeletonCards = Array.from({ length: count }, () => `
        <div class="card" style="margin-bottom: var(--spacing-4);">
            <div class="card-body">
                <div class="skeleton skeleton-title" style="width: 60%; margin-bottom: var(--spacing-3);"></div>
                <div class="skeleton skeleton-text" style="width: 100%; margin-bottom: var(--spacing-2);"></div>
                <div class="skeleton skeleton-text" style="width: 85%; margin-bottom: var(--spacing-2);"></div>
                <div class="skeleton skeleton-text" style="width: 70%;"></div>
            </div>
        </div>
    `).join('');

    return skeletonCards;
}

function renderListSkeleton(count = 3) {
    const skeletonItems = Array.from({ length: count }, () => `
        <div style="display: flex; align-items: center; gap: var(--spacing-3); padding: var(--spacing-3); border-bottom: 1px solid var(--color-border-default);">
            <div class="skeleton skeleton-avatar"></div>
            <div style="flex: 1;">
                <div class="skeleton skeleton-text" style="width: 40%; margin-bottom: var(--spacing-2);"></div>
                <div class="skeleton skeleton-text" style="width: 70%;"></div>
            </div>
        </div>
    `).join('');

    return `
        <div style="background: var(--color-surface-primary); border-radius: var(--radius-lg); overflow: hidden; border: 1px solid var(--color-border-default);">
            ${skeletonItems}
        </div>
    `;
}

function renderTextSkeleton(lines = 3) {
    const skeletonLines = Array.from({ length: lines }, (_, i) => {
        const widths = ['100%', '95%', '85%', '90%', '80%'];
        const width = widths[i % widths.length];
        return `<div class="skeleton skeleton-text" style="width: ${width}; margin-bottom: var(--spacing-3);"></div>`;
    }).join('');

    return `
        <div style="padding: var(--spacing-4);">
            ${skeletonLines}
        </div>
    `;
}
