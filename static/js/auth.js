/**
 * Authentication utilities
 * Handles token management, user state, and auth navigation
 */

const STORAGE_KEYS = {
    ACCESS_TOKEN: 'access_token',
    REFRESH_TOKEN: 'refresh_token',
    USERNAME: 'username',
    USER_ROLE: 'user_role'
};

export function getAccessToken() {
    return localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
}

export function getRefreshToken() {
    return localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
}

export function setTokens(accessToken, refreshToken, username, role) {
    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, accessToken);
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, refreshToken);
    localStorage.setItem(STORAGE_KEYS.USERNAME, username);
    localStorage.setItem(STORAGE_KEYS.USER_ROLE, role);
}

export function clearTokens() {
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN);
    localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN);
    localStorage.removeItem(STORAGE_KEYS.USERNAME);
    localStorage.removeItem(STORAGE_KEYS.USER_ROLE);
}

export function getCurrentUser() {
    const username = localStorage.getItem(STORAGE_KEYS.USERNAME);
    const role = localStorage.getItem(STORAGE_KEYS.USER_ROLE);
    return username ? { username, role } : null;
}

export function isAuthenticated() {
    return !!getAccessToken();
}

export function isAdmin() {
    return localStorage.getItem(STORAGE_KEYS.USER_ROLE) === 'admin';
}

export function logout() {
    clearTokens();
    window.location.href = '/login.html';
}

export function requireAuth() {
    if (!isAuthenticated()) {
        window.location.href = '/login.html';
    }
}

export function requireAdmin() {
    if (!isAdmin()) {
        window.location.href = '/';
    }
}
