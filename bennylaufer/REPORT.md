# Transformation report — bennylaufer

All numbers below are real measurements taken on 24 Nov 2026. Lighthouse 12.8: median of 3 runs. The mobile preset simulates a mid-range phone with 4× CPU slowdown and slow 4G.

## Production (live URLs)

| | Original · bennylaufer.com | New · bennylaufer.vercel.app |
| --- | --- | --- |
| Performance, mobile | 69 | **100** |
| LCP, mobile | 10.5 s | **1.42 s** |
| FCP, mobile | 3.0 s | **0.92 s** |
| Performance, desktop | 83 (LCP 2.4 s) | **100** (LCP 0.37 s) |
| TBT / CLS | 0 / 0 | 0 / 0 |
| Transfer / requests | 2,070 KB / 40 | **244 KB / 14** |
| Accessibility | 100 | 100 |
| Best practices | 93–96 | **100** |
| SEO | 100 | 69 on the preview host only: `noindex` is set on `*.vercel.app` so it doesn't compete with bennylaufer.com. Canonical, title, description and hreflang all pass, and it scores 100 on its own domain (lab). |

## Lab: same server, same conditions (mobile)

| | Original | v1 (first redesign) | v2 (this) |
| --- | --- | --- | --- |
| Performance | 98 | 85 | **100** |
| LCP | 2.33 s | 3.01 s | **1.66 s** |
| TBT | 0 ms | 358 ms | **0 ms** |
| JavaScript | 0 KB | 62 KB | **8 KB** |
| Fonts | 167 KB | 202 KB | **66 KB** |
| Transfer | 836 KB | 437 KB | **242 KB** |
| axe, WCAG 2.2 AA | 0 | 12–14 contrast, 4 target-size | **0** |
| Scroll frames, desktop | 60 fps | 41.6 fps (p95 100 ms) | **60 fps (p95 16.7 ms)** |
| Scroll frames, 4× slower CPU | 60 fps | 53.5 fps (p95 33 ms) | **60 fps (p95 16.8 ms)** |

Scroll frames were measured with a scripted scroll in headless Chromium, timing each requestAnimationFrame. The numbers compare versions on the same machine; they don't predict any particular device.

## Tests

- **End-to-end, 94/94 pass.** Run in he, en and fr, on desktop and mobile. They cover navigation and landing positions, the hero action, language switching, the booking form (live preview, past-date refusal with focus and message, WhatsApp hand-off with the composed text, status line) and the greeting on every WhatsApp link. They also cover carousel next/prev/pause/arrow keys, muted autoplay in view, the theatre (open, next, Escape, focus return), the mobile action bar (hidden on the hero, shown after, hidden at the form), the mobile menu (inert background, focus, closes on navigation) and tap targets.
- **Edge cases:** reduced motion, JavaScript disabled, failed preview clip, failed full video.
- **Devices:** 360 px, iPhone 13, iPad portrait and landscape, 1440, 1920 and 2560 px. No horizontal overflow and no console errors on any of them.

## What changed and why

1. **Diagnosis.** The first redesign looked rich but measured worse than the original: hero content waited for script, GSAP, ScrollTrigger and Lenis cost about 2 s of main-thread work on mobile, and decorative layers dropped scrolling to about 42 fps. It also failed contrast and target-size checks.
2. **Removed the "generated" look.** Removed metallic gradients, shimmer, glows, film grain, backdrop blurs, bento cards with stock-style icons, the marquee, cursor spotlights, magnetic buttons, eyebrow labels on every section, a roles list that repeated the heading, a "watch" card section that duplicated the videos, and a second use of the hero photo.
3. **Design system.** The site is styled like a concert programme: warm black and ivory paper with one foil gold, Frank Ruhl Libre and Bodoni Moda for display, Heebo and Inter for text, hairline ledgers instead of cards, 2 px controls, an 8-pt spacing scale and a 12-column grid. Every text pair is checked for contrast.
4. **UX.** Every "check a date" action leads to the same short form. Date and place are optional, past dates are refused with an explanation, and you see the exact message before WhatsApp opens. A phone fallback appears after sending. On mobile, a bottom action bar offers the form and one-tap WhatsApp.
5. **Motion.** The hero intro is CSS only, so first paint doesn't wait. A dependency-free scroll engine does one rect read per scene and one write per frame. The staff canvas sleeps when idle. Every animation is transform or opacity, and all of it is disabled under reduced motion.
6. **Engineering.** No runtime dependencies. Fonts are subset and limited to the weights used, including a 2.6 KB wordmark font. The CSP allows no third-party sources and hashes the single inline line; page data is JSON. Headers set frame-ancestors, Permissions-Policy and COOP. Images use AVIF and WebP with fixed ratios.
