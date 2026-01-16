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

/**
 * Render a complete form from field definitions
 * @param {Array} fields - Field definitions
 * @returns {string} HTML string for the form
 */
export function renderForm(fields) {
    return fields.map(field => renderFormField(field)).join('');
}

/**
 * Render a single form field
 * @param {Object} field - Field definition
 * @param {string} field.name - Field name
 * @param {string} field.label - Field label
 * @param {string} field.type - Field type (text, email, password, select, textarea)
 * @param {boolean} field.required - Whether field is required
 * @param {Array} field.options - Options for select fields [{ value, label }] or string array
 * @param {string} field.placeholder - Placeholder text
 * @param {string} field.hint - Hint text below field
 * @param {number} field.minLength - Minimum length for validation
 * @param {number} field.maxLength - Maximum length for validation
 * @param {string} field.value - Default value
 * @returns {string} HTML string for the form field
 */
export function renderFormField(field) {
    const {
        name,
        label,
        type = 'text',
        required = false,
        options = [],
        placeholder = '',
        hint = '',
        minLength,
        maxLength,
        value = ''
    } = field;

    const id = `field-${name}`;
    const requiredAttr = required ? 'required' : '';
    const minLengthAttr = minLength ? `minlength="${minLength}"` : '';
    const maxLengthAttr = maxLength ? `maxlength="${maxLength}"` : '';
    const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
    const valueAttr = value ? `value="${value}"` : '';

    let inputHtml = '';

    if (type === 'select') {
        const selectOptions = options.map(opt => {
            if (typeof opt === 'string') {
                return `<option value="${opt}">${opt}</option>`;
            } else {
                const selected = opt.value === value ? 'selected' : '';
                return `<option value="${opt.value}" ${selected}>${opt.label}</option>`;
            }
        }).join('');

        inputHtml = `
            <select 
                id="${id}" 
                name="${name}" 
                class="form-select" 
                ${requiredAttr}
            >
                ${!required ? '<option value="">Select...</option>' : ''}
                ${selectOptions}
            </select>
        `;
    } else if (type === 'textarea') {
        inputHtml = `
            <textarea 
                id="${id}" 
                name="${name}" 
                class="form-input form-textarea" 
                ${requiredAttr}
                ${minLengthAttr}
                ${maxLengthAttr}
                ${placeholderAttr}
                rows="4"
            >${value}</textarea>
        `;
    } else {
        inputHtml = `
            <input 
                type="${type}" 
                id="${id}" 
                name="${name}" 
                class="form-input" 
                ${requiredAttr}
                ${minLengthAttr}
                ${maxLengthAttr}
                ${placeholderAttr}
                ${valueAttr}
            >
        `;
    }

    return `
        <div class="form-group">
            <label class="form-label" for="${id}">
                ${label}
                ${!required ? '<span class="form-label-optional">(optional)</span>' : ''}
            </label>
            ${inputHtml}
            ${hint ? `<div class="form-hint">${hint}</div>` : ''}
        </div>
    `;
}
