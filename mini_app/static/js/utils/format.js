/**
 * Shared formatting utilities.
 */

function escapeHtml(str) {
    return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatDate(iso) {
    if (!iso) return '\u2014';
    return new Date(iso).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
    });
}

function formatDateTime(iso) {
    if (!iso) return '\u2014';
    const d = new Date(iso);
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
        + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function formatDuration(minutes) {
    if (!minutes) return '\u2014';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m} мин`;
    return m === 0 ? `${h} ч` : `${h} ч ${m} мин`;
}

function formatCurrency(amount, currency) {
    if (amount == null) return '\u2014';
    const n = Number(amount);
    const sym = currency === 'USD' ? '$' : currency === 'EUR' ? '€' : '₽';
    return n.toLocaleString('ru-RU') + ' ' + sym;
}
