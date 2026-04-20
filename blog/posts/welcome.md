Welcome to the SFAI.agency blog. This is where we'll share notes from our research, updates on the tools we're building for artists, and longer-form thinking about the shape of generative AI.

## What you'll find here

We'll post on a few recurring themes:

- **Research notes.** Short write-ups that accompany our papers, plus work-in-progress we want to share early.
- **Field reports.** What we're learning from artists, studios, and legal teams as they navigate the new landscape.
- **Tools and experiments.** New things we've built, and what we learned building them.

## Authoring posts

Posts in this blog are just markdown files that live in the repo[^md]. You can use the full range of markdown you'd expect — **bold**, *italics*, [links](https://sfai.agency), headings, lists, images, and code:

```python
def detect_style(image):
    return model.predict(image)
```

You can embed video, images, or interactive widgets directly with raw HTML. For example, an embedded YouTube video:

<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="Video" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>

Or a simple image with a caption:

<figure>
  <img src="../../assets/about/office.jpg" alt="The SFAI office">
  <figcaption>A corner of the SFAI office.</figcaption>
</figure>

> Footnotes[^why], blockquotes, tables, and the rest of GitHub-flavored markdown all work.

More soon.

[^md]: Every post is a file under `blog/posts/`, listed in `manifest.json`. Adding a post means dropping a new `.md` file in that folder and appending an entry to the manifest.
[^why]: We chose markdown so that writing a post feels like writing a README — no CMS, no deploy step beyond a git push.
