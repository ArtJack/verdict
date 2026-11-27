"""The scripts the browser pass runs inside a page: what the page holds, the autofill and
fill plans, overflow, zoom, what scrolling reveals, the focus order and the key candidates.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations



# ── in the page ───────────────────────────────────────────────────────────────


# Helpers every page-side script starts with. `describe` names an element the way a person
# would look for it; `hiddenFromPeople` says why a rendered element cannot be seen, or "".
_LIB = r"""
const labelOf = (el) => {
  const clean = (s) => (s || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  const aria = el.getAttribute('aria-label'); if (aria) return clean(aria);
  if (el.labels && el.labels.length) return clean(el.labels[0].textContent);
  const by = el.getAttribute('aria-labelledby');
  if (by) { const l = document.getElementById(by.split(/\s+/)[0]); if (l) return clean(l.textContent); }
  const ph = el.getAttribute('placeholder'); if (ph) return clean(ph);
  const title = el.getAttribute('title'); if (title) return clean(title);
  if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') return '';
  return clean(el.textContent);
};
const describe = (el) => {
  const tag = el.tagName.toLowerCase();
  let s = tag;
  if (el.id) s += '#' + el.id;
  const name = el.getAttribute('name'); if (name) s += `[name="${name}"]`;
  const type = el.getAttribute('type'); if (tag === 'input' && type) s += `[type="${type}"]`;
  const role = el.getAttribute('role'); if (role) s += `[role="${role}"]`;
  const label = labelOf(el); if (label) s += ` "${label}"`;
  return s.slice(0, 140);
};
const hiddenFromPeople = (el) => {
  if (!el.checkVisibility || !el.checkVisibility({visibilityProperty: true})) return '';
  const r = el.getBoundingClientRect();
  const reasons = [];
  if (r.width < 2 || r.height < 2) reasons.push(`${Math.round(r.width)}×${Math.round(r.height)} px`);
  const docW = Math.max(document.documentElement.scrollWidth, innerWidth);
  const docH = Math.max(document.documentElement.scrollHeight, innerHeight);
  const x = r.left + scrollX, y = r.top + scrollY;
  if (x + r.width <= 0 || y + r.height <= 0 || x >= docW || y >= docH) reasons.push('outside the page');
  if (!el.checkVisibility({opacityProperty: true})) reasons.push('transparent');
  for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
    const s = getComputedStyle(a);
    if (/hidden|clip/.test(s.overflowX + s.overflowY)) {
      const ar = a.getBoundingClientRect();
      const w = Math.min(r.right, ar.right) - Math.max(r.left, ar.left);
      const h = Math.min(r.bottom, ar.bottom) - Math.max(r.top, ar.top);
      if (w < 2 || h < 2) { reasons.push('clipped away by an ancestor'); break; }
    }
    if (/rect\(\s*0(px)?[\s,]+0(px)?[\s,]+0(px)?[\s,]+0(px)?\s*\)/.test(s.clip) ||
        /inset\(\s*(50|100)%/.test(s.clipPath)) { reasons.push('clipped to nothing'); break; }
  }
  return [...new Set(reasons)].join(', ');
};
"""


def _js(body: str) -> str:
    return "(arg) => {" + _LIB + body + "}"


JS_PAGE = _js(r"""
  const meta = (p) => { const m = document.querySelector(`meta[property="${p}"], meta[name="${p}"]`);
                        return m ? m.getAttribute('content') : null; };
  return {
    links: [...document.querySelectorAll('a[href]')].map(a => ({href: a.href, text: (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60)})),
    og: {image: meta('og:image') || meta('twitter:image'), width: meta('og:image:width'), height: meta('og:image:height')},
    fields: document.querySelectorAll('input:not([type=hidden]), textarea, select').length,
    forms: document.forms.length,
    // Forms that would go out as a GET without JavaScript: only their pages are loaded again
    // with JavaScript off.
    getForms: [...document.forms].filter(f => !/^post$/i.test((f.getAttribute('method') || '').trim()) &&
      f.getAttribute('role') !== 'search' &&
      f.querySelector('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=search]), textarea')).length,
  };
""")


JS_AUTOFILL_PLAN = _js(r"""
  const hint = /(^|[\W_])(name|full.?name|first|last|e-?mail|phone|tel|mobile|company|organi[sz]ation|address|street|city|zip|postal)([\W_]|$)/i;
  const tokens = ['name', 'given-name', 'family-name', 'email', 'tel', 'organization', 'street-address', 'address-line1', 'postal-code', 'country'];
  const fillable = (el) => {
    if (el.disabled || el.readOnly) return false;
    if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    return ['text', 'email', 'tel', 'url', 'search', 'number', ''].includes(t);
  };
  const fields = [...document.querySelectorAll('input, textarea, select')].filter(fillable);
  const groups = new Map();
  fields.forEach((el, i) => {
    el.setAttribute('data-verdict-field', String(i));
    const key = el.form ? [...document.forms].indexOf(el.form) : -1;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(i);
  });
  const out = [];
  for (const [form, members] of groups) {
    let trigger = null, best = -1;
    for (const i of members) {
      const el = fields[i];
      if (el.tagName !== 'INPUT' || hiddenFromPeople(el) || !el.checkVisibility({visibilityProperty: true})) continue;
      const ac = (el.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/);
      const text = [el.name, el.id, labelOf(el), el.getAttribute('placeholder')].join(' ');
      const score = ac.some(t => tokens.includes(t)) ? 2 : hint.test(text) ? 1 : 0;
      if (score > best) { best = score; trigger = i; }
    }
    if (trigger !== null && best > 0) out.push({form, trigger, members, triggerDesc: describe(fields[trigger])});
    else out.push({form, trigger: null, members});
  }
  return out;
""")


JS_VALUES = _js(r"""
  const out = {};
  for (const el of document.querySelectorAll('[data-verdict-field]')) out[el.getAttribute('data-verdict-field')] = el.value || '';
  return out;
""")


JS_FIELD_FACTS = _js(r"""
  return arg.map(i => {
    const el = document.querySelector(`[data-verdict-field="${i}"]`);
    if (!el) return null;
    const signs = [];
    if (el.closest('[aria-hidden="true"]')) signs.push('inside aria-hidden');
    if (el.getAttribute('tabindex') === '-1') signs.push('tabindex="-1"');
    const ac = el.getAttribute('autocomplete'); if (ac) signs.push(`autocomplete="${ac}"`);
    return {i, desc: describe(el), name: el.getAttribute('name') || el.id || '', hidden: hiddenFromPeople(el), signs, value: el.value};
  });
""")


JS_OVERFLOW = _js(r"""
  // Two measurements, because a phone and a narrow desktop window differ: a desktop window
  // scrolls sideways, while phone emulation widens the layout viewport to the content and
  // scrolls nothing (measured 2026-11-14: 648 px of content at 375 px gave scrollX 0 and
  // innerWidth 648). The screen's width is the root's clientWidth either way.
  const se = document.scrollingElement || document.documentElement;
  const y = scrollY;
  window.scrollTo(100000, y);
  let moved = Math.max(scrollX, se.scrollLeft);
  window.scrollTo(0, y);
  const W = document.documentElement.clientWidth;
  moved = Math.max(moved, innerWidth - W);
  if (moved < 2) return null;
  const contained = (el) => {
    for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX !== 'visible' && a.getBoundingClientRect().right <= W + 1) return true;
    }
    return false;
  };
  const wide = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!el.checkVisibility || !el.checkVisibility()) continue;
    const r = el.getBoundingClientRect();
    if (r.right > W + 1 && r.width > 0 && !contained(el)) wide.push(el);
  }
  const deepest = wide.filter(el => !wide.some(o => o !== el && el.contains(o)));
  deepest.sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
  return {moved: Math.round(moved), width: W,
          culprits: deepest.slice(0, 3).map(el => `${describe(el)} (right edge at ${Math.round(el.getBoundingClientRect().right)} px)`)};
