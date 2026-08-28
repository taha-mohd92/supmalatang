# Sup &amp; Api Malatang — restaurant site

Single-page site for **Sup & Api Malatang**, G-07 Sunway Avila Avenue, Taman Sri Rampai,
Wangsa Maju, 53300 Kuala Lumpur. No framework, no build step, no third-party request:
`index.html` plus one stylesheet, one script, and procedurally generated media.

## Three-line design summary

1. **Stitch/Material-3 in a chilli-oil palette** — tonal roles (ember `#c4331d`, warm cream
   surfaces), a 12/20/28/pill shape scale, and pill buttons carry a dark cinematic hero into
   calm light content sections, so the restaurant reads premium without a single stock photo.
2. **Depth is the whole motion language** — a looping ambient plate, a spice-bokeh plate and a
   steam plate drift at three different rates behind the copy, with an opposing-depth glass
   "Today" card; every layer moves on `translate3d` only, so scrolling stays on the compositor.
3. **Motion is a courtesy, never a requirement** — `prefers-reduced-motion`, Save-Data and a
   persisted in-page toggle each fully disable parallax, reveals and video, and the page is
   complete, legible and fully navigable with JavaScript off.

## Layout

```
index.html            page, metadata, JSON-LD Restaurant schema
404.html              not-found page
assets/css/site.css   design tokens → primitives → components
assets/js/parallax.js parallax engine, reveals, motion toggle, video governance
assets/video/         hero.webm / hero.mp4 / hero-poster.jpg (8s seamless loop)
assets/img/           parallax depth plates, OG image, icons
tools/make_media.py   regenerates every image and video from code
tools/verify.py       static checks: assets, metadata, schema, links, weight budget
tools/verify_live.py  Chromium checks: playback, parallax, reduced motion, mobile, frame cost
tools/stitch_call.py  direct JSON-RPC client for the Stitch MCP server in .mcp.json
```

## The parallax engine

* **Transform-only.** Each frame writes `translate3d(0, y, 0)` on composited layers. Nothing in
  the loop touches layout properties.
* **No layout reads in the loop.** Scene geometry is measured on load and on resize only, so
  scrolling never forces a synchronous reflow.
* **Demand-driven.** The rAF loop starts on scroll, eases every layer toward its target at
  `0.14` per frame, and parks itself once all layers are within half a pixel.
* **Viewport-scoped.** An `IntersectionObserver` marks scenes active; `will-change: transform`
  is applied only while a scene is near the viewport.
* **Damped on touch.** Travel is `min(vh, 900) × 0.28` on pointer devices and `× 0.16` on
  coarse pointers, so small screens get the depth cue without content sliding around.

## Accessibility

Motion stops completely — parallax, reveals, the scroll cue and the hero video — when any of
these is true: the OS asks for reduced motion, the browser reports Save-Data or ≤2 cores, or
the visitor presses the header's **Motion** toggle (persisted to `localStorage`, and it
overrides the OS setting in both directions). Beyond motion: skip link, one `<h1>`, visible
`:focus-visible` rings, ≥44px touch targets, semantic landmarks, and `aria-pressed` kept in
sync on the toggle.

## Performance

Measured in headless Chromium at 1440×900 (see `tools/verify_live.py`):

| Metric | Result |
| --- | --- |
| First Contentful Paint | ~220 ms |
| Requests / transferred | 8 / ~238 KB |
| Critical-path bytes | 198 KB (budget 400 KB) |
| Median frame while scrolling | 16.7 ms (matches this machine's idle rAF cadence) |
| Long frames (>32 ms) per 95 scrolled | 0–2 |

Getting there meant deleting the expensive things: a CSS `filter` over playing video, four
full-viewport `mix-blend-mode` layers, and a `backdrop-filter` behind the sticky header. Before
those cuts the median frame was **49.9 ms**; after, **16.7 ms**. Below-fold sections use
`content-visibility: auto`, and the hero video pauses when off-screen or in a background tab.

## SEO

Canonical URL, `og:*` (with an absolute 1200×630 `og:image` on the site's own origin),
`twitter:summary_large_image`, geo meta, `robots.txt`, `sitemap.xml`, a web manifest, and
`Restaurant` JSON-LD carrying the address, phone, geo coordinates derived from the listing's
plus code, price range, `hasMap` and `aggregateRating` (4.5 / 125).

Business facts come from the restaurant's public Google listing. The site does not claim a
closing time (the listing's varies) and quotes the halal remark as a visitor review rather
than asserting certification.

## Working on it

```bash
python3 tools/make_media.py     # regenerate video, poster, OG image, depth plates
python3 tools/verify.py         # static checks
python3 -m http.server 8765     # serve locally
python3 tools/verify_live.py    # browser checks + screenshots in tools/screenshots/
```

Deployment: `.github/workflows/pages.yml` verifies, then publishes to GitHub Pages at
`https://taha-mohd92.github.io/supmalatang/`. If a custom domain is added later, update the
canonical/OG/JSON-LD URLs in `index.html`, `robots.txt` and `sitemap.xml` — they are the only
places the origin appears.

### Stitch MCP

`.mcp.json` points at the Stitch MCP server. The committed key is an expired short-lived Google
token — the endpoint answers, then rejects the call with *"Expected OAuth 2 access token"* —
so a fresh credential is needed before Stitch can generate screens. Register it with:

```bash
claude mcp add stitch --transport http https://stitch.googleapis.com/mcp \
  --header "X-Goog-Api-Key: <fresh-key>" -s user
```

MCP servers are read at session start, so a new session is required to pick it up.
