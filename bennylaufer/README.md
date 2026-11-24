# bennylaufer.com — redesign

A one-page site for the Benny Laufer Orchestra in Hebrew (`/`), English (`/en/`) and French (`/fr/`).
Live preview: **https://bennylaufer.vercel.app**

## Design system

The site is styled like a concert programme. Type, hairlines and photography carry it: no cards, glows, gradients or decorative icons.

| Token | Value | Use |
| --- | --- | --- |
| `--ink` / `--fg` | `#0c0b0a` / `#ece7dd` | Stage background and text (15.9:1) |
| `--fg-2`, `--fg-3` | 7.9:1, 5.7:1 | Secondary text; `--fg-3` is the smallest text allowed |
| `--fg-dim` | 3.3:1 | Large text before it lights up; input and button borders |
| `--gold` | `#c9a34f` | Foil accent, used sparingly: the monogram, the surname, the primary action |
| `--paper` / `--on-paper` | `#efe9dc` / `#191714` | The ivory chapter (services, booking steps) |
| Display | Frank Ruhl Libre (he) · Bodoni Moda (en/fr) | Names and headings |
| Text | Heebo (he) · Inter (en/fr) | Everything else |
| Radius | `2px` controls · `0` media · round only for icon buttons | |
| Space | 8-pt scale, `--section` for vertical rhythm, 12-column grid | |

Every text pair passes WCAG 2.2 AA (`src` comments list the ratios). Tap targets are at least 44px on touch screens.

## Behaviour

- The hero draws in with CSS only, so first paint never waits for script. Scrolling pins the stage while the conducting photograph rises like a curtain.
- The five staff lines are a canvas that reacts to a cursor or a finger. When nothing touches them they sleep, with no animation loop.
- The manifesto lights up word by word. The wide stage photograph opens to full bleed. Other sections arrive once, quietly.
- Video: muted 8-second loops play only while the section is in view. Tapping a clip opens the full video with sound in a native `<dialog>`. Buffering, failed-clip and failed-video states are handled.
- Booking: choose an event type, a date (past dates are refused, with a message) and a place. A live preview shows the exact WhatsApp message. After sending, a status line offers the phone number in case WhatsApp doesn't open.
- Mobile: a bottom action bar (check a date, plus WhatsApp) appears after the hero. It steps aside at the form and while typing, and respects safe areas.
- `prefers-reduced-motion`: no pinning or scrubbing, everything visible. Without JavaScript the page is complete.

## Engineering

- No dependencies. `main.js` is about 8 KB gzipped, with one scroll listener and one rAF per frame. Each scene reads its rect first, then writes transforms.
- Fonts are self-hosted, subset to the glyphs used and limited to the weights used (66 KB per Hebrew page). The footer wordmark has its own 2.6 KB font.
- Images are AVIF and WebP with `srcset` and fixed aspect ratios, so there is no layout shift.
- A Content-Security-Policy is set in every page: `script-src 'self'` plus the sha256 of the one inline line, `style-src 'self'`, nothing third-party. `vercel.json` adds frame-ancestors, Permissions-Policy and COOP. Page data lives in `<script type="application/json">`.

## Files

```
build.py            renders the three pages from src/ (and the CSP hash, sitemap, robots)
src/template.html   markup ({{key}} raw, {{@key}} attribute-escaped)
src/i18n.json       all copy, per language
src/brand/          traced monogram + original logo files
site/               the deployable static site
vercel-edge/        how site/ is currently served on Vercel (see below)
```

```bash
python3 build.py                      # site/index.html, site/en/, site/fr/, sitemap, robots
python3 build.py --preview OUT_DIR    # the same pages with file-relative language links
```

## Deploy

The Vercel account has no GitHub connection. Project `bennylaufer` (team `pini`) is therefore deployed from `vercel-edge/`:

- `middleware.js` serves `/`, `/en/` and `/fr/` from this repo at a pinned commit. On `*.vercel.app` it sets `noindex`, because the canonical site is bennylaufer.com.
- `vercel.json` rewrites `/assets`, `/media` and the icons to jsDelivr at the same commit.

To publish: push, put the new commit SHA in both files, and redeploy them. Once GitHub is connected to Vercel (Account Settings, Authentication), connect the repo instead: root directory `bennylaufer/site`, no build command.
