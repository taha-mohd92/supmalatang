"""Static verification: assets, metadata, structured data, links, weight budget.

Run: python3 tools/verify.py       (exit code 1 if any check fails)
"""
import json, os, re, subprocess, sys, html.parser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
FAIL, WARN = [], []
def ok(m):   print("  \033[32mPASS\033[0m", m)
def bad(m):  FAIL.append(m); print("  \033[31mFAIL\033[0m", m)
def warn(m): WARN.append(m); print("  \033[33mWARN\033[0m", m)
def head(m): print("\n\033[1m" + m + "\033[0m")

DOC = open("index.html", encoding="utf-8").read()
SITE = "https://supmalatang.vercel.app/"

# ── files ────────────────────────────────────────────────────────────────
head("Files")
REQUIRED = ["index.html", "404.html", "robots.txt", "sitemap.xml", "site.webmanifest",
            "assets/css/site.css", "assets/js/parallax.js",
            "assets/video/hero.mp4", "assets/video/hero.webm", "assets/video/hero-poster.jpg",
            "assets/img/og.jpg", "assets/img/favicon.svg", "assets/img/apple-touch-icon.png",
            "assets/img/layer-back.webp", "assets/img/layer-mid.webp", "assets/img/layer-front.webp"]
for f in REQUIRED:
    ok(f"{f} ({os.path.getsize(f)/1024:.1f} KB)") if os.path.exists(f) else bad(f"missing {f}")

# ── video ────────────────────────────────────────────────────────────────
head("Hero video")
try:
    import imageio_ffmpeg
    ffprobe = imageio_ffmpeg.get_ffmpeg_exe()
    for path, want_codec in (("assets/video/hero.mp4", "h264"), ("assets/video/hero.webm", "vp9")):
        out = subprocess.run([ffprobe, "-i", path, "-hide_banner"],
                             capture_output=True, text=True).stderr
        m = re.search(r"Video: (\w+).*?(\d{3,4})x(\d{3,4})", out, re.S)
        dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
        if not m:
            bad(f"{path}: no decodable video stream")
            continue
        codec, w, h = m.group(1), int(m.group(2)), int(m.group(3))
        secs = int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0
        if want_codec not in codec:
            warn(f"{path}: codec is {codec}, expected {want_codec}")
        if (w, h) != (1280, 720):
            warn(f"{path}: {w}x{h}, expected 1280x720")
        if secs < 4:
            bad(f"{path}: only {secs:.1f}s")
        else:
            ok(f"{path}: {codec} {w}x{h} {secs:.1f}s, {os.path.getsize(path)/1024:.0f} KB")
except ImportError:
    warn("imageio-ffmpeg not installed — skipped container probe")

for attr in ("muted", "loop", "playsinline", "autoplay", 'preload="metadata"',
             'poster="assets/video/hero-poster.jpg"'):
    ok(f'<video> has {attr}') if attr in DOC else bad(f"<video> missing {attr}")
if DOC.index('type="video/webm"') < DOC.index('type="video/mp4"'):
    ok("webm source listed before mp4 fallback")
else:
    warn("mp4 is offered before webm")

# ── metadata ─────────────────────────────────────────────────────────────
head("SEO metadata")
def meta(pattern, label, must_start=None):
    m = re.search(pattern, DOC)
    if not m:
        bad(f"missing {label}")
        return None
    val = m.group(1)
    if must_start and not val.startswith(must_start):
        bad(f"{label} is not absolute/business-based: {val}")
    else:
        ok(f"{label}: {val[:88]}")
    return val

meta(r'<title>(.*?)</title>', "title")
desc = meta(r'name="description" content="(.*?)"', "meta description")
if desc and not 110 <= len(desc) <= 320:
    warn(f"description is {len(desc)} chars (aim 110–160 visible, ≤320 stored)")
meta(r'rel="canonical" href="(.*?)"', "canonical", SITE)
meta(r'property="og:url" content="(.*?)"', "og:url", SITE)
meta(r'property="og:image" content="(.*?)"', "og:image", SITE)
meta(r'name="twitter:image" content="(.*?)"', "twitter:image", SITE)
for tag in ("og:title", "og:description", "og:type", "og:site_name", "og:locale",
            "og:image:width", "og:image:height", "og:image:alt"):
    ok(tag) if f'"{tag}"' in DOC else bad(f"missing {tag}")
ok("twitter:card = summary_large_image") if 'content="summary_large_image"' in DOC \
    else bad("twitter:card missing")
for tag in ('name="viewport"', 'name="theme-color"', 'rel="manifest"',
            'rel="icon"', 'rel="apple-touch-icon"', 'name="robots"'):
    ok(tag) if tag in DOC else bad(f"missing {tag}")

# OG image must be a real 1200x630 JPEG matching the declared dimensions
from PIL import Image
with Image.open("assets/img/og.jpg") as im:
    ok(f"og.jpg is {im.width}x{im.height} {im.format}") if (im.width, im.height) == (1200, 630) \
        else bad(f"og.jpg is {im.width}x{im.height}, declared 1200x630")

# ── structured data ──────────────────────────────────────────────────────
head("Structured data")
ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', DOC, re.S)
if not ld:
    bad("no JSON-LD block")
