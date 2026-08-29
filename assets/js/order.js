/* ============================================================================
   Sup & Api Malatang — ordering prototype.
   Entirely client-side: nothing is sent anywhere and nothing is charged.
   Prices are held in sen (integers) so totals never drift on floating point.
   ========================================================================= */
(function () {
  'use strict';

  var BASE = { soup: 300, dry: 350 };        // broth/base charge, in sen
  var PORTION_G = 100;                        // one portion of any ingredient
  var MAX_QTY = 9;

  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  var money = function (sen) { return 'RM ' + (sen / 100).toFixed(2); };

  var bowl = Object.create(null);   // itemId -> { name, price, qty }

  /* ── Reading the form ─────────────────────────────────────────────────── */
  function picked(name) {
    var el = $('input[name="' + name + '"]:checked');
    return el ? el.value : null;
  }
  var STYLE_LABEL = { soup: 'Spicy Hot Pot', dry: 'Spicy Mix' };
  var BROTH_LABEL = { mala: 'Mala', tomato: 'Tomato', clear: 'Clear' };
  var HEAT_LABEL  = { 1: 'Clear', 2: 'Mild', 3: 'Medium', 4: 'Hot', 5: 'Mala' };

  function baseSen() { return BASE[picked('style')] || 0; }
  function itemsSen() {
    return Object.keys(bowl).reduce(function (s, k) { return s + bowl[k].price * bowl[k].qty; }, 0);
  }
  function totalSen() { return baseSen() + itemsSen(); }
  function totalGrams() {
    return Object.keys(bowl).reduce(function (s, k) { return s + bowl[k].qty * PORTION_G; }, 0);
  }
  function lineCount() {
    return Object.keys(bowl).reduce(function (s, k) { return s + bowl[k].qty; }, 0);
  }

  /* ── Rendering ────────────────────────────────────────────────────────── */
  function renderCart() {
    var list = $('#cart-list');
    var keys = Object.keys(bowl);
    list.textContent = '';

    if (!keys.length) {
      var li = document.createElement('li');
      li.className = 'cart__empty';
      li.textContent = 'Nothing in the bowl yet. Add something from the left.';
      list.appendChild(li);
    } else {
      keys.forEach(function (k) {
        var it = bowl[k];
        var li = document.createElement('li');
        var left = document.createElement('span');
        left.textContent = it.qty + ' × ' + it.name;
        var right = document.createElement('b');
        right.textContent = money(it.price * it.qty);
        li.appendChild(left); li.appendChild(right);
        list.appendChild(li);
      });
    }

    var dry = picked('style') === 'dry';
    $('#cart-meta').textContent = [
      STYLE_LABEL[picked('style')],
      dry ? 'no broth' : BROTH_LABEL[picked('broth')] + ' broth',
      'heat ' + picked('heat') + ' · ' + HEAT_LABEL[picked('heat')]
    ].join(' · ');

    $('#cart-weight').textContent = totalGrams() + ' g';
    $('#cart-base').textContent   = money(baseSen());
    $('#cart-total').textContent  = money(totalSen());
    $('#checkout').disabled = lineCount() === 0;

    // the broth step is meaningless for the dry mix
    $('#step-broth').hidden = dry;
  }

  /* ── Quantity controls ────────────────────────────────────────────────── */
  function bump(li, delta) {
    var id = li.getAttribute('data-item');
    var cur = bowl[id] ? bowl[id].qty : 0;
    var next = Math.max(0, Math.min(MAX_QTY, cur + delta));
    if (next === cur) return;

    if (next === 0) { delete bowl[id]; }
    else {
      bowl[id] = {
        name: li.getAttribute('data-name'),
        price: parseInt(li.getAttribute('data-price'), 10),
        qty: next
      };
    }
    $('.qty__n', li).textContent = next;
    li.classList.toggle('is-on', next > 0);
    $('[data-act="dec"]', li).disabled = next === 0;
    $('[data-act="inc"]', li).disabled = next === MAX_QTY;
    renderCart();
  }

  $$('.item').forEach(function (li) {
    $('[data-act="dec"]', li).disabled = true;
    li.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (btn) bump(li, btn.getAttribute('data-act') === 'inc' ? 1 : -1);
    });
  });

  $$('input[name="style"], input[name="broth"], input[name="heat"]').forEach(function (el) {
    el.addEventListener('change', renderCart);
  });

  /* ── Checkout sheet ───────────────────────────────────────────────────── */
  var sheet = $('#sheet');
  var lastFocus = null;

  function showPane(id) {
    ['pane-details', 'pane-review', 'pane-done'].forEach(function (p) {
      $('#' + p).hidden = (p !== id);
    });
    var step = { 'pane-details': 0, 'pane-review': 1, 'pane-done': 2 }[id];
    $$('#crumbs li').forEach(function (li, i) {
      if (i === step) li.setAttribute('aria-current', 'step');
      else li.removeAttribute('aria-current');
    });
  }

  function openSheet() {
    lastFocus = document.activeElement;
    sheet.hidden = false;
    document.body.style.overflow = 'hidden';
    showPane('pane-details');
    var first = $('#pane-details input');
    if (first) first.focus();
  }

  function closeSheet() {
    sheet.hidden = true;
    document.body.style.overflow = '';
    if (lastFocus) lastFocus.focus();
  }

  $('#checkout').addEventListener('click', openSheet);
  $$('[data-close]').forEach(function (el) { el.addEventListener('click', closeSheet); });

  document.addEventListener('keydown', function (e) {
    if (sheet.hidden) return;
    if (e.key === 'Escape') { closeSheet(); return; }
    if (e.key !== 'Tab') return;
    // keep focus inside the dialog while it is open
    var f = $$('a[href],button:not([disabled]),input,textarea,select', $('.sheet__panel'))
      .filter(function (el) { return el.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  /* ── Details → review ─────────────────────────────────────────────────── */
  $('#pane-details').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    var err = $('#details-err');
    var name = f.name.value.trim();
    var phone = f.phone.value.trim();

    if (!name || phone.replace(/\D/g, '').length < 8) {
      err.textContent = !name
        ? 'Please tell us your name.'
        : 'Please enter a phone number we can reach you on.';
      err.hidden = false;
      (!name ? f.name : f.phone).focus();
      return;
    }
    err.hidden = true;

    var list = $('#review-list');
    list.textContent = '';
    var dry = picked('style') === 'dry';
    var rows = [
      [STYLE_LABEL[picked('style')] + (dry ? '' : ' · ' + BROTH_LABEL[picked('broth')] + ' broth'),
       money(baseSen())],
      ['Heat level ' + picked('heat') + ' · ' + HEAT_LABEL[picked('heat')], '']
    ];
    Object.keys(bowl).forEach(function (k) {
      rows.push([bowl[k].qty + ' × ' + bowl[k].name, money(bowl[k].price * bowl[k].qty)]);
    });
    rows.push(['About ' + totalGrams() + ' g total', '']);
    rows.push([({ pickup: 'Pick up', dinein: 'Dine in', delivery: 'Delivery' })[f.fulfil.value]
      + ' · ' + name, '']);
    if (f.notes.value.trim()) rows.push(['Note: ' + f.notes.value.trim(), '']);

    rows.forEach(function (r) {
      var li = document.createElement('li');
      var a = document.createElement('span'); a.textContent = r[0];
      var b = document.createElement('b');    b.textContent = r[1];
      li.appendChild(a); li.appendChild(b);
      list.appendChild(li);
    });
    $('#review-total').textContent = money(totalSen());
    showPane('pane-review');
    $('#place').focus();
  });

  $('#back').addEventListener('click', function () {
    showPane('pane-details');
    $('#pane-details input').focus();
  });

  /* ── Place order (prototype: no network call) ─────────────────────────── */
  $('#place').addEventListener('click', function () {
    var f = $('#pane-details');
    $('#done-name').textContent = f.name.value.trim();
    $('#done-ref').textContent = '#SA-' + String(1000 + Math.floor(Math.random() * 8999));
    showPane('pane-done');
    $('#done-close').focus();
  });

  $('#done-close').addEventListener('click', function () {
    closeSheet();
    // reset the builder for the next bowl
    Object.keys(bowl).forEach(function (k) { delete bowl[k]; });
    $$('.item').forEach(function (li) {
      $('.qty__n', li).textContent = '0';
      li.classList.remove('is-on');
      $('[data-act="dec"]', li).disabled = true;
      $('[data-act="inc"]', li).disabled = false;
    });
    $('#pane-details').reset();
    renderCart();
  });

  renderCart();
})();
