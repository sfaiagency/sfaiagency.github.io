// Shared navigation behaviors, driven by the links already present in each
// page's desktop header so every page keeps a single source of truth:
//  - desktop dropdown groups (Products, Company): click/keyboard toggling
//    layered on top of the pure-CSS hover behavior in nav.css
//  - mobile: a hamburger button and a full-screen menu where the dropdown
//    groups become labeled sections.
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
            '.mobile-nav{position:fixed;inset:0;z-index:999;background:var(--white,#FFFFFF);display:flex;justify-content:center;align-items:flex-start;overflow-y:auto;opacity:0;visibility:hidden;transform:translateY(-8px);transition:opacity .3s ease,transform .3s ease,visibility .3s;}',
            '.mobile-nav.open{opacity:1;visibility:visible;transform:translateY(0);}',
            '.mobile-nav-links{display:flex;flex-direction:column;align-items:center;gap:28px;padding:110px 24px 60px;text-align:center;}',
            '.mobile-nav-links>a{font-size:26px;font-weight:600;color:var(--coral,#E15A4A);}',
            '.mobile-nav-group{display:flex;flex-direction:column;align-items:center;gap:14px;padding-top:6px;}',
            '.mobile-nav-group-label{font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--text-gray,#666666);}',
            '.mobile-nav-group a{font-size:21px;font-weight:600;color:var(--coral,#E15A4A);}',
            '.mobile-nav a.mobile-nav-active{text-decoration:underline;text-underline-offset:6px;}',
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

        // ----- Desktop dropdown groups -----
        var groups = Array.prototype.slice.call(headerInner.querySelectorAll('.nav-group'));

        function closeGroups(except) {
            groups.forEach(function (group) {
                if (group === except) return;
                group.classList.remove('open');
                var toggle = group.querySelector('.nav-group-toggle');
                if (toggle) toggle.setAttribute('aria-expanded', 'false');
            });
        }

        groups.forEach(function (group) {
            var toggle = group.querySelector('.nav-group-toggle');
            if (!toggle) return;
            toggle.addEventListener('click', function () {
                var open = group.classList.toggle('open');
                toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
                closeGroups(group);
            });
        });

        document.addEventListener('click', function (e) {
            var inGroup = e.target.closest && e.target.closest('.nav-group');
            if (!inGroup) closeGroups(null);
        });

        // ----- Mobile menu -----
        // Mirror the desktop nav: plain links stay top-level, dropdown groups
        // become labeled sections.
        var containers = headerInner.querySelectorAll('.header-nav, .header-right');
        var items = [];
        containers.forEach(function (container) {
            items = items.concat(Array.prototype.slice.call(container.children));
        });
        if (!items.length) return;

        function makeLink(sourceLink, titleText) {
            var a = document.createElement('a');
            a.href = sourceLink.getAttribute('href');
            a.textContent = (titleText || sourceLink.textContent).trim();
            if (sourceLink.classList.contains('nav-link-active') ||
                sourceLink.classList.contains('nav-card-active')) {
                a.className = 'mobile-nav-active';
            }
            return a;
        }

        var toggle = document.createElement('button');
        toggle.className = 'nav-toggle';
        toggle.setAttribute('aria-label', 'Open menu');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.innerHTML = '<span></span><span></span><span></span>';
        headerInner.appendChild(toggle);

        var overlay = document.createElement('div');
        overlay.className = 'mobile-nav';
        var nav = document.createElement('nav');
        nav.className = 'mobile-nav-links';

        items.forEach(function (item) {
            if (item.tagName === 'A') {
                nav.appendChild(makeLink(item));
            } else if (item.classList.contains('nav-group')) {
                var groupToggle = item.querySelector('.nav-group-toggle');
                var section = document.createElement('div');
                section.className = 'mobile-nav-group';
                var label = document.createElement('span');
                label.className = 'mobile-nav-group-label';
                label.textContent = groupToggle ? groupToggle.textContent.trim() : '';
                section.appendChild(label);
                item.querySelectorAll('.nav-card').forEach(function (card) {
                    var title = card.querySelector('.nav-card-title');
                    section.appendChild(makeLink(card, title ? title.textContent : null));
                });
                nav.appendChild(section);
            }
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
            if (e.key === 'Escape') {
                closeMenu();
                closeGroups(null);
            }
        });
    });
})();