""")


JS_ZOOM_START = _js(r"""
  const vp = ((document.querySelector('meta[name="viewport"]') || {}).content || '');
  const locked = /maximum-scale\s*=\s*1(\.0*)?\s*(,|;|$)|user-scalable\s*=\s*(no|0)/i.test(vp);
  // The browser's own default size says nothing about iOS, whose defaults differ: only a size
  // the site's CSS set is measured. A shadow root keeps the site's styles off the probes.
  const host = document.createElement('div');
  const shadow = host.attachShadow({mode: 'open'});
  const defaults = {};
  for (const tag of ['input', 'select', 'textarea']) shadow.appendChild(document.createElement(tag));
  document.body.appendChild(host);
  for (const el of shadow.children) defaults[el.tagName] = parseFloat(getComputedStyle(el).fontSize);
  host.remove();
  window.__verdictZoom = {locked, defaults, fields: new Map()};
  return locked;
""")


# Read at every step of a scroll through the page, because a field a reveal effect hides at
# load is only measurable once it is shown (a Next.js site, 2026-11-14: the contact form's 14 px
# fields were `visibility: hidden` until scrolled to).
JS_ZOOM_STEP = _js(r"""
  const z = window.__verdictZoom; if (!z) return 0;
  const types = ['text', 'email', 'tel', 'url', 'search', 'password', 'number', 'date', 'datetime-local', 'month', 'time', 'week', ''];
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (z.fields.has(el)) continue;
    if (el.tagName === 'INPUT' && !types.includes((el.getAttribute('type') || 'text').toLowerCase())) continue;
    if (el.disabled || el.readOnly || hiddenFromPeople(el) || !el.checkVisibility({visibilityProperty: true})) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 16 && Math.abs(size - (z.defaults[el.tagName] || 0)) > 0.05)
      z.fields.set(el, {desc: describe(el), size: Math.round(size * 10) / 10});
  }
  return z.fields.size;
