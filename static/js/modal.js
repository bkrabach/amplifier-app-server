/**
 * Modal lifecycle management
 * Handles showing/hiding modals with overlay and keyboard handling
 */

export function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        
        // Trap focus in modal
        modal.focus();
        
        // Close on Escape key
        const escapeHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal(modalId);
                document.removeEventListener('keydown', escapeHandler);
            }
        };
        document.addEventListener('keydown', escapeHandler);
    }
}

export function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
    }
}

export function createModal({ id, title, content, footer, onClose, size = 'md' }) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = id;
    
    modal.innerHTML = `
        <div class="modal-overlay" onclick="closeModal('${id}')"></div>
        <div class="modal-container modal-${size}">
            <div class="modal-header">
                <h2 class="modal-title">${title}</h2>
                <button class="modal-close" onclick="closeModal('${id}')" aria-label="Close">×</button>
            </div>
            <div class="modal-body">
                ${content}
            </div>
            ${footer ? `<div class="modal-footer">${footer}</div>` : ''}
        </div>
    `;
    
    document.body.appendChild(modal);
    
    if (onClose) {
        modal.addEventListener('close', onClose);
    }
    
    return modal;
}

export async function confirmModal(message, title = 'Confirm') {
    return new Promise((resolve) => {
        const modalId = 'confirm-modal-' + Date.now();
        
        const modal = createModal({
            id: modalId,
            title,
            content: `<p>${message}</p>`,
            footer: `
                <button class="btn btn-secondary" onclick="window.confirmResolve(false)">Cancel</button>
                <button class="btn btn-danger" onclick="window.confirmResolve(true)">Confirm</button>
            `
        });
        
        window.confirmResolve = (result) => {
            closeModal(modalId);
            modal.remove();
            delete window.confirmResolve;
            resolve(result);
        };
        
        showModal(modalId);
    });
}
