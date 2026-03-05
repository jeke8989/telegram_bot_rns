/**
 * Unified sidebar module.
 * Usage: place <aside id="sidebar"></aside> + <div class="sidebar-overlay" id="sidebarOverlay"></div>
 * in the HTML body, then include this script.
 */
(function () {
    const SKELETON_STYLE_ID = 'sidebar-skeleton-css';
    if (!document.getElementById(SKELETON_STYLE_ID)) {
        const s = document.createElement('style');
        s.id = SKELETON_STYLE_ID;
        s.textContent = `@keyframes sb-shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}.sb-sk{background:linear-gradient(90deg,var(--surface-2,#22263a) 25%,var(--border,#2d3148) 50%,var(--surface-2,#22263a) 75%);background-size:800px 100%;animation:sb-shimmer 1.5s infinite linear;border-radius:8px}`;
        document.head.appendChild(s);
    }

    const NAV_ITEMS = [
        {
            href: '/seller',
            label: 'Мой кабинет',
            icon: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
            role: ['seller'],
        },
        {
            href: '/projects',
            label: 'Проекты',
            icon: '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>',
            role: ['admin', 'staff'],
        },
        {
            href: '/proposals',
            label: 'Предложения',
            icon: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>',
            role: ['admin', 'seller'],
        },
        {
            href: '/employees',
            label: 'Сотрудники',
            icon: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
            role: 'admin',
        },
        {
            href: '/users',
            label: 'Пользователи',
            icon: '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>',
            role: 'admin',
        },
    ];

    const SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

    function getActiveHref() {
        const path = window.location.pathname;
        if (path.startsWith('/client/')) return '/users';
        for (const item of NAV_ITEMS) {
            if (path === item.href || path.startsWith(item.href + '/')) return item.href;
        }
        return null;
    }

    function buildSidebarSkeleton() {
        const skNavItem = '<div class="sb-sk" style="height:40px;margin-bottom:4px;border-radius:10px"></div>';
        return `
        <div class="sidebar-header">
            <div class="sidebar-logo" id="sidebarLogo">
                <svg ${SVG_ATTRS}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
            </div>
            <span class="sidebar-brand">НейроСофт</span>
            <button class="sidebar-toggle" id="sidebarToggle" title="Свернуть меню">
                <svg ${SVG_ATTRS}><polyline points="15 18 9 12 15 6"/></svg>
            </button>
        </div>
        <nav class="sidebar-nav">${skNavItem}${skNavItem}${skNavItem}${skNavItem}</nav>
        <div class="sidebar-footer">
            <div class="sidebar-user" style="display:flex;align-items:center;gap:10px;padding:6px">
                <div class="sb-sk" style="width:32px;height:32px;border-radius:50%;flex-shrink:0"></div>
                <div style="flex:1;overflow:hidden">
                    <div class="sb-sk" style="height:12px;width:80%;margin-bottom:6px;border-radius:4px"></div>
                    <div class="sb-sk" style="height:10px;width:50%;border-radius:4px"></div>
                </div>
            </div>
        </div>`;
    }

    function buildSidebar(userRole) {
        const activeHref = getActiveHref();

        const navItems = NAV_ITEMS.map(item => {
            if (item.role) {
                const allowed = Array.isArray(item.role) ? item.role : [item.role];
                if (!allowed.includes(userRole)) return '';
            }
            const isActive = item.href === activeHref ? ' active' : '';
            return `
            <a href="${item.href}" class="sidebar-nav-item${isActive}">
                <svg ${SVG_ATTRS}>${item.icon}</svg>
                <span class="sidebar-nav-label">${item.label}</span>
            </a>`;
        }).join('');

        return `
        <div class="sidebar-header">
            <div class="sidebar-logo" id="sidebarLogo">
                <svg ${SVG_ATTRS}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
            </div>
            <span class="sidebar-brand">НейроСофт</span>
            <button class="sidebar-toggle" id="sidebarToggle" title="Свернуть меню">
                <svg ${SVG_ATTRS}><polyline points="15 18 9 12 15 6"/></svg>
            </button>
        </div>
        <nav class="sidebar-nav">${navItems}</nav>
        <div class="sidebar-footer">
            <div class="sidebar-user" id="sidebarUser" style="display:none">
                <div class="sidebar-user-avatar" id="sidebarAvatar"></div>
                <div class="sidebar-user-info">
                    <div class="sidebar-user-name" id="sidebarUserName"></div>
                    <div class="sidebar-user-role" id="sidebarUserRole"></div>
                </div>
            </div>
            <button class="sidebar-logout" id="sidebarLogout" style="display:none" onclick="location.href='/auth/logout'">
                <svg ${SVG_ATTRS}><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                <span class="sidebar-logout-label">Выйти</span>
            </button>
        </div>`;
    }

    function initToggle() {
        const sidebar = document.getElementById('sidebar');
        const sidebarToggle = document.getElementById('sidebarToggle');
        const sidebarLogo = document.getElementById('sidebarLogo');
        const sidebarOverlay = document.getElementById('sidebarOverlay');
        const mobileMenuBtn = document.getElementById('mobileMenuBtn');

        if (localStorage.getItem('sidebar-collapsed') === '1') {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        }

        function toggleSidebar() {
            sidebar.classList.toggle('collapsed');
            document.body.classList.toggle('sidebar-collapsed');
            localStorage.setItem('sidebar-collapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
        }

        sidebarToggle && sidebarToggle.addEventListener('click', toggleSidebar);
        sidebarLogo && sidebarLogo.addEventListener('click', () => {
            if (sidebar.classList.contains('collapsed')) toggleSidebar();
        });
        mobileMenuBtn && mobileMenuBtn.addEventListener('click', () => {
            sidebar.classList.add('mobile-open');
            sidebarOverlay && sidebarOverlay.classList.add('open');
        });
        sidebarOverlay && sidebarOverlay.addEventListener('click', () => {
            sidebar.classList.remove('mobile-open');
            sidebarOverlay.classList.remove('open');
        });
    }

    async function initSidebar() {
        const sidebar = document.getElementById('sidebar');
        if (!sidebar) return;

        sidebar.innerHTML = buildSidebarSkeleton();
        initToggle();

        try {
            const r = await fetch('/api/auth/me');
            if (!r.ok) {
                sidebar.innerHTML = buildSidebar(null);
                initToggle();
                return;
            }
            const u = await r.json();

            sidebar.innerHTML = buildSidebar(u.role);
            initToggle();

            const initial = (u.first_name || u.username || '?')[0].toUpperCase();
            const avatarEl = document.getElementById('sidebarAvatar');
            const nameEl = document.getElementById('sidebarUserName');
            const roleEl = document.getElementById('sidebarUserRole');
            const userEl = document.getElementById('sidebarUser');
            const logoutEl = document.getElementById('sidebarLogout');

            if (avatarEl) avatarEl.textContent = initial;
            if (nameEl) nameEl.textContent = u.first_name || u.username || '';
            if (roleEl) roleEl.textContent = u.role || '';
            if (userEl) userEl.style.display = 'flex';
            if (logoutEl) logoutEl.style.display = 'flex';

            document.dispatchEvent(new CustomEvent('sidebar:user', { detail: u }));
        } catch (_) {
            sidebar.innerHTML = buildSidebar(null);
            initToggle();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebar);
    } else {
        initSidebar();
    }
})();
