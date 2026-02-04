/**
 * API client wrapper
 * Handles authentication headers, error responses, and automatic token refresh
 */

import { getAccessToken, getRefreshToken, setTokens, clearTokens, getCurrentUser } from './auth.js';

const API_BASE = window.location.origin;

// Track if we're currently refreshing to prevent multiple refresh attempts
let isRefreshing = false;
let refreshPromise = null;

/**
 * Attempt to refresh the access token using the refresh token
 */
async function refreshAccessToken() {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
        return false;
    }
    
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
        
        if (response.ok) {
            const data = await response.json();
            const user = getCurrentUser();
            setTokens(
                data.access_token,
                data.refresh_token || refreshToken, // Some APIs return new refresh token
                user?.username || '',
                user?.role || ''
            );
            return true;
        }
        
        return false;
    } catch (error) {
        console.error('Token refresh failed:', error);
        return false;
    }
}

/**
 * Ensure only one refresh attempt happens at a time
 */
async function ensureValidToken() {
    if (isRefreshing) {
        return refreshPromise;
    }
    
    isRefreshing = true;
    refreshPromise = refreshAccessToken();
    
    try {
        return await refreshPromise;
    } finally {
        isRefreshing = false;
        refreshPromise = null;
    }
}

export async function apiCall(endpoint, options = {}, retryCount = 0) {
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
        
        // Handle 401 - token expired, try to refresh
        if (response.status === 401 && retryCount === 0) {
            const refreshed = await ensureValidToken();
            
            if (refreshed) {
                // Retry the original request with new token
                return apiCall(endpoint, options, retryCount + 1);
            }
            
            // Refresh failed, redirect to login
            clearTokens();
            window.location.href = '/login.html';
            return { success: false, error: 'Session expired' };
        }
        
        // Handle other 401s after retry
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
