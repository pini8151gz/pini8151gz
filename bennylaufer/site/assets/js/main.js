/* ==========================================================================
   Benny Laufer — interaction and motion, no dependencies.
   One scroll listener, one rAF per frame: every scrubbed element reads its
   rect first, then writes transforms. Without this file the page is
   complete; with reduced motion it stays still.
   ========================================================================== */
(() => {
  'use strict';

  const d = document;
  const html = d.documentElement;
  const $ = (s, c = d) => c.querySelector(s);
  const $$ = (s, c = d) => Array.from(c.querySelectorAll(s));
  let BL = {};
  try { BL = JSON.parse($('#bl-config').textContent); } catch (e) { /* defaults below */ }
  const rtl = html.dir === 'rtl';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const motion = html.classList.contains('fx') && !reduce;
  if (!motion) html.classList.remove('fx');
  html.classList.add('ready');

  const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
  const range = (p, a, b) => clamp((p - a) / (b - a));
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  $$('.js-year').forEach((el) => { el.textContent = String(new Date().getFullYear()); });

  /* ------------------------------------------------------------------------
     Scroll engine
     ------------------------------------------------------------------------ */
  const scrubs = [];
  let queued = false;
  const near = new IntersectionObserver((entries) => {
    entries.forEach((e) => { const s = scrubs.find((x) => x.el === e.target); if (s) s.on = e.isIntersecting; });
    queue();
  }, { rootMargin: '25% 0px' });
  function scrub(el, write) { if (!el) return; scrubs.push({ el, write, on: false }); near.observe(el); }
  function frame() {
    queued = false;
    const vh = window.innerHeight;
    const live = scrubs.filter((s) => s.on);
    const rects = live.map((s) => s.el.getBoundingClientRect());
    live.forEach((s, i) => s.write(rects[i], vh));
  }
  function queue() { if (!queued) { queued = true; requestAnimationFrame(frame); } }
  addEventListener('scroll', queue, { passive: true });
  addEventListener('resize', queue, { passive: true });

  /* ------------------------------------------------------------------------
     Header: solid after the top, hides while reading down, follows the paper
     ------------------------------------------------------------------------ */
  const nav = $('#nav');
  let lastY = scrollY;
  let menuOpen = false;
  function headerOnScroll() {
    const y = scrollY;
    nav.classList.toggle('is-solid', y > 24);
    if (!menuOpen && !d.activeElement?.closest?.('#nav')) {
      if (y > lastY + 6 && y > innerHeight * 0.8) nav.classList.add('is-hidden');
      else if (y < lastY - 6 || y < 80) nav.classList.remove('is-hidden');
    }
    lastY = y;
  }
  addEventListener('scroll', headerOnScroll, { passive: true });
  headerOnScroll();
  nav.addEventListener('focusin', () => nav.classList.remove('is-hidden'));

  const paper = $('.paper');
  let paperIO;
  function watchPaper() {
    if (paperIO) paperIO.disconnect();
    const line = Math.round(nav.offsetHeight / 2);
    paperIO = new IntersectionObserver(([e]) => nav.classList.toggle('on-paper', e.isIntersecting),
      { rootMargin: `-${line}px 0px -${Math.max(0, innerHeight - line - 1)}px 0px` });
    paperIO.observe(paper);
  }
  if (paper) { watchPaper(); addEventListener('resize', debounce(watchPaper, 200)); }

  const links = $$('.nav-links a');
  const secIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      const id = '#' + e.target.id;
      links.forEach((a) => { if (a.getAttribute('href') === id) a.setAttribute('aria-current', e.isIntersecting ? 'true' : 'false'); });
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  ['about', 'videos', 'services', 'contact'].forEach((id) => { const s = d.getElementById(id); if (s) secIO.observe(s); });

  // the big monogram owns the first screen; the small one returns after it
  const heroName = $('.hero-name');
  if (!motion && heroName) {
    new IntersectionObserver(([e]) => nav.classList.toggle('show-brand', !e.isIntersecting)).observe(heroName);
  }

  /* ------------------------------------------------------------------------
     Mobile menu (focus stays inside while open)
     ------------------------------------------------------------------------ */
  const burger = $('.burger');
  const menu = $('#menu');
  const behind = [$('#main'), $('.footer'), $('#dock')].filter(Boolean);
  function setMenu(open) {
    menuOpen = open;
    menu.hidden = !open;
    burger.setAttribute('aria-expanded', String(open));
    html.classList.toggle('menu-open', open);
    behind.forEach((el) => { el.inert = open; });
    d.body.style.overflow = open ? 'hidden' : '';
    if (open) $('.menu-links a', menu)?.focus();
    else burger.focus({ preventScroll: true });
  }
  burger?.addEventListener('click', () => setMenu(!menuOpen));
  menu?.addEventListener('click', (e) => { if (e.target.closest('a[href^="#"]')) setMenu(false); });
  d.addEventListener('keydown', (e) => { if (e.key === 'Escape' && menuOpen) setMenu(false); });

  /* ------------------------------------------------------------------------
     Mobile action bar
     ------------------------------------------------------------------------ */
  const dock = $('#dock');
  const hero = $('.hero');
  const contact = $('#contact');
  const state = { pastHero: false, atContact: false, typing: false };
  function syncDock() {
    if (!dock) return;
    const show = state.pastHero && !state.atContact && !state.typing && !menuOpen;
    dock.classList.toggle('is-visible', show);
    html.classList.toggle('dock-on', show);
    dock.inert = !show;
  }
  if (dock && hero && contact) {
    new IntersectionObserver(([e]) => { state.pastHero = !e.isIntersecting && e.boundingClientRect.top < 0; syncDock(); }, { rootMargin: '0px 0px -60% 0px' }).observe(hero);
    new IntersectionObserver(([e]) => { state.atContact = e.isIntersecting || e.boundingClientRect.top < 0; syncDock(); }).observe(contact);
    d.addEventListener('focusin', (e) => { if (e.target.matches('input, textarea')) { state.typing = true; syncDock(); } });
    d.addEventListener('focusout', (e) => { if (e.target.matches('input, textarea')) { state.typing = false; syncDock(); } });
    syncDock();
  }

  /* ------------------------------------------------------------------------
     WhatsApp: the form composes the message, every WhatsApp link carries text
     ------------------------------------------------------------------------ */
  const WA = 'https://wa.me/' + (BL.wa || '972559330757') + '?text=';
  $$('.js-wa-hello').forEach((a) => { if (BL.hello) a.href = WA + encodeURIComponent(BL.hello); });

  const form = $('#inq');
  const fDate = $('#fDate');
  const fPlace = $('#fPlace');
  const dateErr = $('#fDateErr');
  const waText = $('#waText');
  const send = $('#fSend');
  const status = $('#fStatus');
  const today = new Date();
  const iso = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  if (fDate) fDate.min = iso(today);

  function dateValue() {
    const v = fDate?.value || '';
    const p = v.split('-').map(Number);
    if (p.length !== 3 || p.some(isNaN)) return { text: BL.tbd, past: false };
    const dt = new Date(p[0], p[1] - 1, p[2]);
    let text = v;
    try { text = dt.toLocaleDateString(BL.locale || undefined, { day: 'numeric', month: 'long', year: 'numeric' }); } catch (e) { /* raw value */ }
    return { text, past: iso(dt) < iso(today) };
  }
  function compose() {
    const key = form.querySelector('input[name="type"]:checked')?.value || 'o1';
    const date = dateValue();
    const msg = String(BL.text || '')
      .replace('{type}', (BL.types || {})[key] || '')
      .replace('{date}', date.text)
      .replace('{place}', fPlace.value.trim() || BL.tbd);
    return { msg, past: date.past };
  }
  function render(showErrors) {
    const { msg, past } = compose();
    waText.textContent = msg;
    send.href = WA + encodeURIComponent(msg);
    const invalid = past && (showErrors || fDate.getAttribute('aria-invalid') === 'true');
    fDate.setAttribute('aria-invalid', String(invalid));
    dateErr.hidden = !invalid;
    return !past;
  }
  if (form) {
    form.addEventListener('input', () => { status.hidden = true; render(false); });
    fDate.addEventListener('change', () => render(true));
    form.addEventListener('submit', (e) => e.preventDefault());
    send.addEventListener('click', (e) => {
      if (!render(true)) { e.preventDefault(); fDate.focus(); return; }
      status.hidden = false; // the new tab may be blocked; say what happened and offer the phone
    });
    render(false);
  }

  /* ------------------------------------------------------------------------
     Video highlights + theatre
     ------------------------------------------------------------------------ */
  const reels = $$('.reel');
  const track = $('.reels-track');
  const count = $('.js-count');
  const toggle = $('.js-toggle');
  const videos = $('#videos');
  const theater = $('#theater');
  const tVideo = theater && $('.theater-video', theater);
  const tErr = theater && $('.theater-err', theater);
  let active = 0;
  let autoplay = motion;
  let inView = false;
  let theaterOpen = false;
  let byCode = 0;
  let raf = 0;
  const vid = (i) => reels[i] && $('video', reels[i]);
  const bar = (i) => reels[i] && $('.reel-progress', reels[i]);

  function load(v) { if (v && !v.getAttribute('src') && v.dataset.src) { v.src = v.dataset.src; v.load(); } }
  function alignTo(i, instant) {
    if (!track || !reels[i]) return;
    const tr = track.getBoundingClientRect();
    const rr = reels[i].getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(track).paddingInlineStart) || 0;
    const delta = rtl ? rr.right - (tr.right - pad) : rr.left - (tr.left + pad);
    if (Math.abs(delta) < 2) return;
    byCode = Date.now();
    track.scrollBy({ left: delta, behavior: instant || reduce ? 'auto' : 'smooth' });
  }
  function play() {
    reels.forEach((r, k) => {
      const v = vid(k);
      if (!v) return;
      if (k === active && inView && autoplay && !theaterOpen) {
        load(v);
        v.muted = true;
        const p = v.play();
        if (p && p.catch) p.catch(() => r.classList.remove('is-buffering'));
      } else if (!v.paused) v.pause();
    });
    if (toggle) {
      toggle.classList.toggle('is-paused', !autoplay);
      toggle.setAttribute('aria-label', autoplay ? toggle.dataset.pause : toggle.dataset.play);
    }
    if (inView && autoplay) { const n = vid((active + 1) % reels.length); if (n) { n.preload = 'auto'; load(n); } }
  }
  function select(i, opts = {}) {
    if (!reels.length) return;
    active = (i + reels.length) % reels.length;
    reels.forEach((r, k) => {
      r.classList.toggle('is-active', k === active);
      const b = bar(k); if (b) b.style.transform = 'scaleX(0)';
      if (k !== active) { const v = vid(k); try { if (v && v.currentTime) v.currentTime = 0; } catch (e) { /* not loaded */ } }
    });
    if (count) count.textContent = String(active + 1);
    if (opts.scroll !== false) alignTo(active, opts.instant);
    play();
  }
  function tick() {
    const v = vid(active); const b = bar(active);
    if (v && b && v.duration) b.style.transform = `scaleX(${Math.min(1, v.currentTime / v.duration).toFixed(4)})`;
    raf = requestAnimationFrame(tick);
  }
  reels.forEach((r, k) => {
    const v = vid(k);
    if (v) {
      v.muted = true;
      v.addEventListener('playing', () => { v.classList.add('is-ready'); r.classList.remove('is-buffering'); });
      v.addEventListener('waiting', () => r.classList.add('is-buffering'));
      v.addEventListener('error', () => { r.classList.remove('is-buffering'); v.removeAttribute('src'); }); // poster stays
      v.addEventListener('ended', () => { if (k === active && autoplay && !theaterOpen) select(active + 1); });
    }
    $('.reel-open', r)?.addEventListener('click', () => { select(k); openTheater(k); });
  });
  $('.js-prev')?.addEventListener('click', () => select(active - 1));
  $('.js-next')?.addEventListener('click', () => select(active + 1));
  toggle?.addEventListener('click', () => { autoplay = !autoplay; play(); });
  if (track) {
    let t;
    track.addEventListener('scroll', () => {
      if (Date.now() - byCode < 700) return;
      clearTimeout(t);
      t = setTimeout(() => {
        const tr = track.getBoundingClientRect();
        const pad = parseFloat(getComputedStyle(track).paddingInlineStart) || 0;
        const edge = rtl ? tr.right - pad : tr.left + pad;
        let best = active; let bestD = Infinity;
        reels.forEach((r, k) => { const rr = r.getBoundingClientRect(); const dd = Math.abs((rtl ? rr.right : rr.left) - edge); if (dd < bestD) { bestD = dd; best = k; } });
        if (best !== active) select(best, { scroll: false });
      }, 120);
    }, { passive: true });
    track.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      select(active + ((e.key === 'ArrowRight') !== rtl ? 1 : -1));
    });
  }
  if (videos) {
    new IntersectionObserver(([e]) => {
      inView = e.isIntersecting;
      if (inView && !raf) tick();
      if (!inView && raf) { cancelAnimationFrame(raf); raf = 0; }
      play();
    }, { threshold: 0.3 }).observe(videos);
  }
  if (reels.length) select(0, { scroll: false });

  let tIndex = 0;
  function theaterLoad(i) {
    tIndex = (i + reels.length) % reels.length;
    const r = reels[tIndex];
    tErr.hidden = true;
    tVideo.poster = r.dataset.poster || '';
    tVideo.src = r.dataset.full;
    const p = tVideo.play();
    if (p && p.catch) p.catch(() => {}); // autoplay with sound may be refused; controls are visible
  }
  function openTheater(i) {
    if (!theater || typeof theater.showModal !== 'function') { window.open(reels[i].dataset.full, '_blank', 'noopener'); return; }
    theaterOpen = true;
    play();
    theater.showModal();
    theaterLoad(i);
  }
  if (theater && tVideo) {
    $('.theater-close', theater).addEventListener('click', () => theater.close());
    $('.theater-prev', theater).addEventListener('click', () => theaterLoad(tIndex - 1));
    $('.theater-next', theater).addEventListener('click', () => theaterLoad(tIndex + 1));
    theater.addEventListener('click', (e) => { if (e.target === theater || e.target.classList.contains('theater-in')) theater.close(); });
    tVideo.addEventListener('error', () => { if (tVideo.getAttribute('src')) tErr.hidden = false; });
    tVideo.addEventListener('ended', () => theaterLoad(tIndex + 1));
    theater.addEventListener('close', () => {
      tVideo.pause(); tVideo.removeAttribute('src'); tVideo.load();
      theaterOpen = false;
      select(tIndex);
      reels[tIndex] && $('.reel-open', reels[tIndex])?.focus({ preventScroll: true });
    });
  }

  /* ------------------------------------------------------------------------
     The staff: five gold lines that answer a hand or a cursor. They sleep
     when nothing touches them, so the page costs nothing at rest.
     ------------------------------------------------------------------------ */
  const canvas = $('.staff');
  const staff = canvas && canvas.getContext ? Staff(canvas) : null;
  function Staff(cv) {
    const ctx = cv.getContext('2d');
    const N = 5; const P = 72;
    let w = 0; let h = 0; let lines = []; let grad = null;
    let px = -1; let py = -1; let running = false; let raf2 = 0; let quiet = 0;
    let cy = 0; let gap = 12;
    // the name sits on the staff: centre the five lines on the lower half of the H1
    const base = (i, x) => cy + (i - (N - 1) / 2) * gap + Math.sin((x / w) * Math.PI * 1.1 - 0.45) * h * 0.035;
    function size() {
      const r = cv.getBoundingClientRect();
      if (!r.width) return;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      const name = $('.hero-name');
      const nr = name ? name.getBoundingClientRect() : null;
      gap = Math.max(8, Math.min(15, h * 0.016));
      cy = nr && nr.height ? nr.top - r.top + nr.height * 0.78 : h * 0.55;
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      grad = ctx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, 'rgba(201,163,79,0)');
      grad.addColorStop(0.2, 'rgba(201,163,79,.5)');
      grad.addColorStop(0.8, 'rgba(201,163,79,.5)');
      grad.addColorStop(1, 'rgba(201,163,79,0)');
      lines = Array.from({ length: N }, () => ({ y: new Float32Array(P), v: new Float32Array(P) }));
      draw();
    }
    function draw() {
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = grad; ctx.lineWidth = 1;
      for (let i = 0; i < N; i++) {
        const L = lines[i];
        ctx.beginPath();
        for (let j = 0; j < P; j++) { const x = (j / (P - 1)) * w; const y = base(i, x) + L.y[j]; if (j) ctx.lineTo(x, y); else ctx.moveTo(x, y); }
        ctx.stroke();
      }
    }
    function step() {
      let energy = 0;
      for (const L of lines) {
        for (let s = 0; s < 2; s++) {
          for (let j = 1; j < P - 1; j++) L.v[j] = (L.v[j] + 0.3 * (L.y[j - 1] + L.y[j + 1] - 2 * L.y[j])) * 0.982;
          for (let j = 1; j < P - 1; j++) { L.y[j] += L.v[j]; energy += Math.abs(L.v[j]); }
        }
      }
      return energy;
    }
    function loop() {
      const e = step(); draw();
      quiet = e < 0.05 ? quiet + 1 : 0;
      if (quiet > 30) { running = false; lines.forEach((L) => { L.y.fill(0); L.v.fill(0); }); draw(); return; }
      raf2 = requestAnimationFrame(loop);
    }
    function wake() { if (!running) { running = true; quiet = 0; raf2 = requestAnimationFrame(loop); } }
    function pluck(i, x, f) {
      const L = lines[i]; const j = Math.round((x / w) * (P - 1));
      for (let k = -4; k <= 4; k++) { const q = j + k; if (q > 0 && q < P - 1) L.v[q] += f * Math.exp(-(k * k) / 6); }
      wake();
    }
    function move(cx, cy) {
      const r = cv.getBoundingClientRect(); const x = cx - r.left; const y = cy - r.top;
      if (px >= 0 && x >= 0 && x <= w) {
        for (let i = 0; i < N; i++) {
          const a = py - base(i, px); const b = y - base(i, x);
          if (a * b < 0) pluck(i, x, Math.max(-14, Math.min(14, (y - py) * 0.7)) + (y > py ? 1.5 : -1.5));
        }
      }
      px = x; py = y;
    }
    size();
    return { size, move, leave() { px = -1; py = -1; }, stop() { cancelAnimationFrame(raf2); running = false; } };
  }
  if (staff) {
    let heroVisible = true;
    new IntersectionObserver(([e]) => { heroVisible = e.isIntersecting; if (!heroVisible) staff.stop(); }).observe(canvas);
    if (motion) {
      addEventListener('pointermove', (e) => { if (heroVisible && e.pointerType === 'mouse') staff.move(e.clientX, e.clientY); }, { passive: true });
      addEventListener('touchmove', (e) => { const t = e.touches[0]; if (heroVisible && t) staff.move(t.clientX, t.clientY); }, { passive: true });
      addEventListener('touchend', () => staff.leave(), { passive: true });
    }
    addEventListener('resize', debounce(() => staff.size(), 150));
    if (d.fonts && d.fonts.ready) d.fonts.ready.then(() => setTimeout(() => staff.size(), 950));
  }

  /* ------------------------------------------------------------------------
     Scrubbed scenes (motion only)
     ------------------------------------------------------------------------ */
  if (motion) {
    // Hero: the copy steps back and the stage photograph rises like a curtain
    const copy = $('.hero-copy');
    const photo = $('.hero-photo');
    const pimg = $('.hero-photo img');
    const moment = $$('.moment > span');
    let lastP = -1;
    scrub(hero, (r, vh) => {
      const p = clamp(-r.top / Math.max(1, r.height - vh));
      if (Math.abs(p - lastP) < 0.0005) return;
      lastP = p;
      const c = easeOut(range(p, 0, 0.36));
      copy.style.opacity = String(1 - c);
      copy.style.transform = `translate3d(0, ${-5 * c}vh, 0) scale(${1 - 0.05 * c})`;
      canvas.style.opacity = String(1 - range(p, 0.04, 0.32));
      let top; let side; let bottom;
      if (p < 0.48) { const t = easeOut(range(p, 0.04, 0.48)); top = lerp(100, 18, t); side = lerp(34, 18, t); bottom = lerp(0, 12, t); }
      else { const t = easeInOut(range(p, 0.48, 0.8)); top = lerp(18, 0, t); side = lerp(18, 0, t); bottom = lerp(12, 0, t); }
      photo.style.clipPath = `inset(${top.toFixed(2)}% ${side.toFixed(2)}% ${bottom.toFixed(2)}% ${side.toFixed(2)}%)`;
      pimg.style.transform = `scale(${lerp(1.35, 1, easeOut(range(p, 0.04, 0.84))).toFixed(4)})`;
      moment.forEach((m, i) => {
        const q = easeOut(range(p, 0.78 + i * 0.05, 0.92 + i * 0.05));
        m.style.opacity = String(q);
        m.style.transform = `translate3d(0, ${((1 - q) * 40).toFixed(1)}%, 0)`;
      });
      nav.classList.toggle('show-brand', p > 0.3);
    });
    new IntersectionObserver(([e]) => { if (!e.isIntersecting && e.boundingClientRect.top < 0) nav.classList.add('show-brand'); }).observe(hero);

    // Manifesto: words come up to full strength as they are read
    const fill = $('[data-fill]');
    if (fill) {
      const words = [];
      fill.childNodes.forEach((n) => {
        if (n.nodeType !== 3) return;
        const frag = d.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach((part) => {
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.appendChild(d.createTextNode(part)); return; }
          const s = d.createElement('span'); s.className = 'w'; s.textContent = part; frag.appendChild(s); words.push(s);
        });
        n.replaceWith(frag);
      });
      let lit = -1;
      scrub(fill, (r, vh) => {
        const p = clamp((vh * 0.82 - r.top) / (r.height + vh * 0.32));
        const n = Math.round(p * words.length);
        if (n === lit) return;
        words.forEach((w, i) => w.classList.toggle('on', i < n));
        lit = n;
      });
    }

    // On stage: the wide shot opens to the full width as it arrives
    const frame = $('.stage-frame');
    const fimg = frame && $('img', frame);
    const narrow = matchMedia('(max-width: 760px)');
    scrub(frame, (r, vh) => {
      const t = easeOut(clamp((vh - r.top) / (vh * 0.85)));
      const inset = lerp(narrow.matches ? 4 : 6, 0, t);
      frame.style.clipPath = `inset(0 ${inset.toFixed(2)}%)`;
      fimg.style.transform = `scale(${lerp(1.1, 1, t).toFixed(4)})`;
    });

    // Everything else: a quiet arrival, once
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -8% 0px' });
    $$('[data-reveal]').forEach((el) => io.observe(el));

    queue();
  }

  function debounce(fn, ms) { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; }
})();
