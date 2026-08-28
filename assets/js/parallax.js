/* ============================================================================
   Sup & Api Malatang — scroll parallax, reveals and hero-video governance.

   Design notes
   ------------
   * Transform only. Every frame writes `translate3d(0, y, 0)` on a composited
     layer; nothing in the loop touches top/margin/background-position, so no
     style recalc or layout is forced while scrolling.
   * Geometry is measured once per resize, never inside the rAF loop, so the
     loop performs zero layout reads (no scroll-linked forced reflow).
   * The loop is demand-driven: it starts on scroll/resize, eases each layer to
     its target, then parks itself once every layer is within half a pixel.
   * Only scenes intersecting the viewport are updated (IntersectionObserver),
     and `will-change` is applied to active scenes only, so idle sections cost
     nothing in compositor memory.
   * Motion is opt-out in three independent ways: the OS `prefers-reduced-motion`
     setting, a persisted in-page toggle, and Save-Data / low-core devices.
   ========================================================================= */
(function () {
  'use strict';

  var root = document.documentElement;
  var reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  var coarse = window.matchMedia('(hover: none)').matches;
  var STORE_KEY = 'sam-motion';

  var conn = navigator.connection || {};
  var thrifty = conn.saveData === true ||
                /2g/.test(conn.effectiveType || '') ||
                (navigator.hardwareConcurrency || 8) <= 2;

  /* User preference: 'off' | 'on' | null (follow the system). */
  function stored() {
    try { return localStorage.getItem(STORE_KEY); } catch (e) { return null; }
  }
  function store(v) {
    try { v ? localStorage.setItem(STORE_KEY, v) : localStorage.removeItem(STORE_KEY); }
    catch (e) { /* private mode — the session still works, it just won't persist */ }
  }

  function motionAllowed() {
    var pref = stored();
    if (pref === 'off') return false;
    if (pref === 'on') return true;
    return !reduceQuery.matches && !thrifty;
  }

  /* ── Parallax engine ───────────────────────────────────────────────── */
  var scenes = [].map.call(document.querySelectorAll('[data-parallax-scene]'), function (el) {
    return {
      el: el,
      active: false,
      top: 0,
      height: 0,
      layers: [].map.call(el.querySelectorAll('[data-parallax-layer]'), function (node) {
        return {
          node: node,
          depth: parseFloat(node.getAttribute('data-depth')) || 0,
          current: 0,
          target: 0
        };
      })
    };
  });

  var viewportH = window.innerHeight;
  var amplitude = 0;
  var running = false;
  var enabled = false;

  function measure() {
    viewportH = window.innerHeight;
    /* Shorter travel on touch/small screens: the same depth ordering reads
       clearly without shoving content around on a 6-inch display. */
    amplitude = Math.min(viewportH, 900) * (coarse ? 0.16 : 0.28);
    for (var i = 0; i < scenes.length; i++) {
      var rect = scenes[i].el.getBoundingClientRect();
      scenes[i].top = rect.top + window.scrollY;
      scenes[i].height = rect.height;
    }
  }

  function computeTargets() {
    var mid = window.scrollY + viewportH / 2;
    for (var i = 0; i < scenes.length; i++) {
      var s = scenes[i];
      if (!s.active) continue;
      /* −1 when the scene sits a full viewport below, +1 when a full one above */
      var rel = (mid - (s.top + s.height / 2)) / (viewportH / 2 + s.height / 2);
      if (rel < -1) rel = -1; else if (rel > 1) rel = 1;
      for (var j = 0; j < s.layers.length; j++) {
        s.layers[j].target = rel * s.layers[j].depth * amplitude;
      }
    }
  }

  function frame() {
    var settled = true;
    for (var i = 0; i < scenes.length; i++) {
      var s = scenes[i];
      if (!s.active) continue;
      for (var j = 0; j < s.layers.length; j++) {
        var l = s.layers[j];
        var delta = l.target - l.current;
        if (Math.abs(delta) < 0.05) {
          l.current = l.target;
        } else {
          l.current += delta * 0.14;          /* critically-damped feel */
          settled = false;
        }
        l.node.style.transform = 'translate3d(0,' + l.current.toFixed(2) + 'px,0)';
      }
    }
    if (settled) { running = false; return; }
    requestAnimationFrame(frame);
  }

  function kick() {
    if (!enabled) return;
    computeTargets();
    if (!running) { running = true; requestAnimationFrame(frame); }
  }

  function clearTransforms() {
    for (var i = 0; i < scenes.length; i++) {
      for (var j = 0; j < scenes[i].layers.length; j++) {
        var l = scenes[i].layers[j];
        l.current = l.target = 0;
        l.node.style.transform = '';
        l.node.style.willChange = '';
      }
    }
  }

  var sceneObserver = 'IntersectionObserver' in window
    ? new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
          for (var k = 0; k < scenes.length; k++) {
            if (scenes[k].el !== entries[i].target) continue;
            scenes[k].active = entries[i].isIntersecting;
            for (var j = 0; j < scenes[k].layers.length; j++) {
              scenes[k].layers[j].node.style.willChange =
                entries[i].isIntersecting ? 'transform' : '';
            }
          }
        }
        kick();
      }, { rootMargin: '20% 0px' })
    : null;

  function enableParallax() {
    if (enabled || !scenes.length) return;
    enabled = true;
    measure();
    if (sceneObserver) {
      for (var i = 0; i < scenes.length; i++) sceneObserver.observe(scenes[i].el);
    } else {
      for (var k = 0; k < scenes.length; k++) scenes[k].active = true;
    }
    window.addEventListener('scroll', kick, { passive: true });
    window.addEventListener('resize', onResize, { passive: true });
    window.addEventListener('orientationchange', onResize, { passive: true });
    kick();
  }

  function disableParallax() {
    if (!enabled) return;
    enabled = false;
    running = false;
    if (sceneObserver) {
      for (var i = 0; i < scenes.length; i++) sceneObserver.unobserve(scenes[i].el);
    }
    window.removeEventListener('scroll', kick);
    window.removeEventListener('resize', onResize);
    window.removeEventListener('orientationchange', onResize);
    clearTransforms();
  }

  var resizeTimer;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { measure(); kick(); }, 120);
  }

  /* ── Scroll reveals ────────────────────────────────────────────────── */
  var reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var revealObserver = new IntersectionObserver(function (entries, obs) {
      for (var i = 0; i < entries.length; i++) {
        if (!entries[i].isIntersecting) continue;
        entries[i].target.classList.add('is-in');
        obs.unobserve(entries[i].target);
      }
    }, { rootMargin: '0px 0px -8%' });
    for (var r = 0; r < reveals.length; r++) revealObserver.observe(reveals[r]);
  } else {
    for (var r2 = 0; r2 < reveals.length; r2++) reveals[r2].classList.add('is-in');
  }

  /* ── Hero video ────────────────────────────────────────────────────── */
  var video = document.getElementById('hero-video');

  function playVideo() {
    if (!video) return;
    var p = video.play();
    if (p && p.catch) p.catch(function () { /* autoplay refused — poster stands in */ });
  }
  function pauseVideo() { if (video) video.pause(); }

  if (video) {
    /* Off-screen or background tab: stop decoding frames nobody can see. */
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting && motionAllowed()) playVideo(); else pauseVideo();
      }, { threshold: 0.05 }).observe(video);
    }
    document.addEventListener('visibilitychange', function () {
      if (document.hidden || !motionAllowed()) pauseVideo(); else playVideo();
    });
  }

  /* ── Apply / toggle ────────────────────────────────────────────────── */
  var toggle = document.getElementById('motion-toggle');

  function apply() {
    var on = motionAllowed();
    root.classList.toggle('motion-off', !on);
    if (on) { enableParallax(); playVideo(); }
    else { disableParallax(); pauseVideo(); }
    if (toggle) {
      toggle.setAttribute('aria-pressed', on ? 'false' : 'true');
      toggle.setAttribute('aria-label',
        on ? 'Motion effects are on. Turn them off.' : 'Motion effects are off. Turn them on.');
    }
  }

  if (toggle) {
    toggle.addEventListener('click', function () {
      store(motionAllowed() ? 'off' : 'on');
      apply();
    });
  }

  if (reduceQuery.addEventListener) {
    reduceQuery.addEventListener('change', function () { if (!stored()) apply(); });
  } else if (reduceQuery.addListener) {
    reduceQuery.addListener(function () { if (!stored()) apply(); });
  }

  window.addEventListener('load', function () { measure(); kick(); });

  var yr = document.getElementById('year');
  if (yr) yr.textContent = String(new Date().getFullYear());

  apply();
})();
