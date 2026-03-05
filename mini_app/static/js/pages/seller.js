(async () => {
    try {
        var r = await fetch('/api/auth/me');
        if (!r.ok) { window.location.replace('/login'); return; }
        var u = await r.json();
        if (u.role === 'user') { window.location.replace('/my-cabinet'); return; }
        document.getElementById('heroName').textContent = u.first_name || u.username || 'Продажник';
        loadData();
    } catch (_) { window.location.replace('/login'); }
})();

var STATUS_MAP = {
    draft:    { label: 'Черновик',   cls: 'draft' },
    sent:     { label: 'Отправлено', cls: 'sent' },
    accepted: { label: 'Принято',    cls: 'accepted' },
    rejected: { label: 'Отклонено',  cls: 'rejected' },
};

function fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function fmtMoney(v, currency) {
    if (!v) return '—';
    v = Math.round(Number(v));
    if (currency === '₽') return v.toLocaleString('ru-RU') + ' ₽';
    if (currency === '€') return '€' + v.toLocaleString('en-US');
    return '$' + v.toLocaleString('en-US');
}

function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function renderFunnel(proposals) {
    var section = document.getElementById('funnelSection');
    if (!proposals.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    var stages = ['draft', 'sent', 'accepted', 'rejected'];
    var counts = {}; var amounts = {};
    stages.forEach(function(s) { counts[s] = 0; amounts[s] = 0; });
    proposals.forEach(function(p) {
        var st = p.proposal_status || 'draft';
        if (!counts[st] && counts[st] !== 0) { st = 'draft'; }
        counts[st]++;
        amounts[st] += Number(p.total_cost || 0);
    });
    var maxCount = Math.max.apply(null, stages.map(function(s) { return counts[s]; })) || 1;
    var html = '';
    stages.forEach(function(s) {
        var info = STATUS_MAP[s] || { label: s, cls: 'draft' };
        var pct = Math.max(counts[s] / maxCount * 100, counts[s] > 0 ? 8 : 0);
        var currency = proposals[0] ? (proposals[0].currency || '₽') : '₽';
        html += '<div class="funnel-row">'
            + '<div class="funnel-label">' + info.label + '</div>'
            + '<div class="funnel-bar-wrap">'
            + '<div class="funnel-bar ' + info.cls + '" style="width:' + pct + '%"></div>'
            + '<span class="funnel-count">' + counts[s] + '</span>'
            + '</div>'
            + '<div class="funnel-amount">' + fmtMoney(amounts[s], currency) + '</div>'
            + '</div>';
    });
    document.getElementById('funnelBars').innerHTML = html;
}

function renderProposals(rows) {
    var el = document.getElementById('proposalsBody');
    document.getElementById('proposalsCount').textContent = rows.length;
    if (!rows.length) {
        el.innerHTML = '<div class="empty-msg">Нет предложений. Создайте КП через бот.</div>';
        return;
    }
    var html = '';
    rows.forEach(function(p) {
        var st = p.proposal_status || 'draft';
        var info = STATUS_MAP[st] || { label: st, cls: 'draft' };
        var client = p.client_company || p.client_display_name || p.client_name || '';
        var currency = p.currency || '₽';
        html += '<div class="prop-row">'
            + '<div class="status-dot ' + info.cls + '" title="' + info.label + '"></div>'
            + '<div class="prop-info">'
            + '<div class="prop-name"><a href="/proposal/' + p.token + '" target="_blank">' + esc(p.project_name || 'Без названия') + '</a></div>'
            + (client ? '<div class="prop-client">' + esc(client) + '</div>' : '')
            + '</div>'
            + '<div class="prop-cost">' + fmtMoney(p.total_cost, currency) + '</div>'
            + '<div class="prop-date">' + fmtDate(p.created_at) + '</div>'
            + '</div>';
    });
    el.innerHTML = html;
}

function renderClients(rows) {
    var el = document.getElementById('clientsBody');
    document.getElementById('clientsCount').textContent = rows.length;
    if (!rows.length) {
        el.innerHTML = '<div class="empty-msg">Нет клиентов. Клиенты появятся после привязки к КП.</div>';
        return;
    }
    var html = '';
    rows.forEach(function(c) {
        var name = [c.first_name, c.last_name].filter(Boolean).join(' ') || c.username || '—';
        var initials = (name[0] || '?').toUpperCase();
        html += '<div class="client-row">'
            + '<div class="client-avatar-sm">' + initials + '</div>'
            + '<div class="client-info">'
            + '<div class="client-name-row">' + esc(name) + '</div>'
            + (c.company ? '<div class="client-company">' + esc(c.company) + '</div>' : '')
            + '</div>'
            + '<span class="client-kp-count">' + (c.proposals_count || 0) + ' КП</span>'
            + '</div>';
    });
    el.innerHTML = html;
}

async function loadData() {
    try {
        var results = await Promise.allSettled([
            fetch('/api/proposals'),
            fetch('/api/clients'),
        ]);
        var proposals = [];
        var clients = [];
        if (results[0].status === 'fulfilled' && results[0].value.ok)
            proposals = await results[0].value.json();
        if (results[1].status === 'fulfilled' && results[1].value.ok)
            clients = await results[1].value.json();
        if (!Array.isArray(proposals)) proposals = [];
        if (!Array.isArray(clients)) clients = [];

        document.getElementById('statProposals').textContent = proposals.length;
        document.getElementById('statClients').textContent = clients.length;

        var accepted = proposals.filter(function(p) { return p.proposal_status === 'accepted'; });
        document.getElementById('statAccepted').textContent = accepted.length;

        var totalSum = 0;
        var currency = '₽';
        proposals.forEach(function(p) {
            totalSum += Number(p.total_cost || 0);
            if (p.currency) currency = p.currency;
        });
        document.getElementById('statTotalSum').textContent = totalSum > 0 ? fmtMoney(totalSum, currency) : '—';

        renderFunnel(proposals);
        renderProposals(proposals);
        renderClients(clients);
    } catch (e) {
        console.error('Seller loadData error:', e);
    }
}