""")


JS_ZOOM_DONE = _js(r"""
  const z = window.__verdictZoom; if (!z) return null;
  return {locked: z.locked, fields: [...z.fields.values()]};
""")


JS_FILL_PLAN = _js(r"""
  const texts = [], files = [];
  [...document.querySelectorAll('input, textarea')].forEach((el, i) => {
    if (el.disabled || el.readOnly) return;
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t === 'file') { el.setAttribute('data-verdict-fill', String(i)); files.push({i, accept: el.getAttribute('accept') || '', desc: describe(el)}); return; }
    if (el.tagName === 'INPUT' && !['text', 'email', 'url', 'search', 'tel', ''].includes(t)) return;
    // Rendered is enough: filling scrolls a field into view, which runs its reveal effect.
    if (hiddenFromPeople(el) || !el.checkVisibility()) return;
    el.setAttribute('data-verdict-fill', String(i));
    texts.push({i, max: el.maxLength > 0 ? el.maxLength : null, desc: describe(el)});
  });
  return {texts, files};
""")


JS_REVEAL_INIT = _js(r"""
  window.__verdictReveal = {text: [], focus: []};
  let shown = 0, hidden = 0, fShown = 0, fHidden = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const chars = n.nodeValue.replace(/\s+/g, '').length;
    const el = n.parentElement;
    if (!chars || !el || el.closest('[aria-hidden="true"], script, style, noscript, template, [hidden], dialog:not([open])')) continue;
    if (!el.checkVisibility()) continue;
    if (el.checkVisibility({visibilityProperty: true})) { shown += chars; continue; }
    hidden += chars;
    window.__verdictReveal.text.push({el, chars, seen: false});
  }
  for (const el of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex="-1"])')) {
    if (el.closest('[aria-hidden="true"], [hidden], dialog:not([open])') || !el.checkVisibility()) continue;
    if (el.checkVisibility({visibilityProperty: true})) { fShown++; continue; }
    fHidden++;
    window.__verdictReveal.focus.push({el, seen: false});
  }
  return {shown, hidden, fShown, fHidden, height: document.documentElement.scrollHeight};
