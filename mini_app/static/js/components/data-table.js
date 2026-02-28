/**
 * Reusable data table renderer.
 * Requires: css/components/table.css
 *
 * Usage:
 *   const table = DataTable(container, {
 *       columns: [
 *           { key: 'name', label: 'Имя', render: (val, row) => `<b>${escapeHtml(val)}</b>` },
 *           { key: 'role', label: 'Роль' },
 *       ],
 *       onRowClick: (row) => { ... },
 *       emptyText: 'Нет данных',
 *   });
 *   table.render(data);
 */
function DataTable(container, config) {
    const columns = config.columns || [];
    const onRowClick = config.onRowClick;
    const emptyText = config.emptyText || 'Нет данных';

    let wrapEl = null;

    function render(data) {
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">\uD83D\uDD0D</div><p>' + escapeHtml(emptyText) + '</p></div>';
            return;
        }

        let html = '<div class="table-wrap"><table class="data-table"><thead><tr>';
        for (const col of columns) {
            const style = col.width ? ' style="width:' + col.width + '"' : '';
            html += '<th' + style + '>' + escapeHtml(col.label || '') + '</th>';
        }
        html += '</tr></thead><tbody>';

        for (const row of data) {
            html += '<tr>';
            for (const col of columns) {
                const val = row[col.key];
                const content = col.render ? col.render(val, row) : escapeHtml(val);
                html += '<td>' + (content || '') + '</td>';
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';
        container.innerHTML = html;

        if (onRowClick) {
            const rows = container.querySelectorAll('tbody tr');
            rows.forEach(function (tr, i) {
                tr.addEventListener('click', function () { onRowClick(data[i]); });
            });
        }

        wrapEl = container.querySelector('.table-wrap');
    }

    function destroy() {
        container.innerHTML = '';
        wrapEl = null;
    }

    return { render: render, destroy: destroy };
}
