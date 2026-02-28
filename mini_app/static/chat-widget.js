/**
 * Reusable chat widget.
 *
 * Usage:
 *   <div id="myChat"></div>
 *   <script src="/chat-widget.js"></script>
 *   <script>
 *     ChatWidget.init({
 *       container: '#myChat',
 *       messagesUrl: '/api/client/5/messages',
 *       sendUrl: '/api/client/5/messages',
 *       senderName: 'Менеджер',
 *       fetchFn: authFetch,  // or window.fetch
 *       pollInterval: 5000,
 *     });
 *   </script>
 */
(function () {
    'use strict';

    function escapeHtml(t) {
        var d = document.createElement('div');
        d.textContent = t || '';
        return d.innerHTML;
    }

    function formatTime(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        var pad = function (n) { return n < 10 ? '0' + n : n; };
        return pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function formatDate(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        var months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
        return d.getDate() + ' ' + months[d.getMonth()];
    }

    function injectStyles() {
        if (document.getElementById('chat-widget-styles')) return;
        var style = document.createElement('style');
        style.id = 'chat-widget-styles';
        style.textContent = [
            '.cw-wrap { display:flex; flex-direction:column; height:100%; min-height:300px; background:var(--bg,#0d0f17); border:1px solid var(--border,#1e2235); border-radius:14px; overflow:hidden; }',
            '.cw-header { padding:14px 18px; border-bottom:1px solid var(--border,#1e2235); display:flex; align-items:center; gap:10px; }',
            '.cw-header-icon { width:32px; height:32px; border-radius:8px; background:rgba(120,124,245,.12); display:flex; align-items:center; justify-content:center; font-size:16px; }',
            '.cw-header-title { font-size:.9rem; font-weight:600; color:var(--text,#e4e6f0); }',
            '.cw-header-sub { font-size:.75rem; color:var(--text-dim,#8b8fa8); }',
            '.cw-messages { flex:1; overflow-y:auto; padding:16px 18px; display:flex; flex-direction:column; gap:8px; }',
            '.cw-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1; color:var(--text-dim,#8b8fa8); font-size:.85rem; gap:8px; }',
            '.cw-empty-icon { font-size:2rem; }',
            '.cw-date-sep { text-align:center; font-size:.72rem; color:var(--text-dim,#8b8fa8); padding:8px 0 4px; }',
            '.cw-msg { max-width:75%; padding:10px 14px; border-radius:14px; font-size:.85rem; line-height:1.5; position:relative; word-wrap:break-word; }',
            '.cw-msg-in { background:var(--surface,#161928); color:var(--text,#e4e6f0); align-self:flex-start; border-bottom-left-radius:4px; }',
            '.cw-msg-out { background:rgba(120,124,245,.15); color:var(--text,#e4e6f0); align-self:flex-end; border-bottom-right-radius:4px; }',
            '.cw-msg-sender { font-size:.72rem; font-weight:600; color:var(--accent,#787cf5); margin-bottom:3px; }',
            '.cw-msg-time { font-size:.65rem; color:var(--text-dim,#8b8fa8); margin-top:4px; text-align:right; }',
            '.cw-input-bar { padding:12px 14px; border-top:1px solid var(--border,#1e2235); display:flex; gap:8px; align-items:flex-end; }',
            '.cw-input { flex:1; background:var(--surface,#161928); border:1px solid var(--border,#1e2235); border-radius:10px; padding:10px 14px; color:var(--text,#e4e6f0); font-size:.85rem; resize:none; outline:none; max-height:100px; font-family:inherit; transition:border-color .2s; }',
            '.cw-input:focus { border-color:var(--accent,#787cf5); }',
            '.cw-send-btn { width:38px; height:38px; border-radius:10px; background:var(--accent,#787cf5); border:none; color:#fff; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:opacity .2s; flex-shrink:0; }',
            '.cw-send-btn:hover { opacity:.85; }',
            '.cw-send-btn:disabled { opacity:.4; cursor:default; }',
            '.cw-send-btn svg { width:18px; height:18px; }',
        ].join('\n');
        document.head.appendChild(style);
    }

    function buildWidget(containerOrOpts, opts) {
        if (!opts && typeof containerOrOpts === 'object' && containerOrOpts.container) {
            opts = containerOrOpts;
            containerOrOpts = opts.container;
        }
        opts = opts || {};
        injectStyles();
        var el = typeof containerOrOpts === 'string' ? document.querySelector(containerOrOpts) : containerOrOpts;
        if (!el) return null;

        el.innerHTML = [
            '<div class="cw-wrap">',
            '  <div class="cw-header">',
            '    <div class="cw-header-icon">💬</div>',
            '    <div>',
            '      <div class="cw-header-title">' + escapeHtml(opts.headerTitle || 'Чат') + '</div>',
            '      <div class="cw-header-sub">' + escapeHtml(opts.headerSub || 'Сообщения доставляются в Telegram') + '</div>',
            '    </div>',
            '  </div>',
            '  <div class="cw-messages" id="cwMessages"></div>',
            '  <div class="cw-input-bar">',
            '    <textarea class="cw-input" id="cwInput" rows="1" placeholder="Введите сообщение..."></textarea>',
            '    <button class="cw-send-btn" id="cwSendBtn" title="Отправить">',
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
            '    </button>',
            '  </div>',
            '</div>',
        ].join('\n');

        var messagesEl = el.querySelector('#cwMessages');
        var inputEl = el.querySelector('#cwInput');
        var sendBtn = el.querySelector('#cwSendBtn');
        var fetchFn = opts.fetchFn || window.fetch.bind(window);
        var lastMsgId = 0;
        var polling = null;

        function scrollBottom() {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        function renderMessages(msgs) {
            if (!msgs.length) {
                messagesEl.innerHTML = '<div class="cw-empty"><div class="cw-empty-icon">💬</div>Сообщений пока нет<br>Напишите первое сообщение</div>';
                return;
            }
            var html = '';
            var lastDate = '';
            msgs.forEach(function (m) {
                var dateStr = formatDate(m.created_at);
                if (dateStr !== lastDate) {
                    html += '<div class="cw-date-sep">' + dateStr + '</div>';
                    lastDate = dateStr;
                }
                var cls = m.direction === 'in' ? 'cw-msg-in' : 'cw-msg-out';
                html += '<div class="cw-msg ' + cls + '">';
                if (m.sender_name) html += '<div class="cw-msg-sender">' + escapeHtml(m.sender_name) + '</div>';
                html += escapeHtml(m.message);
                html += '<div class="cw-msg-time">' + formatTime(m.created_at) + '</div>';
                html += '</div>';
                if (m.id > lastMsgId) lastMsgId = m.id;
            });
            messagesEl.innerHTML = html;
            scrollBottom();
        }

        async function loadMessages() {
            try {
                var res = await fetchFn(opts.messagesUrl);
                if (!res.ok) return;
                var msgs = await res.json();
                renderMessages(msgs);
            } catch (e) {
                console.error('Chat load error:', e);
            }
        }

        async function sendMessage() {
            var text = inputEl.value.trim();
            if (!text) return;
            sendBtn.disabled = true;
            inputEl.value = '';
            try {
                var res = await fetchFn(opts.sendUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text }),
                });
                if (res.ok) {
                    await loadMessages();
                }
            } catch (e) {
                console.error('Chat send error:', e);
            } finally {
                sendBtn.disabled = false;
                inputEl.focus();
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Auto-resize textarea
        inputEl.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });

        loadMessages();

        if (opts.pollInterval) {
            polling = setInterval(loadMessages, opts.pollInterval);
        }

        return {
            refresh: loadMessages,
            destroy: function () {
                if (polling) clearInterval(polling);
                el.innerHTML = '';
            },
        };
    }

    window.ChatWidget = { init: buildWidget };
})();
