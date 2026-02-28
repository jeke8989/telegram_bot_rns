/**
 * Reusable pagination component.
 * Requires: css/components/pagination.css
 *
 * Usage:
 *   const pager = Pagination(container, {
 *       total: 100,
 *       perPage: 15,
 *       onChange: (page) => { ... },
 *   });
 *   pager.setPage(2);
 *   pager.update(newTotal);
 */
function Pagination(container, config) {
    const perPage = config.perPage || 15;
    const onChange = config.onChange;
    let total = config.total || 0;
    let current = 1;

    function totalPages() { return Math.max(1, Math.ceil(total / perPage)); }

    function render() {
        const pages = totalPages();
        if (pages <= 1) { container.style.display = 'none'; return; }
        container.style.display = 'flex';
        container.className = 'pagination';
        container.innerHTML = '';

        var prev = document.createElement('button');
        prev.className = 'page-btn';
        prev.textContent = '\u2190';
        prev.disabled = current <= 1;
        prev.addEventListener('click', function () { setPage(current - 1); });
        container.appendChild(prev);

        var start = Math.max(1, current - 2);
        var end = Math.min(pages, start + 4);
        if (end - start < 4) start = Math.max(1, end - 4);

        for (var i = start; i <= end; i++) {
            var btn = document.createElement('button');
            btn.className = 'page-btn' + (i === current ? ' active' : '');
            btn.textContent = i;
            btn.addEventListener('click', (function (p) { return function () { setPage(p); }; })(i));
            container.appendChild(btn);
        }

        var next = document.createElement('button');
        next.className = 'page-btn';
        next.textContent = '\u2192';
        next.disabled = current >= pages;
        next.addEventListener('click', function () { setPage(current + 1); });
        container.appendChild(next);
    }

    function setPage(p) {
        p = Math.max(1, Math.min(p, totalPages()));
        if (p === current) return;
        current = p;
        render();
        if (onChange) onChange(current);
    }

    function update(newTotal) {
        total = newTotal;
        if (current > totalPages()) current = totalPages();
        render();
    }

    render();
    return { setPage: setPage, update: update, render: render, getCurrent: function () { return current; } };
}
