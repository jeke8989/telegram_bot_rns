/**
 * Reusable dropdown menu component.
 * Positioned absolutely via getBoundingClientRect.
 *
 * Usage:
 *   Dropdown.show(triggerEl, {
 *       items: [
 *           { label: 'Edit', icon: '✏️', onClick: () => {} },
 *           { label: 'Delete', icon: '🗑️', danger: true, onClick: () => {} },
 *           { divider: true },
 *       ],
 *   });
 *   Dropdown.hide();
 */
const Dropdown = (function () {
    let menuEl = null;
    let cleanup = null;

    function hide() {
        if (menuEl && menuEl.parentNode) menuEl.parentNode.removeChild(menuEl);
        if (cleanup) { document.removeEventListener('click', cleanup); cleanup = null; }
        menuEl = null;
    }

    function show(trigger, config) {
        hide();
        const items = config.items || [];
        menuEl = document.createElement('div');
        menuEl.style.cssText = 'position:absolute;z-index:var(--z-dropdown,200);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm,8px);padding:4px;box-shadow:0 8px 32px rgba(0,0,0,.3);min-width:160px;';

        for (const item of items) {
            if (item.divider) {
                const d = document.createElement('div');
                d.style.cssText = 'height:1px;background:var(--border);margin:4px 0;';
                menuEl.appendChild(d);
                continue;
            }
            const btn = document.createElement('button');
            btn.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;padding:8px 12px;border:none;background:none;color:' + (item.danger ? 'var(--red)' : 'var(--text)') + ';font-size:.85rem;cursor:pointer;border-radius:6px;font-family:inherit;transition:.15s;text-align:left;';
            btn.innerHTML = (item.icon ? '<span>' + item.icon + '</span>' : '') + escapeHtml(item.label);
            btn.addEventListener('mouseenter', function () { this.style.background = 'var(--surface-2)'; });
            btn.addEventListener('mouseleave', function () { this.style.background = 'none'; });
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                hide();
                if (item.onClick) item.onClick();
            });
            menuEl.appendChild(btn);
        }

        document.body.appendChild(menuEl);

        const rect = trigger.getBoundingClientRect();
        const menuRect = menuEl.getBoundingClientRect();
        let top = rect.bottom + window.scrollY + 4;
        let left = rect.left + window.scrollX;
        if (left + menuRect.width > window.innerWidth - 8) left = window.innerWidth - menuRect.width - 8;
        if (top + menuRect.height > window.innerHeight + window.scrollY - 8) top = rect.top + window.scrollY - menuRect.height - 4;
        menuEl.style.top = top + 'px';
        menuEl.style.left = left + 'px';

        cleanup = function (e) {
            if (menuEl && !menuEl.contains(e.target) && !trigger.contains(e.target)) hide();
        };
        setTimeout(function () { document.addEventListener('click', cleanup); }, 0);
    }

    return { show: show, hide: hide };
})();
