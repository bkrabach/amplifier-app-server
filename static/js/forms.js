/**
 * Form utilities
 * Validation, error display, data extraction
 */

export function validateForm(formElement) {
    const errors = {};
    const inputs = formElement.querySelectorAll('input[required], select[required], textarea[required]');
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            errors[input.name] = `${input.labels[0]?.textContent || input.name} is required`;
        }
        
        // Email validation
        if (input.type === 'email' && input.value && !input.value.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) {
            errors[input.name] = 'Invalid email address';
        }
        
        // Min length
        if (input.minLength && input.value.length < input.minLength) {
            errors[input.name] = `Minimum ${input.minLength} characters required`;
        }
    });
    
    return {
        valid: Object.keys(errors).length === 0,
        errors
    };
}

export function showFieldError(fieldName, message) {
    const field = document.querySelector(`[name="${fieldName}"]`);
    if (!field) return;
    
    // Add error class
    field.classList.add('error');
    
    // Find or create error message
    let errorEl = field.parentElement.querySelector('.form-error');
    if (!errorEl) {
        errorEl = document.createElement('div');
        errorEl.className = 'form-error';
        errorEl.style.cssText = `
            color: var(--color-danger);
            font-size: var(--font-size-sm);
            margin-top: var(--spacing-2);
        `;
        field.parentElement.appendChild(errorEl);
    }
    errorEl.textContent = message;
}

export function clearFieldError(fieldName) {
    const field = document.querySelector(`[name="${fieldName}"]`);
    if (!field) return;
    
    field.classList.remove('error');
    const errorEl = field.parentElement.querySelector('.form-error');
    if (errorEl) {
        errorEl.remove();
    }
}

export function clearFormErrors(formElement) {
    formElement.querySelectorAll('.error').forEach(el => el.classList.remove('error'));
    formElement.querySelectorAll('.form-error').forEach(el => el.remove());
}

export function getFormData(formElement) {
    const formData = new FormData(formElement);
    const data = {};
    for (const [key, value] of formData.entries()) {
        data[key] = value;
    }
    return data;
}

export function setFormData(formElement, data) {
    Object.entries(data).forEach(([key, value]) => {
        const field = formElement.querySelector(`[name="${key}"]`);
        if (field) {
            field.value = value;
        }
    });
}

export function disableForm(formElement, disabled = true) {
    formElement.querySelectorAll('input, select, textarea, button').forEach(el => {
        el.disabled = disabled;
    });
}
