(async () => {
    try {
        const r = await fetch('/api/auth/me');
        if (!r.ok) { window.location.replace('/login'); return; }
        const u = await r.json();

        if (u.role === 'user') { window.location.replace('/my-cabinet'); return; }

        var name = u.first_name || u.username || 'Продажник';
        document.getElementById('heroName').textContent = name;

        loadData();
    } catch (_) { window.location.replace('/login'); }
})();

const STATUS_LABELS = {
    draft: 'Черновик', sent: 'Отправлено', accepted: 'Принято', rejected: 'Отклонено',
};

function fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function renderProposals(rows) {
    var el = document.getElementById('proposalsBody');
    if (!rows.length) {
        el.innerHTML = '<div class="empty-msg">Нет предложений. Создайте КП через бот.</div>';
        return;
    }
    var html = '<table class="seller-table"><thead><tr><th>Проект</th><th>Клиент</th><th>Статус</th><th>Дата</th></tr></thead><tbody>';
    rows.forEach(function (p) {
        var status = p.proposal_status || 'draft';
        var cls = STATUS_LABELS[status] ? status : 'draft';
        html += '<tr>'
            + '<td><a href="/proposal/' + p.token + '" target="_blank">' + (p.project_name || '—') + '</a></td>'
            + '<td>' + (p.client_company || p.client_display_name || p.client_name || '—') + '</td>'
            + '<td><span class="status-pill ' + cls + '">' + (STATUS_LABELS[status] || status) + '</span></td>'
            + '<td>' + fmtDate(p.created_at) + '</td>'
            + '</tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

function renderClients(rows) {
    var el = document.getElementById('clientsBody');
    if (!rows.length) {
        el.innerHTML = '<div class="empty-msg">Нет клиентов. Клиенты появятся после отправки КП.</div>';
        return;
    }
    var html = '<table class="seller-table"><thead><tr><th>Имя</th><th>Компания</th><th>Предложений</th></tr></thead><tbody>';
    rows.forEach(function (c) {
        var name = [c.first_name, c.last_name].filter(Boolean).join(' ') || c.username || '—';
        html += '<tr>'
            + '<td>' + name + '</td>'
            + '<td>' + (c.company || '—') + '</td>'
            + '<td>' + (c.proposals_count || 0) + '</td>'
            + '</tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

async function loadData() {
    try {
        var [propsRes, clientsRes] = await Promise.allSettled([
            fetch('/api/proposals'),
            fetch('/api/clients'),
        ]);

        var proposals = [];
        var clients = [];

        if (propsRes.status === 'fulfilled' && propsRes.value.ok) {
            proposals = await propsRes.value.json();
            if (!Array.isArray(proposals)) proposals = [];
        }
        if (clientsRes.status === 'fulfilled' && clientsRes.value.ok) {
            clients = await clientsRes.value.json();
            if (!Array.isArray(clients)) clients = [];
        }

        document.getElementById('statProposals').textContent = proposals.length;
        document.getElementById('statClients').textContent = clients.length;

        renderProposals(proposals);
        renderClients(clients);
    } catch (_) {}
}
