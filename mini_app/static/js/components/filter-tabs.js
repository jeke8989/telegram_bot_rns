/**
 * Reusable filter tabs component.
 * Requires: css/components/tabs.css
 *
 * Usage:
 *   FilterTabs(container, {
 *       tabs: [
 *           { key: 'all', label: 'Все', count: 10 },
 *           { key: 'active', label: 'Активные', count: 5 },
 *       ],
 *       active: 'all',
 *       onChange: (key) => { ... },
 *   });
 */
function FilterTabs(container, config) {
    const tabs = config.tabs || [];
    const onChange = config.onChange;
    let activeKey = config.active || (tabs[0] && tabs[0].key);

    function render() {
        container.innerHTML = '';
        container.classList.add('filter-tabs');

        for (const tab of tabs) {
            const btn = document.createElement('button');
            btn.className = 'filter-tab' + (tab.key === activeKey ? ' active' : '');
            btn.dataset.filter = tab.key;
            btn.innerHTML = escapeHtml(tab.label)
                + (tab.count != null ? ' <span class="filter-count">' + tab.count + '</span>' : '');
            btn.addEventListener('click', function () {
                setActive(tab.key);
                if (onChange) onChange(tab.key);
            });
            container.appendChild(btn);
        }
    }

    function setActive(key) {
        activeKey = key;
        var btns = container.querySelectorAll('.filter-tab');
        btns.forEach(function (b) {
            b.classList.toggle('active', b.dataset.filter === key);
        });
    }

    function updateCounts(countsMap) {
        for (const tab of tabs) {
            if (countsMap[tab.key] != null) tab.count = countsMap[tab.key];
        }
        var btns = container.querySelectorAll('.filter-tab');
        btns.forEach(function (b) {
            var t = tabs.find(function (t) { return t.key === b.dataset.filter; });
            if (t) {
                var span = b.querySelector('.filter-count');
                if (span) span.textContent = t.count;
            }
        });
    }

    render();
    return { setActive: setActive, updateCounts: updateCounts, render: render };
}
