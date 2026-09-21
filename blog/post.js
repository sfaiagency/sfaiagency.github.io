/**
 * Renders a post body from its markdown source.
 *
 * The surrounding page — title, date, byline, hero image and, crucially, the
 * og: tags a social crawler reads — is generated ahead of time by
 * tools/build_blog_pages.py and served as static HTML. This script only fills
 * in the article body, so a crawler that never runs it still gets a complete
 * preview, and a reader with JavaScript off still gets the headline and excerpt.
 *
 * The slug comes from `<body data-post-slug="...">` rather than a query string,
 * because every post now has its own URL.
 */
(function () {
    const body = document.getElementById('post-body');
    if (!body) return;

    const slug = (document.body.getAttribute('data-post-slug') || '')
        .replace(/[^a-zA-Z0-9_-]/g, '');

    function setError(msg) {
        body.innerHTML = '<p>' + msg + ' <a href="../">Back to blog</a>.</p>';
    }

    if (!slug) {
        setError('No post specified.');
        return;
    }

    const md = window.markdownit({
        html: true,          // allow raw HTML (iframes, embeds) in authored markdown
        linkify: true,
        typographer: true,
        breaks: false
    }).use(window.markdownitFootnote);

    // Open external links in a new tab
    const defaultLinkRender = md.renderer.rules.link_open ||
        function (tokens, idx, options, env, self) {
            return self.renderToken(tokens, idx, options);
        };
    md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
        const href = tokens[idx].attrGet('href') || '';
        if (/^https?:\/\//i.test(href)) {
            tokens[idx].attrSet('target', '_blank');
            tokens[idx].attrSet('rel', 'noopener noreferrer');
        }
        return defaultLinkRender(tokens, idx, options, env, self);
    };

    fetch('../posts/' + slug + '.md', { cache: 'no-cache' })
        .then(function (r) {
            if (!r.ok) throw new Error('not-found');
            return r.text();
        })
        .then(function (markdown) {
            body.innerHTML = md.render(markdown);
        })
        .catch(function () {
            setError('Post not found.');
        });
})();
