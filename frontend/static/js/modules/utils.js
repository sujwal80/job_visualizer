export function createElement(tagName, attributes = {}, children = []) {
    const el = document.createElement(tagName);
    const appendChildSafe = (c) => {
        if (!c) return;
        if (typeof c === 'string') {
            el.appendChild(document.createTextNode(c));
        } else {
            el.appendChild(c);
        }
    };

    for (const [key, value] of Object.entries(attributes)) {
        if (key === 'style' && typeof value === 'string') {
            el.style.cssText = value;
        } else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.substring(2).toLowerCase(), value);
        } else if (key === 'children' && Array.isArray(value)) {
            value.forEach(appendChildSafe);
        } else if (key === 'className') {
            el.className = value;
        } else if (key === 'id') {
            el.id = value;
        } else {
            el[key] = value;
        }
    }
    if (Array.isArray(children)) {
        children.forEach(appendChildSafe);
    }
    return el;
}

export function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = createElement('div', { id: 'toast-container', className: 'toast-container' });
        document.body.appendChild(container);
    }
    const toast = createElement('div', { className: `toast toast-${type}`, textContent: message });
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

export function getDomain(startup) {
    if (!startup || !startup.website) return '';
    try {
        const urlStr = startup.website.trim();
        const url = new URL(urlStr.match(/^https?:\/\//i) ? urlStr : `http://${urlStr}`);
        return url.hostname.replace(/^www\./i, '');
    } catch {
        return '';
    }
}

export function createLogoContent(startup) {
    const domain = getDomain(startup);
    const logoUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : '';
    const initials = String(startup.name || 'S').substring(0, 1).toUpperCase();
    
    const initialsEl = createElement('span', { className: 'initials', textContent: initials });
    const children = [initialsEl];
    
    if (logoUrl) {
        const img = createElement('img', { src: logoUrl, alt: String(startup.name || 'Logo') });
        img.onerror = () => { img.style.display = 'none'; };
        children.push(img);
    }
    
    const containerClass = 'logo-marker' + (startup.has_pin === false ? ' hub-logo-marker' : '');
    return createElement('div', { className: containerClass, children });
}
