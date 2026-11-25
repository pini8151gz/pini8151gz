/* ==========================================================================
   Benny Laufer — motion & interaction
   - Works without GSAP/Lenis (static, fully usable page).
   - Honors prefers-reduced-motion.
   ========================================================================== */
(() => {
  'use strict';

  const d = document;
  const html = d.documentElement;
  const BL = window.BL || {};
  const $ = (s, c = d) => c.querySelector(s);
  const $$ = (s, c = d) => Array.from(c.querySelectorAll(s));
  const rtl = html.dir === 'rtl';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  const hasGsap = !!(window.gsap && window.ScrollTrigger);
  const motion = html.classList.contains('fx') && hasGsap && !reduce;

  if (!motion) { html.classList.remove('fx'); html.classList.add('no-motion'); }
  html.classList.add('ready');

  let lenis = null;
  const stopScroll = () => { if (lenis) lenis.stop(); };
  const startScroll = () => { if (lenis) lenis.start(); };

  const yr = $('#yr');
  if (yr) yr.textContent = String(new Date().getFullYear());

  /* ------------------------------------------------------------------------
     Split helpers
     ------------------------------------------------------------------------ */
  function splitWords(el, masked) {
    const words = [];
    const walk = (node) => {
      Array.from(node.childNodes).forEach((n) => {
        if (n.nodeType === 3) {
          const frag = d.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach((part) => {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(d.createTextNode(part)); return; }
            const w = d.createElement('span');
            w.className = 'w';
            w.textContent = part;
            if (masked) {
              const m = d.createElement('span');
              m.className = 'wm';
              m.appendChild(w);
              frag.appendChild(m);
            } else {
              frag.appendChild(w);
            }
            words.push(w);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.tagName !== 'BR') {
          walk(n);
        }
      });
    };
    walk(el);
    return words;
  }

  /* ------------------------------------------------------------------------
     WhatsApp composer (live message preview)
     ------------------------------------------------------------------------ */
  const form = $('#inq');
  const waText = $('#waText');
  const fDate = $('#fDate');
  const fPlace = $('#fPlace');
  const bubble = $('.bubble');

  function fmtDate(v) {
    if (!v) return BL.tbd;
    const p = v.split('-').map(Number);
    if (p.length !== 3 || p.some(isNaN)) return v;
    try {
      return new Date(p[0], p[1] - 1, p[2]).toLocaleDateString(BL.locale || undefined, { day: 'numeric', month: 'long', year: 'numeric' });
    } catch (e) { return v; }
  }
  function compose() {
    const checked = form && form.querySelector('input[name="type"]:checked');
    const key = checked ? checked.value : 'o1';
    return String(BL.text || '')
      .replace('{type}', (BL.types || {})[key] || '')
      .replace('{date}', fmtDate(fDate ? fDate.value : ''))
      .replace('{place}', (fPlace && fPlace.value.trim()) || BL.tbd);
  }
  let bumpT;
  function updateWa(bump) {
    const msg = compose();
    if (waText) waText.textContent = msg;
    const url = 'https://wa.me/' + (BL.wa || '') + '?text=' + encodeURIComponent(msg);
    $$('.js-wa').forEach((a) => { a.href = url; });
    if (bump && bubble) {
      bubble.classList.add('bump');
      clearTimeout(bumpT);
      bumpT = setTimeout(() => bubble.classList.remove('bump'), 160);
    }
  }
  if (form) {
    form.addEventListener('input', () => updateWa(true));
    form.addEventListener('change', () => updateWa(true));
    form.addEventListener('submit', (e) => e.preventDefault());
  }
  updateWa(false);

  /* ------------------------------------------------------------------------
     Mobile menu
     ------------------------------------------------------------------------ */
  const nav = $('#nav');
  const burger = $('.burger');
  const menu = $('#menu');
  function openMenu() {
    if (!menu) return;
    menu.hidden = false;
    burger.setAttribute('aria-expanded', 'true');
    html.classList.add('menu-open');
    stopScroll();
    if (motion) {
      gsap.fromTo(menu, { opacity: 0 }, { opacity: 1, duration: .45, ease: 'power2.out' });
      gsap.fromTo($$('.menu-links a span'), { yPercent: 110 }, { yPercent: 0, duration: 1.1, stagger: .06, ease: 'expo.out' });
      gsap.fromTo('.menu-foot', { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: .9, delay: .25, ease: 'expo.out' });
    }
    const first = $('.menu-links a');
    if (first) first.focus({ preventScroll: true });
  }
  function closeMenu() {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    burger.setAttribute('aria-expanded', 'false');
    html.classList.remove('menu-open');
    startScroll();
  }
  if (burger) burger.addEventListener('click', () => (menu.hidden ? openMenu() : closeMenu()));
  d.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });

  /* ------------------------------------------------------------------------
     Video stage: every card is a real player. The active film plays muted
     as soon as the section is on screen (phones allow that), sound is one tap
     away, and if a phone refuses autoplay (e.g. iPhone Low Power Mode) a
     play button takes over instead of a frozen picture.
     ------------------------------------------------------------------------ */
  const reels = $$('.reel');
  const track = $('.reels-track');
  const dots = $$('.dot');
  const reelsSec = $('#videos');
  const VL = reelsSec ? reelsSec.dataset : {};
  const canSetVolume = (() => { try { const t = d.createElement('video'); t.volume = 0.5; return Math.abs(t.volume - 0.5) < 0.01; } catch (e) { return false; } })();
  html.classList.toggle('no-volume', !canSetVolume);
  let active = 0;
  let inView = false;
  let wantSound = false;   // once the visitor turns sound on, the next films keep it
  let userPaused = false;  // an explicit pause wins until they press play again
  let byCode = 0;
  let rafId = 0;
  const vidOf = (i) => reels[i] && $('video', reels[i]);

  function load(v, how) {
    if (!v) return;
    if (!v.getAttribute('src') && v.dataset.src) { v.preload = how || 'auto'; v.src = v.dataset.src; }
    else if (how === 'auto' && v.preload !== 'auto') v.preload = 'auto';
  }
  function centerReel(i, instant) {
    if (!track || !reels[i]) return;
    const tr = track.getBoundingClientRect();
    const rr = reels[i].getBoundingClientRect();
    const delta = (rr.left + rr.width / 2) - (tr.left + tr.width / 2);
    if (Math.abs(delta) < 2) return;
    byCode = Date.now();
    track.scrollBy({ left: delta, behavior: instant || reduce ? 'auto' : 'smooth' });
  }
  function paint(i) {
    const r = reels[i]; const v = vidOf(i);
    if (!r || !v) return;
    const muted = v.muted || v.volume === 0;
    r.classList.toggle('is-playing', !v.paused);
    r.classList.toggle('is-muted', muted);
    $('.pc-play', r).setAttribute('aria-label', v.paused ? VL.play : VL.pause);
    $('.pc-surface', r).setAttribute('aria-label', v.paused ? VL.play : (muted ? VL.unmute : VL.pause));
    const mb = $('.pc-mute', r);
    mb.setAttribute('aria-pressed', String(!muted));
    mb.setAttribute('aria-label', muted ? VL.unmute : VL.mute);
    const vol = $('.pc-vol', r);
    if (vol && d.activeElement !== vol) { vol.value = muted ? 0 : v.volume; vol.style.setProperty('--p', (muted ? 0 : v.volume * 100) + '%'); }
  }
  async function start(i, opts = {}) {
    const v = vidOf(i); const r = reels[i];
    if (!v) return;
    const sound = opts.sound ?? wantSound;
    load(v, 'auto');
    v.muted = !sound;
    if (sound && v.volume < 0.05) v.volume = 1;
    try {
      await v.play();
      r.classList.remove('is-blocked');
    } catch (e) {
      if (sound && !opts.gesture) {
        // sound needs a tap on this browser: keep playing, quietly
        v.muted = true;
        try { await v.play(); } catch (e2) { r.classList.add('is-blocked'); }
      } else {
        r.classList.add('is-blocked'); // autoplay refused: the big play button stays up
      }
    }
    paint(i);
  }
  function sync() {
    reels.forEach((r, k) => { const v = vidOf(k); if (v && k !== active && !v.paused) v.pause(); });
    const v = vidOf(active);
    if (!v) return;
    if (inView && !userPaused) start(active);
    else if (!v.paused) v.pause();
    if (inView) load(vidOf((active + 1) % reels.length), 'metadata'); // the next film is ready to go
  }
  function select(i, opts = {}) {
    if (!reels.length) return;
    const prev = active;
    active = (i + reels.length) % reels.length;
    reels.forEach((r, k) => {
      const on = k === active;
      r.classList.toggle('is-active', on);
      $('.pc', r).inert = !on;
      $('.reel-select', r).tabIndex = on ? -1 : 0;
    });
    dots.forEach((dt, k) => {
      dt.classList.toggle('is-active', k === active);
      dt.setAttribute('aria-current', k === active ? 'true' : 'false');
      const bar = $('i', dt); if (bar) bar.style.transform = 'scaleX(0)';
    });
    if (prev !== active) { const pv = vidOf(prev); if (pv) { pv.pause(); try { if (pv.currentTime) pv.currentTime = 0; } catch (e) { /* not loaded */ } } }
    if (opts.scroll !== false) centerReel(active, opts.instant);
    if (opts.play !== false) sync();
  }
  function tick() {
    const v = vidOf(active); const r = reels[active];
    if (v && r && v.duration) {
      const p = v.currentTime / v.duration;
      const seek = $('.pc-seek', r);
      if (seek && d.activeElement !== seek) { seek.value = String(Math.round(p * 1000)); seek.style.setProperty('--p', (p * 100).toFixed(2) + '%'); }
      const bar = dots[active] && $('i', dots[active]);
      if (bar) bar.style.transform = `scaleX(${p.toFixed(4)})`;
    }
    rafId = requestAnimationFrame(tick);
  }
  function unmute(k) {
    const v = vidOf(k);
    wantSound = true; userPaused = false;
    v.muted = false;
    if (v.volume < 0.05) v.volume = 1;
    if (v.paused) start(k, { sound: true, gesture: true });
    paint(k);
  }

  reels.forEach((r, k) => {
    const v = vidOf(k);
    if (!v) return;
    ['play', 'pause', 'volumechange'].forEach((ev) => v.addEventListener(ev, () => paint(k)));
    v.addEventListener('playing', () => { r.classList.add('is-ready'); r.classList.remove('is-buffering', 'is-blocked'); $('.pc-error', r).hidden = true; });
    v.addEventListener('waiting', () => { if (k === active) r.classList.add('is-buffering'); });
    v.addEventListener('canplay', () => r.classList.remove('is-buffering'));
    v.addEventListener('error', () => { if (!v.getAttribute('src')) return; r.classList.remove('is-buffering'); $('.pc-error', r).hidden = false; });
    v.addEventListener('ended', () => { if (k === active) select(active + 1); });

    $('.reel-select', r).addEventListener('click', () => { userPaused = false; select(k); });
    $('.pc-surface', r).addEventListener('click', () => {
      if (v.paused) { userPaused = false; wantSound = true; start(k, { sound: true, gesture: true }); }
      else if (v.muted || v.volume === 0) unmute(k);
      else { userPaused = true; v.pause(); }
    });
    $('.pc-sound', r).addEventListener('click', () => unmute(k));
    $('.pc-play', r).addEventListener('click', () => {
      if (v.paused) { userPaused = false; start(k, { sound: !v.muted, gesture: true }); }
      else { userPaused = true; v.pause(); }
    });
    $('.pc-mute', r).addEventListener('click', () => {
      if (v.muted || v.volume === 0) unmute(k);
      else { v.muted = true; wantSound = false; paint(k); }
    });
    const vol = $('.pc-vol', r);
    vol.addEventListener('input', () => {
      const x = Number(vol.value);
      v.volume = x; v.muted = x === 0; wantSound = x > 0;
      vol.style.setProperty('--p', (x * 100) + '%');
      if (x > 0 && v.paused) start(k, { sound: true, gesture: true });
    });
    const seek = $('.pc-seek', r);
    seek.addEventListener('input', () => {
      if (v.duration) v.currentTime = (Number(seek.value) / 1000) * v.duration;
      seek.style.setProperty('--p', (Number(seek.value) / 10) + '%');
    });
    $('.pc-full', r).addEventListener('click', () => {
      if (v.requestFullscreen) { v.controls = true; v.requestFullscreen().catch(() => { v.controls = false; }); }
      else if (v.webkitEnterFullscreen) { load(v, 'auto'); v.webkitEnterFullscreen(); } // iPhone
    });
  });
  d.addEventListener('fullscreenchange', () => { if (!d.fullscreenElement) reels.forEach((r, k) => { const v = vidOf(k); if (v) v.controls = false; }); });

  dots.forEach((dt, k) => dt.addEventListener('click', () => { userPaused = false; select(k); }));
  const prevBtn = $('.reels-prev');
  const nextBtn = $('.reels-next');
  if (prevBtn) prevBtn.addEventListener('click', () => { userPaused = false; select(active - 1); });
  if (nextBtn) nextBtn.addEventListener('click', () => { userPaused = false; select(active + 1); });

  if (track) {
    let t;
    track.addEventListener('scroll', () => {
      if (Date.now() - byCode < 700) return;
      clearTimeout(t);
      t = setTimeout(() => {
        const tr = track.getBoundingClientRect();
        const mid = tr.left + tr.width / 2;
        let best = active; let bestD = Infinity;
        reels.forEach((r, k) => { const rr = r.getBoundingClientRect(); const dd = Math.abs(rr.left + rr.width / 2 - mid); if (dd < bestD) { bestD = dd; best = k; } });
        if (best !== active) { userPaused = false; select(best, { scroll: false }); }
      }, 120);
    }, { passive: true });
    track.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      if (e.target.matches('input[type="range"]')) return;
      e.preventDefault();
      userPaused = false;
      select(active + ((e.key === 'ArrowRight') !== rtl ? 1 : -1));
    });
  }

  if (reelsSec && 'IntersectionObserver' in window) {
    new IntersectionObserver(([e]) => {
      inView = e.isIntersecting;
      if (inView && !rafId) tick();
      if (!inView && rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      if (inView) sync(); else { const v = vidOf(active); if (v && !v.paused) v.pause(); }
    }, { threshold: 0.35 }).observe(reelsSec);
  }
  d.addEventListener('visibilitychange', () => { if (d.hidden) { const v = vidOf(active); if (v && !v.paused) v.pause(); } else if (inView) sync(); });
  if (reels.length) select(0, { scroll: false, play: false });

  /* ------------------------------------------------------------------------
     Hero strings: five gold staff lines you can pluck
     ------------------------------------------------------------------------ */
  function Strings(canvas) {
    const ctx = canvas.getContext('2d');
    const N = 5, P = 84;
    let w = 0, h = 0, dpr = 1, grad = null, lines = [], motes = [];
    let running = false, raf = 0, t0 = performance.now(), lastPluck = 0;
    let px = -1, py = -1;
    let scrollKick = 0;

    function baseY(i, x) {
      const u = x / w;
      const gap = Math.max(9, Math.min(17, h * .019));
      const cy = h * .56 + (i - (N - 1) / 2) * gap;
      return cy + Math.sin(u * Math.PI * 1.1 - .45) * h * .065;
    }
    function resize() {
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      grad = ctx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, 'rgba(201,165,72,0)');
      grad.addColorStop(.18, 'rgba(201,165,72,.85)');
      grad.addColorStop(.5, 'rgba(246,231,176,1)');
      grad.addColorStop(.82, 'rgba(201,165,72,.85)');
      grad.addColorStop(1, 'rgba(201,165,72,0)');
      lines = Array.from({ length: N }, () => ({ y: new Float32Array(P), v: new Float32Array(P) }));
      const count = Math.round(Math.min(70, w / 22));
      motes = Array.from({ length: count }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        r: Math.random() * 1.3 + .3, s: Math.random() * .25 + .06,
        a: Math.random() * .5 + .15, ph: Math.random() * Math.PI * 2,
      }));
    }
    function pluck(i, x, force) {
      const L = lines[i];
      if (!L) return;
      const j = Math.round((x / w) * (P - 1));
      for (let k = -5; k <= 5; k++) {
        const q = j + k;
        if (q <= 0 || q >= P - 1) continue;
        L.v[q] += force * Math.exp(-(k * k) / 8);
      }
    }
    function disp(i, x) {
      const L = lines[i];
      const j = Math.max(0, Math.min(P - 1, Math.round((x / w) * (P - 1))));
      return L ? L.y[j] : 0;
    }
    function move(x, y) {
      if (px < 0) { px = x; py = y; return; }
      for (let i = 0; i < N; i++) {
        const s0 = py - (baseY(i, px) + disp(i, px));
        const s1 = y - (baseY(i, x) + disp(i, x));
        if (s0 * s1 < 0) {
          const vy = Math.max(-26, Math.min(26, y - py));
          pluck(i, x, vy * .9 + (vy >= 0 ? 2 : -2));
        }
      }
      px = x; py = y;
    }
    function step() {
      const k = .3, damp = .986;
      for (let n = 0; n < N; n++) {
        const L = lines[n];
        for (let s = 0; s < 2; s++) {
          for (let j = 1; j < P - 1; j++) L.v[j] = (L.v[j] + k * (L.y[j - 1] + L.y[j + 1] - 2 * L.y[j])) * damp;
          for (let j = 1; j < P - 1; j++) L.y[j] += L.v[j];
        }
      }
    }
    function draw(time) {
      ctx.clearRect(0, 0, w, h);
      const t = time * .001;
      // drifting dust in the light
      for (const m of motes) {
        const tw = .5 + .5 * Math.sin(t * 1.3 + m.ph);
        ctx.globalAlpha = m.a * tw;
        ctx.fillStyle = '#f3dfa0';
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, 6.283);
        ctx.fill();
      }
      ctx.lineCap = 'round';
      for (let i = 0; i < N; i++) {
        const L = lines[i];
        let energy = 0;
        ctx.beginPath();
        for (let j = 0; j < P; j++) {
          const x = (j / (P - 1)) * w;
          const amb = Math.sin(t * .9 + j * .16 + i * .8) * 1.1;
          const y = baseY(i, x) + L.y[j] + amb;
          energy += Math.abs(L.v[j]);
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = grad;
        ctx.globalAlpha = .42;
        ctx.lineWidth = 1;
        ctx.stroke();
        if (energy > 1.5) {
          ctx.globalAlpha = Math.min(.32, energy * .006);
          ctx.lineWidth = 3.5;
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }
    function frame(now) {
      const dt = Math.min(64, now - t0); t0 = now;
      for (const m of motes) {
        m.y -= m.s * dt * .06;
        m.x += Math.sin(now * .0004 + m.ph) * .08;
        if (m.y < -4) { m.y = h + 4; m.x = Math.random() * w; }
      }
      // the strings breathe on their own, like a quiet tuning
      if (now - lastPluck > 2600) {
        lastPluck = now;
        pluck(Math.floor(Math.random() * N), w * (.15 + Math.random() * .7), (Math.random() - .5) * 9);
      }
      if (Math.abs(scrollKick) > .5) {
        pluck(Math.floor(Math.random() * N), Math.random() * w, Math.max(-6, Math.min(6, scrollKick * .25)));
        scrollKick *= .8;
      }
      step();
      draw(now);
      raf = requestAnimationFrame(frame);
    }
    function start() { if (running) return; running = true; t0 = performance.now(); raf = requestAnimationFrame(frame); }
    function stop() { running = false; cancelAnimationFrame(raf); }
    resize();
    return {
      resize, start, stop,
      move(cx, cy) { const r = canvas.getBoundingClientRect(); move(cx - r.left, cy - r.top); },
      leave() { px = -1; py = -1; },
      kick(v) { scrollKick = v; },
      still() { resize(); draw(0); },
    };
  }

  const canvas = $('.strings');
  const strings = canvas && canvas.getContext ? Strings(canvas) : null;

  /* ------------------------------------------------------------------------
     No-motion path: everything visible, simple helpers, done.
     ------------------------------------------------------------------------ */
  if (!motion) {
    if (strings) { strings.still(); window.addEventListener('resize', () => strings.still()); }
    const dock = $('#dock');
    const contact = $('#contact');
    const hero = $('.hero');
    if (dock && 'IntersectionObserver' in window) {
      let heroIn = true, contactIn = false, stageIn = false;
      const upd = () => dock.classList.toggle('is-visible', !heroIn && !contactIn && !stageIn);
      new IntersectionObserver((e) => { heroIn = e[0].isIntersecting; upd(); }).observe(hero);
      new IntersectionObserver((e) => { contactIn = e[0].isIntersecting; upd(); }).observe(contact);
      // the bar steps aside while the films are on screen so it never covers their controls
      new IntersectionObserver((e) => { stageIn = e[0].isIntersecting; upd(); }).observe($('.reels'));
    }
    return;
  }

  /* ==========================================================================
     MOTION
     ========================================================================== */
  gsap.registerPlugin(ScrollTrigger);
  ScrollTrigger.config({ ignoreMobileResize: true });

  // Smooth scrolling (wheel only; touch stays native)
  if (window.Lenis) {
    lenis = new window.Lenis({ lerp: .085, smoothWheel: true, wheelMultiplier: 1 });
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((t) => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }

  // In-page anchors glide
  d.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const id = a.getAttribute('href');
    if (!id || id === '#') return;
    const target = id === '#top' ? 0 : $(id);
    if (target === null) return;
    e.preventDefault();
    closeMenu();
    if (lenis) lenis.scrollTo(target, { duration: 1.8, easing: (x) => 1 - Math.pow(1 - x, 4) });
    else if (target === 0) window.scrollTo({ top: 0, behavior: 'smooth' });
    else target.scrollIntoView({ behavior: 'smooth' });
    if (target !== 0) { target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true }); }
  });

  /* ---------- Hero: overture ---------- */
  const monoPath = $('.hero-mono path');
  gsap.set($$('.hero-content > *'), { opacity: 1 });
  gsap.set('.scroll-cue', { opacity: 1 });
  let monoLen = 0;
  try { monoLen = monoPath.getTotalLength(); } catch (e) { monoLen = 0; }

  const intro = gsap.timeline({ delay: .1, defaults: { ease: 'expo.out' } });
  intro.from('.beams', { opacity: 0, duration: 3, ease: 'power2.out' }, 0);
  intro.from('.strings', { opacity: 0, duration: 2.4, ease: 'power2.out' }, .4);
  if (monoLen) {
    gsap.set(monoPath, { strokeDasharray: monoLen, strokeDashoffset: monoLen, strokeWidth: 18, fillOpacity: 0 });
    intro
      .to(monoPath, { strokeDashoffset: 0, duration: 2.2, ease: 'power2.inOut' }, .05)
      .to(monoPath, { fillOpacity: 1, duration: 1.3, ease: 'power2.out' }, 1.4)
      .to(monoPath, { strokeWidth: 0, duration: 1, ease: 'power2.out' }, 1.75);
  }
  intro
    .from('.hero-mono', { scale: .9, duration: 2.4 }, 0)
    .from('.hero-title .li', { yPercent: 115, duration: 1.7, stagger: .13 }, .55)
    .from('.hero-eyebrow', { opacity: 0, y: 18, duration: 1.3 }, .9)
    .from(['.hero-latin', '.hero-lead'], { opacity: 0, y: 22, duration: 1.4, stagger: .1 }, 1.05)
    .from('.hero-ctas > *', { opacity: 0, y: 26, duration: 1.4, stagger: .09 }, 1.2)
    .from(['.scroll-cue span', '.scroll-cue i'], { opacity: 0, duration: 1.2 }, 1.9);

  // Scroll: the hero opens into the stage photo
  const heroTl = gsap.timeline({
    scrollTrigger: {
      trigger: '.hero', start: 'top top',
      end: () => '+=' + Math.round(window.innerHeight * 1.7),
      pin: true, scrub: 1, anticipatePin: 1, invalidateOnRefresh: true,
    },
  });
  heroTl
    .to('.hero-content', { yPercent: -10, scale: .9, opacity: 0, ease: 'power1.in', duration: .4 }, 0)
    .to('.scroll-cue', { opacity: 0, duration: .08 }, 0)
    .to('.hero-stage', { opacity: 0, duration: .5 }, .1)
    .fromTo('.hero-photo', { clipPath: 'inset(100% 36% 0% 36% round 32px)' }, { clipPath: 'inset(22% 21% 14% 21% round 32px)', ease: 'power2.out', duration: .42 }, .04)
    .to('.hero-photo', { clipPath: 'inset(0% 0% 0% 0% round 0px)', ease: 'power2.inOut', duration: .4 }, .46)
    .fromTo('.hero-photo img', { scale: 1.5, yPercent: 5 }, { scale: 1, yPercent: 0, ease: 'power2.out', duration: .86 }, .04)
    .from('.moment .line > span', { yPercent: 112, duration: .2, stagger: .07, ease: 'power3.out' }, .72)
    .to({}, { duration: .12 });

  // Strings: run only while the hero is on screen
  if (strings) {
    let heroVisible = true;
    ScrollTrigger.create({
      trigger: '.hero', start: 'top bottom', end: () => '+=' + Math.round(window.innerHeight * 1.9),
      onToggle: (s) => { heroVisible = s.isActive; heroVisible && !d.hidden ? strings.start() : strings.stop(); },
    });
    d.addEventListener('visibilitychange', () => (d.hidden || !heroVisible ? strings.stop() : strings.start()));
    window.addEventListener('pointermove', (e) => { if (heroVisible) strings.move(e.clientX, e.clientY); }, { passive: true });
    window.addEventListener('touchmove', (e) => { if (heroVisible && e.touches[0]) strings.move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
    window.addEventListener('touchend', () => strings.leave(), { passive: true });
    d.addEventListener('pointerleave', () => strings.leave());
    let rT;
    window.addEventListener('resize', () => { clearTimeout(rT); rT = setTimeout(() => strings.resize(), 150); });
    if (lenis) lenis.on('scroll', (l) => { if (heroVisible) strings.kick(l.velocity); });
    strings.start();
  }

  /* ---------- Header: glass, hide on scroll down, theme on ivory ---------- */
  const progress = $('.progress span');
  let lastY = 0;
  ScrollTrigger.create({
    start: 0, end: 'max',
    onUpdate: (self) => {
      const y = self.scroll();
      nav.classList.toggle('is-scrolled', y > 30);
      if (!html.classList.contains('menu-open')) {
        if (y > lastY + 6 && y > window.innerHeight * .9) nav.classList.add('is-hidden');
        else if (y < lastY - 6 || y < 60) nav.classList.remove('is-hidden');
      }
      lastY = y;
      if (progress) progress.style.transform = 'scaleX(' + self.progress.toFixed(4) + ')';
    },
  });
  ScrollTrigger.create({
    trigger: '.sheet-light', start: 'top 32px', endTrigger: '.sheet-dark', end: 'top 32px',
    toggleClass: { targets: nav, className: 'on-light' },
  });
  // active nav link
  const navLinks = $$('.nav-links a');
  ['#about', '#videos', '#services', '#contact'].forEach((id) => {
    const sec = $(id);
    if (!sec) return;
    ScrollTrigger.create({
      trigger: sec, start: 'top 50%', end: 'bottom 50%',
      onToggle: (s) => navLinks.forEach((a) => {
        if (a.getAttribute('href') === id) a.setAttribute('aria-current', s.isActive ? 'true' : 'false');
      }),
    });
  });

  /* ---------- Mobile dock ---------- */
  const dock = $('#dock');
  if (dock) {
    let pastHero = false, atContact = false, stageIn = false;
    const upd = () => dock.classList.toggle('is-visible', pastHero && !atContact && !stageIn);
    // the bar steps aside while the films are on screen so it never covers their controls
    const stage = $('.reels');
    if (stage) new IntersectionObserver(([e]) => { stageIn = e.isIntersecting; upd(); }).observe(stage);
    ScrollTrigger.create({ trigger: '#about', start: 'top bottom', end: 'max', onEnter: () => { pastHero = true; upd(); }, onLeaveBack: () => { pastHero = false; upd(); } });
    ScrollTrigger.create({ trigger: '#contact', start: 'top 85%', end: 'max', onEnter: () => { atContact = true; upd(); }, onLeaveBack: () => { atContact = false; upd(); } });
  }

  /* ---------- Text reveals ---------- */
  $$('[data-split]').forEach((h) => {
    const words = splitWords(h, true);
    gsap.from(words, {
      yPercent: 118, duration: 1.5, stagger: .055, ease: 'expo.out',
      scrollTrigger: { trigger: h, start: 'top 86%', once: true },
    });
  });

  const reveals = $$('[data-reveal]');
  gsap.set(reveals, { opacity: 0, y: 38 });
  ScrollTrigger.batch(reveals, {
    start: 'top 90%', once: true,
    onEnter: (batch) => gsap.to(batch, { opacity: 1, y: 0, duration: 1.4, stagger: .09, ease: 'expo.out', overwrite: true }),
  });

  // Manifesto: words light up as you read
  $$('[data-fill]').forEach((el) => {
    const words = splitWords(el, false);
    gsap.fromTo(words, { opacity: .14 }, {
      opacity: 1, ease: 'none', stagger: .1,
      scrollTrigger: { trigger: el, start: 'top 82%', end: 'bottom 44%', scrub: .5 },
    });
  });

  gsap.from('.roles li', {
    opacity: 0, y: 26, duration: 1.3, stagger: .11, ease: 'expo.out',
    scrollTrigger: { trigger: '.roles', start: 'top 92%', once: true },
  });

  /* ---------- Images ---------- */
  $$('[data-clip]').forEach((f) => {
    const img = $('img', f);
    gsap.timeline({ scrollTrigger: { trigger: f, start: 'top 88%', once: true } })
      .fromTo(f, { clipPath: 'inset(100% 0% 0% 0% round 30px)' }, { clipPath: 'inset(0% 0% 0% 0% round 30px)', duration: 1.7, ease: 'expo.out' })
      .fromTo(img, { scale: 1.35 }, { scale: 1, duration: 2.2, ease: 'expo.out' }, 0);
  });
  $$('[data-parallax]').forEach((f) => {
    gsap.fromTo($('img', f), { yPercent: -6 }, {
      yPercent: 6, ease: 'none',
      scrollTrigger: { trigger: f, start: 'top bottom', end: 'bottom top', scrub: true },
    });
  });

  // On stage: the wide shot opens to full bleed
  const wide = $('.stage-wide');
  if (wide) {
    const small = window.matchMedia('(max-width: 760px)').matches;
    const from = small ? 'inset(0% 4% 0% 4% round 24px)' : 'inset(0% 7% 0% 7% round 36px)';
    const st = { trigger: wide, start: 'top 92%', end: 'top 12%', scrub: true };
    gsap.fromTo(wide, { clipPath: from }, { clipPath: 'inset(0% 0% 0% 0% round 0px)', ease: 'none', scrollTrigger: st });
    gsap.fromTo($('img', wide), { scale: 1.22 }, { scale: 1, ease: 'none', scrollTrigger: { trigger: wide, start: 'top bottom', end: 'bottom top', scrub: true } });
    gsap.from($('figcaption', wide), { opacity: 0, y: 20, duration: 1.2, ease: 'expo.out', scrollTrigger: { trigger: wide, start: 'top 40%', once: true } });
  }

  /* ---------- Marquee: speed follows your scroll ---------- */
  const mq = $('.marquee-track');
  if (mq) {
    const loop = gsap.fromTo(mq, { xPercent: rtl ? -50 : 0 }, { xPercent: rtl ? 0 : -50, duration: 46, ease: 'none', repeat: -1 });
    let dir = 1;
    ScrollTrigger.create({
      trigger: '.marquee', start: 'top bottom', end: 'bottom top',
      onToggle: (s) => (s.isActive ? loop.play() : loop.pause()),
      onUpdate: (s) => {
        dir = s.direction;
        const boost = 1 + Math.min(Math.abs(s.getVelocity()) / 260, 6);
        gsap.to(loop, { timeScale: dir * boost, duration: .2, overwrite: true, onComplete: () => gsap.to(loop, { timeScale: dir, duration: 1.4, ease: 'power2.out' }) });
      },
    });
  }

  /* ---------- Videos: entrance ---------- */
  gsap.from('.reels-track', {
    x: rtl ? -120 : 120, opacity: 0, duration: 1.8, ease: 'expo.out',
    scrollTrigger: { trigger: '.reels', start: 'top 88%', once: true },
  });
  gsap.from('.reels-ui', { opacity: 0, y: 20, duration: 1.2, ease: 'expo.out', scrollTrigger: { trigger: '.reels-ui', start: 'top 95%', once: true } });
  if (reels.length) setTimeout(() => centerReel(0, true), 50);

  /* ---------- Sheets rise like cards ---------- */
  $$('.sheet').forEach((s) => {
    gsap.fromTo($('.sheet-bg', s), { scaleX: .9 }, {
      scaleX: 1, ease: 'none',
      scrollTrigger: { trigger: s, start: 'top bottom', end: 'top 20%', scrub: true },
    });
  });

  /* ---------- Bento ---------- */
  const tiles = $$('.tile');
  gsap.set(tiles, { opacity: 0, y: 60 });
  ScrollTrigger.batch(tiles, {
    start: 'top 90%', once: true,
    onEnter: (b) => gsap.to(b, { opacity: 1, y: 0, duration: 1.5, stagger: .1, ease: 'expo.out', clearProps: 'transform' }),
  });
  $$('.tile svg').forEach((svg) => {
    const paths = $$('path, ellipse, rect', svg);
    paths.forEach((p) => {
      let len = 0;
      try { len = p.getTotalLength(); } catch (e) { len = 0; }
      if (len) gsap.set(p, { strokeDasharray: len, strokeDashoffset: len });
    });
    gsap.to(paths, {
      strokeDashoffset: 0, duration: 2.2, stagger: .12, ease: 'power2.inOut',
      scrollTrigger: { trigger: svg, start: 'top 88%', once: true },
    });
  });

  /* ---------- Process: steps light up, rail fills ---------- */
  $$('.step').forEach((s) => {
    ScrollTrigger.create({ trigger: s, start: 'top 62%', end: 'bottom 38%', toggleClass: 'is-active' });
  });
  gsap.fromTo('.rail i', { scaleY: 0 }, {
    scaleY: 1, ease: 'none',
    scrollTrigger: { trigger: '.steps', start: 'top 62%', end: 'bottom 50%', scrub: true },
  });

  /* ---------- Footer: the logo lockup, written out ---------- */
  const fw = $('.footer-word');
  if (fw) {
    fw.innerHTML = Array.from(fw.textContent).map((c) => '<span class="ch">' + (c === ' ' ? '&nbsp;' : c) + '</span>').join('');
    const ft = gsap.timeline({ scrollTrigger: { trigger: '.footer-mark', start: 'top 85%', once: true } });
    ft.from('.footer-mono', { opacity: 0, y: 30, duration: 1.4, ease: 'expo.out' })
      .from('.footer-word .ch', { yPercent: 70, opacity: 0, duration: 1.5, stagger: .045, ease: 'expo.out' }, .1)
      .fromTo('.baton', { clipPath: 'inset(0% 100% 0% 0%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: 1.8, ease: 'expo.inOut' }, .35);
  }

  /* ---------- Pointer niceties (desktop only) ---------- */
  if (fine) {
    $$('.spot').forEach((el) => {
      el.addEventListener('pointermove', (e) => {
        const r = el.getBoundingClientRect();
        el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
        el.style.setProperty('--my', (e.clientY - r.top) + 'px');
      });
    });
    $$('.magnetic').forEach((el) => {
      const xTo = gsap.quickTo(el, 'x', { duration: .9, ease: 'elastic.out(1, .45)' });
      const yTo = gsap.quickTo(el, 'y', { duration: .9, ease: 'elastic.out(1, .45)' });
      el.addEventListener('pointermove', (e) => {
        const r = el.getBoundingClientRect();
        xTo((e.clientX - (r.left + r.width / 2)) * .22);
        yTo((e.clientY - (r.top + r.height / 2)) * .32);
      });
      el.addEventListener('pointerleave', () => { xTo(0); yTo(0); });
    });
  }

  // Layout settles once webfonts arrive
  if (d.fonts && d.fonts.ready) d.fonts.ready.then(() => ScrollTrigger.refresh());
  window.addEventListener('load', () => ScrollTrigger.refresh());
})();
