/**
 * Toast notification component.
 * Requires: css/components/toast.css, a <div class="toast" id="toast"></div> in the page.
 *
 * Usage: showToast('Saved!'); showToast('Error!', 'error');
 */
function showToast(message, type, duration) {
    duration = duration || 2500;
    let t = document.getElementById('toast');
    if (!t) {
        t = document.createElement('div');
        t.id = 'toast';
        t.className = 'toast';
        document.body.appendChild(t);
    }
    t.textContent = message;
    t.className = 'toast' + (type === 'error' ? ' error' : '');
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.classList.remove('show'); }, duration);
}
