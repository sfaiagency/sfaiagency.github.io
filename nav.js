// Mobile navigation: builds a hamburger button and a full-screen menu
// overlay from the links already present in the desktop header, so each
// page keeps a single source of truth for its navigation.
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var headerInner = document.querySelector('.header .header-inner');
        if (!headerInner) return;

        var links = headerInner.querySelectorAll('.header-nav a, .header-right a');
        if (!links.length) return;

        // Hamburger toggle button.
        var toggle = document.createElement('button');
        toggle.className = 'nav-toggle';
        toggle.setAttribute('aria-label', 'Open menu');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.innerHTML = '<span></span><span></span><span></span>';
        headerInner.appendChild(toggle);

        // Full-screen overlay menu mirroring the header links.
        var overlay = document.createElement('div');
        overlay.className = 'mobile-nav';
        var nav = document.createElement('nav');
        nav.className = 'mobile-nav-links';
        links.forEach(function (link) {
            var a = document.createElement('a');
            a.href = link.getAttribute('href');
            a.textContent = link.textContent.trim();
            if (link.classList.contains('nav-link-active')) {
                a.className = 'mobile-nav-active';
            }
            nav.appendChild(a);
        });
        overlay.appendChild(nav);
        document.body.appendChild(overlay);

        function openMenu() {
            overlay.classList.add('open');
            toggle.classList.add('open');
            toggle.setAttribute('aria-expanded', 'true');
            toggle.setAttribute('aria-label', 'Close menu');
            document.body.classList.add('nav-open');
        }
        function closeMenu() {
            overlay.classList.remove('open');
            toggle.classList.remove('open');
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-label', 'Open menu');
            document.body.classList.remove('nav-open');
        }

        toggle.addEventListener('click', function () {
            if (overlay.classList.contains('open')) closeMenu();
            else openMenu();
        });
        nav.addEventListener('click', function (e) {
            if (e.target.tagName === 'A') closeMenu();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeMenu();
        });
    });
})();