else:
    try:
        data = json.loads(ld.group(1))
        ok(f"JSON-LD parses, @type = {data.get('@type')}")
        for k in ("name", "address", "telephone", "geo", "priceRange", "aggregateRating", "hasMap"):
            ok(f"schema.{k}") if k in data else bad(f"schema missing {k}")
        if data.get("image", "").startswith(SITE):
            ok("schema.image uses the business URL")
        else:
            bad("schema.image is not absolute")
    except json.JSONDecodeError as e:
        bad(f"JSON-LD invalid: {e}")

# ── links ────────────────────────────────────────────────────────────────
head("Links")
ids = set(re.findall(r'\sid="([^"]+)"', DOC))
hrefs = re.findall(r'href="([^"]+)"', DOC)
for h in hrefs:
    if h.startswith("#"):
        ok(f"anchor {h} → #{h[1:]}") if h[1:] in ids else bad(f"dead anchor {h}")
    elif h.startswith("tel:"):
        ok(f"{h} (E.164)") if re.fullmatch(r"tel:\+\d{8,15}", h) else bad(f"bad tel link {h}")
    elif h.startswith("http"):
        pass
    elif not h.startswith("mailto:"):
        ok(f"local {h}") if os.path.exists(h) else bad(f"broken local link {h}")

for m in re.finditer(r'<a [^>]*href="(https?://[^"]+)"[^>]*>', DOC):
    tag = m.group(0)
    if 'target="_blank"' in tag and "noopener" not in tag:
        bad(f"external link without rel=noopener: {m.group(1)}")
ok("every target=_blank link carries rel=noopener")

for f, pat in (("robots.txt", SITE + "sitemap.xml"), ("sitemap.xml", SITE)):
    ok(f"{f} points at {pat}") if pat in open(f).read() else bad(f"{f} missing {pat}")

# ── accessibility ────────────────────────────────────────────────────────
head("Accessibility")
ok("single <h1>") if DOC.count("<h1") == 1 else bad(f"{DOC.count('<h1')} <h1> elements")
ok("lang attribute") if 'html lang="en"' in DOC else bad("missing lang")
ok("skip link") if "skip-link" in DOC else bad("no skip link")
for pat, label in (("prefers-reduced-motion", "CSS honours prefers-reduced-motion"),
                   ("motion-off", "CSS has a motion-off escape hatch")):
    ok(label) if pat in open("assets/css/site.css").read() else bad(label)
JS = open("assets/js/parallax.js").read()
for pat, label in (("prefers-reduced-motion", "JS reads the reduced-motion query"),
                   ("aria-pressed", "JS keeps the toggle's aria-pressed in sync"),
                   ("saveData", "JS respects Save-Data"),
                   ("{ passive: true }", "scroll listener is passive"),
                   ("translate3d", "layers move on the compositor")):
    ok(label) if pat in JS else bad(label)
imgs = re.findall(r"<img [^>]*>", DOC)
bad_alt = [i for i in imgs if "alt=" not in i]
ok(f"{len(imgs)} <img> tags, all with alt") if not bad_alt else bad(f"{len(bad_alt)} <img> without alt")

# ── depth layers ─────────────────────────────────────────────────────────
head("Parallax structure")
scenes = DOC.count("data-parallax-scene")
depths = [float(d) for d in re.findall(r'data-depth="(-?[\d.]+)"', DOC)]
ok(f"{scenes} parallax scenes") if scenes >= 2 else bad("fewer than 2 parallax scenes")
uniq = sorted(set(abs(d) for d in depths))
if len(uniq) >= 3:
    ok(f"{len(depths)} layers across {len(uniq)} distinct depths: {uniq}")
else:
    bad(f"only {len(uniq)} distinct depths — need 2–3 layered depths")

# ── weight budget ────────────────────────────────────────────────────────
head("Weight budget (initial view)")
critical = ["index.html", "assets/css/site.css", "assets/js/parallax.js",
            "assets/video/hero-poster.jpg", "assets/img/layer-mid.webp",
            "assets/img/layer-front.webp"]
total = sum(os.path.getsize(f) for f in critical) / 1024
for f in critical:
    print(f"    {f:38s} {os.path.getsize(f)/1024:7.1f} KB")
ok(f"critical path {total:.0f} KB (budget 400 KB)") if total < 400 else bad(f"critical path {total:.0f} KB > 400 KB")
allsize = sum(os.path.getsize(os.path.join(r, f))
              for r, _, fs in os.walk("assets") for f in fs) / 1024
ok(f"all assets {allsize:.0f} KB (budget 900 KB)") if allsize < 900 else warn(f"all assets {allsize:.0f} KB")
ok("no render-blocking third-party request") if "https://" not in re.sub(
    r'<script type="application/ld\+json">.*?</script>', "", DOC, flags=re.S).split("</head>")[0].replace(
    SITE, "").replace("https://schema.org", "") else warn("head references a third-party origin")

# ── summary ──────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print(f"  {len(FAIL)} failed, {len(WARN)} warnings")
for m in FAIL: print("   FAIL:", m)
for m in WARN: print("   WARN:", m)
print("=" * 62)
sys.exit(1 if FAIL else 0)
