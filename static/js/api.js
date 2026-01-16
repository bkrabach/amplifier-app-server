/**
 * API client wrapper
 * Handles authentication headers, error responses, and token refresh
 */

import { getAccessToken, clearTokens } from './auth.js';

const API_BASE = window.location.origin;

export async function apiCall(endpoint, options = {}) {
    const token = getAccessToken();
    
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {})
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers
        });
        
        // Handle 401 - token expired
        if (response.status === 401) {
            clearTokens();
            window.location.href = '/login.html';
            return { success: false, error: 'Session expired' };
        }
        
        const data = await response.json();
        
        if (!response.ok) {
            return {
                success: false,
                error: data.detail || data.message || 'Request failed',
                status: response.status
            };
        }
        
        return { success: true, data };
        
    } catch (error) {
        return {
            success: false,
            error: error.message || 'Network error'
        };
    }
}

export const api = {
    get: (endpoint) => apiCall(endpoint, { method: 'GET' }),
    post: (endpoint, data) => apiCall(endpoint, { method: 'POST', body: JSON.stringify(data) }),
    put: (endpoint, data) => apiCall(endpoint, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (endpoint) => apiCall(endpoint, { method: 'DELETE' })
};
