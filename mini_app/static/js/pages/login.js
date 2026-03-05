(async () => {
    var params = new URLSearchParams(location.search);
    var explicitNext = params.get('next');
    if (explicitNext) {
        document.cookie = 'auth_next=' + encodeURIComponent(explicitNext) + ';path=/;max-age=3600;SameSite=Lax';
    }

    function getDefaultRedirect(role, data) {
        if (role === 'user') {
            if (data && data.cabinet_token) return '/cabinet/' + data.cabinet_token;
            return '/my-cabinet';
        }
        if (role === 'seller') {
            if (explicitNext) return explicitNext;
            return '/seller';
        }
        if (explicitNext) return explicitNext;
        return '/projects';
    }

    var loginCard = document.getElementById('loginCard');
    var spinnerCard = document.getElementById('spinnerCard');
    var devCard = document.getElementById('devCard');

    // --- Check if dev mode is available ---
    var isDevMode = false;
    try {
        var devResp = await fetch('/api/auth/dev-users');
        if (devResp.ok) {
            isDevMode = true;
        }
    } catch (e) {}

    if (isDevMode) {
        var devData = await devResp.json();
        var allUsers = devData.users || [];
        devCard.style.display = '';
        initDevAuth(allUsers);
        return;
    }

    // --- Standard Telegram auth flow ---
    var tg = window.Telegram && window.Telegram.WebApp;
    if (tg && tg.initData) {
        spinnerCard.style.display = '';
        tg.expand();
        try {
            var resp = await fetch('/api/auth/telegram', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ initData: tg.initData }),
            });
            var data = await resp.json();
            if (data.ok && data.session_token) {
                var next = encodeURIComponent(getDefaultRedirect(data.role, data));
                window.location.replace('/auth/callback?token=' + data.session_token + '&next=' + next);
                return;
            }
        } catch (e) {
            console.error('Telegram auto-auth failed', e);
        }
        spinnerCard.style.display = 'none';
        loginCard.style.display = '';
    } else {
        loginCard.style.display = '';
    }

    try {
        var resp2 = await fetch('/api/auth/bot-info');
        var info = await resp2.json();
        if (info.bot_username) {
            document.getElementById('loginBtn').href = 'https://t.me/' + info.bot_username + '?start=weblogin';
        }
    } catch (e) {
        console.error('Failed to load bot info', e);
    }

    // --- Dev auth ---
    function initDevAuth(users) {
        var roleFilter = 'all';
        var tabs = document.querySelectorAll('#devRoleTabs .dev-role-tab');
        var listEl = document.getElementById('devUserList');

        tabs.forEach(function(tab) {
            tab.addEventListener('click', function() {
                tabs.forEach(function(t) { t.classList.remove('active'); });
                tab.classList.add('active');
                roleFilter = tab.dataset.role;
                renderUsers();
            });
        });

        function renderUsers() {
            var filtered = roleFilter === 'all'
                ? users
                : users.filter(function(u) { return u.role === roleFilter; });
            listEl.innerHTML = '';
            if (!filtered.length) {
                listEl.innerHTML = '<p style="text-align:center;color:var(--text-dim);padding:20px;">Нет пользователей</p>';
                return;
            }
            filtered.forEach(function(u) {
                var el = document.createElement('div');
                el.className = 'dev-user-item';
                var initials = ((u.first_name || '?')[0] + (u.last_name || '')[0]).toUpperCase();
                var displayName = (u.first_name + ' ' + (u.last_name || '')).trim();
                var meta = u.username ? '@' + u.username : 'ID: ' + u.telegram_id;
                el.innerHTML =
                    '<div class="dev-user-avatar">' + initials + '</div>' +
                    '<div class="dev-user-info">' +
                        '<div class="dev-user-name">' + displayName + '</div>' +
                        '<div class="dev-user-meta">' + meta + '</div>' +
                    '</div>' +
                    '<span class="dev-user-role-badge ' + u.role + '">' + u.role + '</span>';
                el.addEventListener('click', function() { devLogin(u.telegram_id); });
                listEl.appendChild(el);
            });
        }

        async function devLogin(telegramId) {
            try {
                var resp = await fetch('/api/auth/dev-login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ telegram_id: telegramId }),
                });
                var data = await resp.json();
                if (data.ok) {
                    window.location.replace(getDefaultRedirect(data.role, data));
                } else {
                    alert('Ошибка: ' + (data.error || 'unknown'));
                }
            } catch (e) {
                console.error('Dev login failed', e);
                alert('Ошибка авторизации');
            }
        }

        renderUsers();
    }
})();
