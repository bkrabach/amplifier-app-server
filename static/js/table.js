/**
 * Table generation utilities
 * Provides consistent table rendering with support for custom columns, actions, and empty states
 */

import { renderEmptyState } from './ui.js';

/**
 * Render a table with columns and rows
 * @param {Object} config - Table configuration
 * @param {Array} config.columns - Column definitions [{ key, label, render? }]
 * @param {Array} config.rows - Data rows (array of objects)
 * @param {string|Object} config.emptyMessage - Empty state message or config
 * @returns {string} HTML string
 */
export function renderTable({ columns, rows, emptyMessage = 'No data available' }) {
    // Handle empty state
    if (!rows || rows.length === 0) {
        if (typeof emptyMessage === 'string') {
            return renderEmptyState({
                icon: '📋',
                title: 'No Data',
                message: emptyMessage
            });
        } else {
            return renderEmptyState(emptyMessage);
        }
    }

    const thead = `
        <thead>
            <tr>
                ${columns.map(col => `<th>${col.label}</th>`).join('')}
            </tr>
        </thead>
    `;

    const tbody = `
        <tbody>
            ${rows.map(row => `
                <tr>
                    ${columns.map(col => {
                        const value = row[col.key];
                        const rendered = col.render ? col.render(value, row) : value;
                        return `<td>${rendered !== undefined && rendered !== null ? rendered : '-'}</td>`;
                    }).join('')}
                </tr>
            `).join('')}
        </tbody>
    `;

    return `
        <div class="table-wrapper">
            <table class="table">
                ${thead}
                ${tbody}
            </table>
        </div>
    `;
}

/**
 * Render a table with an actions column
 * @param {Object} config - Table configuration
 * @param {Array} config.columns - Column definitions [{ key, label, render? }]
 * @param {Array} config.rows - Data rows (array of objects)
 * @param {Function} config.actions - Function that returns HTML for action buttons (row) => string
 * @param {string|Object} config.emptyMessage - Empty state message or config
 * @returns {string} HTML string
 */
export function renderTableWithActions({ columns, rows, actions, emptyMessage = 'No data available' }) {
    // Handle empty state
    if (!rows || rows.length === 0) {
        if (typeof emptyMessage === 'string') {
            return renderEmptyState({
                icon: '📋',
                title: 'No Data',
                message: emptyMessage
            });
        } else {
            return renderEmptyState(emptyMessage);
        }
    }

    const thead = `
        <thead>
            <tr>
                ${columns.map(col => `<th>${col.label}</th>`).join('')}
                <th>Actions</th>
            </tr>
        </thead>
    `;

    const tbody = `
        <tbody>
            ${rows.map(row => `
                <tr>
                    ${columns.map(col => {
                        const value = row[col.key];
                        const rendered = col.render ? col.render(value, row) : value;
                        return `<td>${rendered !== undefined && rendered !== null ? rendered : '-'}</td>`;
                    }).join('')}
                    <td>
                        <div class="table-actions">
                            ${actions(row)}
                        </div>
                    </td>
                </tr>
            `).join('')}
        </tbody>
    `;

    return `
        <div class="table-wrapper">
            <table class="table">
                ${thead}
                ${tbody}
            </table>
        </div>
    `;
}

/**
 * Helper function to render a badge for common statuses
 * @param {string} status - Status value
 * @param {string} type - Badge type (active, inactive, etc.)
 * @returns {string} HTML string
 */
export function renderBadge(status, type) {
    return `<span class="badge badge-${type}">${status}</span>`;
}

/**
 * Helper function to format dates consistently
 * @param {string|Date} date - Date to format
 * @param {string} fallback - Fallback text if date is null/undefined
 * @returns {string} Formatted date or fallback
 */
export function formatDate(date, fallback = 'Never') {
    if (!date) return fallback;
    return new Date(date).toLocaleDateString();
}

/**
 * Helper function to format date and time
 * @param {string|Date} date - Date to format
 * @param {string} fallback - Fallback text if date is null/undefined
 * @returns {string} Formatted date and time or fallback
 */
export function formatDateTime(date, fallback = 'Never') {
    if (!date) return fallback;
    return new Date(date).toLocaleString();
}
