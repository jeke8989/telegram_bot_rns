/**
 * DOM helper utilities.
 */

function $(selector, root) {
    return (root || document).querySelector(selector);
}

function $$(selector, root) {
    return Array.from((root || document).querySelectorAll(selector));
}

function createElement(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
        for (const [key, val] of Object.entries(attrs)) {
            if (key === 'className') el.className = val;
            else if (key === 'textContent') el.textContent = val;
            else if (key === 'innerHTML') el.innerHTML = val;
            else if (key.startsWith('on') && typeof val === 'function') el.addEventListener(key.slice(2).toLowerCase(), val);
            else if (key === 'style' && typeof val === 'object') Object.assign(el.style, val);
            else el.setAttribute(key, val);
        }
    }
    if (children) {
        for (const child of Array.isArray(children) ? children : [children]) {
            if (typeof child === 'string') el.appendChild(document.createTextNode(child));
            else if (child) el.appendChild(child);
        }
    }
    return el;
}