""")


JS_REVEAL_STEP = _js(r"""
  const r = window.__verdictReveal; if (!r) return 0;
  for (const e of r.text) if (!e.seen && e.el.checkVisibility({visibilityProperty: true})) e.seen = true;
  for (const e of r.focus) if (!e.seen && e.el.checkVisibility({visibilityProperty: true})) e.seen = true;
  return document.documentElement.scrollHeight;
""")


JS_REVEAL_DONE = _js(r"""
  const r = window.__verdictReveal; if (!r) return null;
  const first = r.text.find(e => e.seen) || r.text[0];
  const holder = first ? (first.el.closest('h1, h2, h3, p, li, section, article') || first.el) : null;
  return {revealed: r.text.filter(e => e.seen).reduce((s, e) => s + e.chars, 0),
          focusRevealed: r.focus.filter(e => e.seen).length,
          example: holder ? describe(holder) : ''};
""")


JS_FOCUSED = _js(r"""
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const t = (el.getAttribute('type') || 'text').toLowerCase();
  const textEntry = el.isContentEditable || el.tagName === 'TEXTAREA' ||
    (el.tagName === 'INPUT' && ['text', 'email', 'url', 'search', 'tel', 'password', 'number', ''].includes(t));
  const r = el.getBoundingClientRect();
  let box = {l: r.left, t: r.top, r: r.right, b: r.bottom};
  let a = el.parentElement;
  for (let k = 0; a && k < 4 && a !== document.body; k++, a = a.parentElement) {
    const ar = a.getBoundingClientRect();
    if (ar.width * ar.height > 150000) break;
    box = {l: Math.min(box.l, ar.left), t: Math.min(box.t, ar.top), r: Math.max(box.r, ar.right), b: Math.max(box.b, ar.bottom)};
  }
  const pad = 8;
  const clip = {x: Math.max(0, box.l - pad), y: Math.max(0, box.t - pad)};
  clip.width = Math.min(innerWidth, box.r + pad) - clip.x;
  clip.height = Math.min(innerHeight, box.b + pad) - clip.y;
  const offscreen = r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight;
  return {desc: describe(el), sig: describe(el) + '|' + (el.getAttribute('href') || ''), textEntry, offscreen, clip,
          frame: el.tagName === 'IFRAME'};
""")


JS_KEY_CANDIDATES = _js(r"""
  const native = (el) => ['BUTTON', 'SUMMARY', 'SELECT', 'TEXTAREA'].includes(el.tagName) ||
    (el.tagName === 'INPUT') || (el.tagName === 'A' && el.hasAttribute('href'));
  const out = [];
  [...document.querySelectorAll('[role="button"], [role="link"]')].forEach((el, i) => {
    if (native(el) || el.closest('[aria-hidden="true"]') || el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') return;
    if (el.tabIndex < 0 || hiddenFromPeople(el) || !el.checkVisibility({visibilityProperty: true, opacityProperty: true})) return;
    el.setAttribute('data-verdict-key', String(i));
    out.push({i, desc: describe(el), role: el.getAttribute('role')});
  });
  return out;
""")


JS_WATCH_START = _js(r"""
  window.__verdictMutations = 0;
  if (window.__verdictObserver) window.__verdictObserver.disconnect();
  window.__verdictObserver = new MutationObserver((ms) => { window.__verdictMutations += ms.length; });
  window.__verdictObserver.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  return true;
""")


JS_WATCH_READ = _js(r"""
  return window.__verdictMutations || 0;
""")
