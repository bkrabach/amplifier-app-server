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
