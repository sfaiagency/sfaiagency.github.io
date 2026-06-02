// Mobile navigation: builds a hamburger button and a full-screen menu
// overlay from the links already present in the desktop header, so each
// page keeps a single source of truth for its navigation.
(function () {
    // Inject the mobile-nav styles from here so the hamburger works on every
    // page regardless of which (possibly cached) stylesheet that page loads.
    function injectStyles() {
        if (document.getElementById('mobile-nav-styles')) return;
        var css = [
            '.nav-toggle{display:none;flex-direction:column;justify-content:center;gap:5px;width:44px;height:44px;padding:0;margin:0;background:none;border:none;cursor:pointer;}',
            '.nav-toggle span{display:block;width:26px;height:3px;border-radius:3px;background:var(--coral,#E15A4A);transition:transform .3s ease,opacity .3s ease;}',
            '.nav-toggle.open span:nth-child(1){transform:translateY(8px) rotate(45deg);}',
            '.nav-toggle.open span:nth-child(2){opacity:0;}',
            '.nav-toggle.open span:nth-child(3){transform:translateY(-8px) rotate(-45deg);}',
            '.mobile-nav{position:fixed;inset:0;z-index:999;background:var(--white,#FFFFFF);display:flex;align-items:center;justify-content:center;opacity:0;visibility:hidden;transform:translateY(-8px);transition:opacity .3s ease,transform .3s ease,visibility .3s;}',
            '.mobile-nav.open{opacity:1;visibility:visible;transform:translateY(0);}',
            '.mobile-nav-links{display:flex;flex-direction:column;align-items:center;gap:34px;}',
            '.mobile-nav-links a{font-size:28px;font-weight:600;color:var(--coral,#E15A4A);}',
            '.mobile-nav-links a.mobile-nav-active{text-decoration:underline;text-underline-offset:6px;}',
            'body.nav-open{overflow:hidden;}',
            '@media (max-width:768px){.header-right,.header-nav{display:none;}.nav-toggle{display:flex;}}'
        ].join('');
        var style = document.createElement('style');
        style.id = 'mobile-nav-styles';
        style.textContent = css;
        document.head.appendChild(style);
    }

    document.addEventListener('DOMContentLoaded', function () {
        injectStyles();

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
