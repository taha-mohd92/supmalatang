"""Live browser verification against a real Chromium: video playback, parallax
transforms, reduced-motion behaviour, link integrity and load timings.

Run: python3 tools/verify_live.py   (serves ./ on :8765, exit 1 on failure)
     python3 tools/verify_live.py https://supmalatang.vercel.app/   (check the live site)
"""
import http.server, os, socketserver, subprocess, sys, threading, time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PORT = 8765
LIVE = sys.argv[1].rstrip("/") + "/" if len(sys.argv) > 1 else None
BASE = LIVE or f"http://127.0.0.1:{PORT}/"
SHOTS = os.path.join(ROOT, "tools", "screenshots")
FAIL = []
def ok(m):  print("  \033[32mPASS\033[0m", m)
def bad(m): FAIL.append(m); print("  \033[31mFAIL\033[0m", m)
def head(m): print("\n\033[1m" + m + "\033[0m")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def serve():
    if LIVE:
        class Noop:
            def shutdown(self): pass
        return Noop()
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def transforms(page):
    return page.eval_on_selector_all(
        "[data-parallax-layer]",
        "els => els.map(e => getComputedStyle(e).transform)")


def run():
    os.makedirs(SHOTS, exist_ok=True)
    httpd = serve()
    with sync_playwright() as pw:
        launch = {"args": ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"]}
        vendored = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        if os.path.exists(vendored):
            launch["executable_path"] = vendored
        browser = pw.chromium.launch(**launch)

        # ── desktop, motion allowed ─────────────────────────────────────
        head("Desktop — page load")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1)
        page = ctx.new_page()
        errors, failed = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: failed.append(r.url + " " + str(r.failure)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        t0 = time.time()
        page.goto(BASE, wait_until="load")
        load_ms = (time.time() - t0) * 1000
        page.wait_for_timeout(700)

        ok("no JS errors") if not errors else bad(f"JS errors: {errors[:3]}")
        ok("every request resolved") if not failed else bad(f"failed requests: {failed[:3]}")
        ok(f"load event at {load_ms:.0f} ms")

        nav = page.evaluate("""() => {
            const n = performance.getEntriesByType('navigation')[0];
            const p = performance.getEntriesByName('first-contentful-paint')[0];
            return { dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd,
                     fcp: p ? p.startTime : null,
                     bytes: performance.getEntriesByType('resource')
                              .reduce((s, r) => s + (r.transferSize || 0), 0),
                     reqs: performance.getEntriesByType('resource').length };
        }""")
        print(f"    DOMContentLoaded {nav['dcl']:.0f} ms · load {nav['load']:.0f} ms · "
              f"FCP {nav['fcp']:.0f} ms · {nav['reqs']} requests · "
              f"{nav['bytes']/1024:.0f} KB transferred")
        ok(f"FCP {nav['fcp']:.0f} ms (< 1800 ms)") if nav["fcp"] < 1800 \
            else bad(f"FCP {nav['fcp']:.0f} ms")
        ok(f"{nav['reqs']} requests, {nav['bytes']/1024:.0f} KB") if nav["reqs"] <= 20 \
            else bad(f"{nav['reqs']} requests")

        # ── video ───────────────────────────────────────────────────────
        head("Hero video")
        v = page.evaluate("""() => {
            const v = document.getElementById('hero-video');
            return { ready: v.readyState, w: v.videoWidth, h: v.videoHeight,
                     dur: v.duration, paused: v.paused, src: v.currentSrc,
                     muted: v.muted, loop: v.loop, t: v.currentTime };
        }""")
        ok(f"decoding {v['src'].split('/')[-1]} at {v['w']}x{v['h']}, {v['dur']:.1f}s") \
            if v["w"] > 0 else bad(f"video has no decoded frames: {v}")
        ok("readyState >= HAVE_CURRENT_DATA") if v["ready"] >= 2 else bad(f"readyState {v['ready']}")
        ok("muted + loop (autoplay-safe)") if v["muted"] and v["loop"] else bad("not muted/looping")
        page.wait_for_timeout(1200)
        t2 = page.evaluate("document.getElementById('hero-video').currentTime")
        ok(f"playhead advanced {v['t']:.2f}s → {t2:.2f}s") if t2 > v["t"] \
            else bad(f"playhead stuck at {t2}")

        # ── parallax ────────────────────────────────────────────────────
        head("Parallax")
        before = transforms(page)
        page.evaluate("window.scrollTo(0, 700)")
        page.wait_for_timeout(700)
        after = transforms(page)
        moved = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        ok(f"{len(moved)}/{len(before)} layers re-transformed on scroll") if len(moved) >= 3 \
            else bad(f"only {len(moved)} layers moved: {before} → {after}")

        ys = page.eval_on_selector_all("[data-parallax-layer]", """els => els.map(e => {
            const m = new DOMMatrixReadOnly(getComputedStyle(e).transform);
            return { y: m.m42, depth: parseFloat(e.dataset.depth) };
        })""")
        hero = [l for l in ys if l["depth"] > 0][:3]
        ordered = all(abs(hero[i]["y"]) <= abs(hero[i + 1]["y"]) + 0.5 for i in range(len(hero) - 1))
        print("    " + " · ".join(f"depth {l['depth']} → {l['y']:.1f}px" for l in ys))
        ok("deeper layers travel further (depth ordering holds)") if ordered \
            else bad(f"depth ordering broken: {hero}")
        ok("transforms are translate-only (no layout properties animated)") \
            if all("matrix" in t for t in after if t != "none") else bad("unexpected transform type")

        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
        page.wait_for_timeout(800)
        band = page.eval_on_selector_all(
            ".band [data-parallax-layer]",
            "els => els.map(e => new DOMMatrixReadOnly(getComputedStyle(e).transform).m42)")
        ok(f"second scene animates independently: {[round(b,1) for b in band]}") \
            if any(abs(b) > 1 for b in band) else bad("band layers never moved")

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(SHOTS, "desktop-hero.png"))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(SHOTS, "desktop-band.png"))

        # ── reveals + links ─────────────────────────────────────────────
        head("Reveals and links")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)
        hidden = page.eval_on_selector_all(
            ".reveal", "els => els.filter(e => !e.classList.contains('is-in')).length")
        ok("every .reveal element resolved to visible") if hidden == 0 \
            else bad(f"{hidden} reveal elements stuck hidden")

        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        dead = page.evaluate("""() => [...document.querySelectorAll('a[href^="#"]')]
            .filter(a => a.getAttribute('href') !== '#' &&
                         !document.querySelector(a.getAttribute('href')))
            .map(a => a.getAttribute('href'))""")
        ok(f"{len(links)} links, 0 dead in-page anchors") if not dead else bad(f"dead anchors {dead}")

        page.click('a[href="#visit"]')
        page.wait_for_timeout(900)
        vis = page.evaluate("""() => {
            const r = document.getElementById('visit').getBoundingClientRect();
            return r.top < window.innerHeight && r.bottom > 0; }""")
        ok("nav anchor scrolls #visit into view") if vis else bad("#visit not reached")
        ctx.close()

        # ── reduced motion ──────────────────────────────────────────────
        head("prefers-reduced-motion: reduce")
        ctx2 = browser.new_context(viewport={"width": 1440, "height": 900},
                                   reduced_motion="reduce")
        p2 = ctx2.new_page()
        p2.goto(BASE, wait_until="load")
        p2.wait_for_timeout(500)
        p2.evaluate("window.scrollTo(0, 800)")
        p2.wait_for_timeout(700)
        t = transforms(p2)
        ok("no layer is transformed under reduced motion") \
            if all(x in ("none", "matrix(1, 0, 0, 1, 0, 0)") for x in t) else bad(f"transforms: {t}")
        ok("html.motion-off applied") if p2.evaluate(
            "document.documentElement.classList.contains('motion-off')") else bad("motion-off missing")
        paused = p2.evaluate("document.getElementById('hero-video').paused")
        ok("hero video paused") if paused else bad("video still playing under reduced motion")
        vis = p2.evaluate("""() => {
            const e = document.querySelector('.reveal');
            const s = getComputedStyle(e); return s.opacity; }""")
        ok(f"content is visible without animation (opacity {vis})") if float(vis) > 0.99 \
            else bad(f"reveal content hidden at opacity {vis}")
        ok("toggle exposes aria-pressed=true (motion off)") if p2.get_attribute(
            "#motion-toggle", "aria-pressed") == "true" else bad("aria-pressed not synced")

        p2.click("#motion-toggle")          # explicit opt-in overrides the OS setting
        p2.evaluate("window.scrollTo(0, 900)")
        p2.wait_for_timeout(700)
        t = transforms(p2)
        ok("user can opt back into motion (toggle overrides OS)") \
            if any(x not in ("none", "matrix(1, 0, 0, 1, 0, 0)") for x in t) else bad("toggle no-op")
        p2.click("#motion-toggle")
        p2.wait_for_timeout(300)
        ok("preference persists to localStorage") if p2.evaluate(
            "localStorage.getItem('sam-motion')") == "off" else bad("preference not stored")
        p2.screenshot(path=os.path.join(SHOTS, "reduced-motion.png"))
        ctx2.close()

        # ── mobile ──────────────────────────────────────────────────────
        head("Mobile (iPhone-class viewport)")
        m = browser.new_context(**pw.devices["iPhone 13"])
        pm = m.new_page()
        pm.goto(BASE, wait_until="load")
        pm.wait_for_timeout(800)
        overflow = pm.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        ok("no horizontal overflow") if overflow <= 0 else bad(f"{overflow}px of horizontal scroll")
        cta = pm.evaluate("""() => {
            const a = document.querySelector('.mobile-cta').getBoundingClientRect();
            return { w: a.width, h: a.height, bottom: a.bottom <= window.innerHeight + 1 }; }""")
        ok(f"sticky call CTA visible, {cta['h']:.0f}px tall") if cta["h"] >= 44 and cta["bottom"] \
            else bad(f"mobile CTA problem: {cta}")
        taps = pm.eval_on_selector_all("a.btn, button, .mobile-cta", """els => els
            .map(e => e.getBoundingClientRect())
            .filter(r => r.width > 0 && r.height > 0 && r.height < 44).length""")
        ok("all visible tap targets ≥ 44px tall") if taps == 0 else bad(f"{taps} targets under 44px")
        pm.screenshot(path=os.path.join(SHOTS, "mobile-hero.png"))
        pm.evaluate("window.scrollTo(0, 500)")
        pm.wait_for_timeout(700)
        mt = pm.eval_on_selector_all("[data-parallax-layer]",
            "els => els.map(e => new DOMMatrixReadOnly(getComputedStyle(e).transform).m42)")
        ok(f"mobile parallax runs at reduced amplitude: max {max(abs(x) for x in mt):.1f}px") \
            if max(abs(x) for x in mt) < 120 else bad(f"mobile travel too large: {mt}")
        pm.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        pm.wait_for_timeout(600)
        pm.screenshot(path=os.path.join(SHOTS, "mobile-band.png"))
        m.close()

        # ── frame cost while scrolling ──────────────────────────────────
        head("Scroll performance")
        ctx3 = browser.new_context(viewport={"width": 1440, "height": 900})
        p3 = ctx3.new_page()
        p3.goto(BASE, wait_until="load")
        p3.wait_for_timeout(400)
        stats = p3.evaluate("""async () => {
            const gaps = [];
            let last = performance.now(), y = 0;
            return await new Promise(res => {
                function step(now) {
                    gaps.push(now - last); last = now;
                    y += 22; window.scrollTo(0, y);
                    if (gaps.length < 100) requestAnimationFrame(step);
                    else {
                        const s = gaps.slice(5).sort((a, b) => a - b);
                        res({ median: s[Math.floor(s.length / 2)], p95: s[Math.floor(s.length * .95)],
                              long: s.filter(g => g > 32).length });
                    }
                }
                requestAnimationFrame(step);
            });
        }""")
        print(f"    median frame {stats['median']:.1f} ms · p95 {stats['p95']:.1f} ms · "
              f"{stats['long']} frames over 32 ms")
        ok(f"median frame {stats['median']:.1f} ms (60fps budget 16.7 ms)") \
            if stats["median"] <= 18 else bad(f"median frame {stats['median']:.1f} ms")
        ok(f"{stats['long']} dropped frames over 95 scrolled frames") if stats["long"] <= 5 \
            else bad(f"{stats['long']} long frames")
        ctx3.close()
        browser.close()
    httpd.shutdown()

    print("\n" + "=" * 62)
    print(f"  live verification: {len(FAIL)} failed")
    for f in FAIL: print("   FAIL:", f)
    print(f"  screenshots → {os.path.relpath(SHOTS, ROOT)}/")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run())
