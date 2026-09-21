# Adding a blog post

Posts are markdown files plus one entry in `posts/manifest.json`. Two generators
turn that into the pages that actually get served.

## 1. Write the post

Create `posts/<slug>.md` and add an entry to `posts/manifest.json`:

```json
{
    "slug": "my-post",
    "title": "My Post",
    "date": "2026-09-21",
    "author": "Jane Doe",
    "excerpt": "One or two sentences. This is the text LinkedIn and X show under the headline, so write it for a reader scrolling past.",
    "featured": true,
    "image": "posts/images/my-post.jpg"
}
```

The slug must be lowercase letters, digits and hyphens, and becomes the URL:
`sfai.agency/blog/my-post/`.

## 2. Build the share card

```sh
pip install Pillow
python3 ../tools/build_share_images.py
```

This writes `assets/share/blog-<slug>.jpg`, a 1200x630 card cropped or padded
from the hero image — the size and shape LinkedIn, Facebook, X and Slack expect.
The script picks a treatment from the source's aspect ratio; if it guesses
wrong, add `"shareFocus"` to the manifest entry, one of `top`, `center`,
`bottom` or `contain`, and run it again. Check the result before committing.

## 3. Build the post page

```sh
python3 ../tools/build_blog_pages.py
```

This writes `blog/<slug>/index.html`: the headline, date, byline, hero image and
the `og:`/`twitter:` tags, all as static HTML. Do not edit those files by hand —
they are overwritten on every build, and the Pages workflow regenerates them on
deploy.

Commit the markdown, the manifest, the share card and the generated page.

## Why the pages are generated

Posts used to be served from one shell page at `/blog/post/?slug=<slug>`, with
everything filled in by JavaScript. Social crawlers don't run JavaScript: they
fetch the HTML, find no title and no image, and every post in the site shares as
the same blank card. Runtime `<meta>` juggling can't fix that — the tags have to
be in the bytes the crawler is served, which means one real page per post.

`/blog/post/?slug=<slug>` still redirects, so links already posted keep working.

## Checking a preview

After deploying, paste the post URL into
[LinkedIn's Post Inspector](https://www.linkedin.com/post-inspector/). It shows
what LinkedIn sees and re-scrapes the page, which is also how you clear a cached
preview from an earlier version. Facebook and X have the same thing at
[developers.facebook.com/tools/debug](https://developers.facebook.com/tools/debug/)
and [cards-dev.twitter.com/validator](https://cards-dev.twitter.com/validator).
