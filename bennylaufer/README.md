# bennylaufer.com — redesign

A cinematic, scroll-driven one-page site for the Benny Laufer Orchestra in Hebrew (`/`), English (`/en/`) and French (`/fr/`).
Black stage, champagne gold, one ivory chapter, all built from the content and media of the current site.

## What's on the page

| Section | Effect |
| --- | --- |
| Hero | The gold monogram draws itself, the name rises out of a mask, and stage beams sway. Five gold staff lines can be plucked with the cursor or a finger. |
| Hero → stage | The hero stays pinned while the B&W conducting photo opens from a small window into a full-bleed frame, revealing "This moment happens once. Give it an orchestra." |
| Manifesto | Each word lights up as you read and scroll. |
| About | Image reveal with parallax, staggered heading, roles list |
| Marquee | Event types scroll by and speed up with your scroll |
| On stage | The wide orchestra shot grows to full bleed; a two-photo collage moves with parallax |
| Video | Highlights carousel: muted 8-second loops autoplay in view, with a progress pill. Tapping a clip opens the full video with sound in a lightbox. |
| Services | A bento grid on an ivory sheet that rises over the page, with line-art icons that draw themselves and a gold spotlight that follows the cursor. |
| Process | Sticky heading, a gold rail that fills as you scroll, and steps that light up one by one |
| Contact | Event-type chips, date and place fields, and a **live WhatsApp message preview**. Nothing is sent until the visitor confirms in WhatsApp. |
| Footer | The logo lockup is written out letter by letter and the baton draws across |

Without JavaScript the page is still complete. It also honors `prefers-reduced-motion`: no pinning, no smooth scroll, every section static and readable.

## Files

```
build.py            renders the three language pages from src/
src/template.html   markup (placeholders: {{key}} raw, {{@key}} attribute-escaped)
src/i18n.json       all text, per language — edit copy here
src/brand/mono.svg  the gold monogram, traced from the original logo
site/               deployable output (static)
  assets/css/main.css   design system and layout
  assets/js/main.js     motion and interaction (GSAP + ScrollTrigger, Lenis)
  assets/vendor/        gsap 3.13.0, ScrollTrigger, lenis 1.3.4 (self-hosted)
  assets/fonts/         Frank Ruhl Libre, Heebo, Bodoni Moda, Inter (SIL OFL)
  assets/img/           AVIF/WebP/JPEG at several widths, video posters
  media/                full videos (v*.mp4) and muted 8-second loops (loop-*.mp4)
  og.jpg, favicon.svg, favicon-32.png, apple-touch-icon.png, icon-512.png
  sitemap.xml, robots.txt, vercel.json
```

## Build

```bash
python3 build.py                      # writes site/index.html, site/en/, site/fr/, sitemap, robots
python3 build.py --preview OUT_DIR    # same pages with file-relative language links (for local previews)
```

After editing `main.css` or `main.js`, run the build again. That updates the `?v=` cache-buster.

## Deploy

`site/` is a plain static folder. On Vercel, set the project's root directory to `bennylaufer/site` with no build command and no framework preset.
