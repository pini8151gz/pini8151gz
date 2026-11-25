#!/usr/bin/env python3
"""Render the Benny Laufer site into static pages, one per language.

    python3 build.py                 # production build -> site/  (/, /en/, /fr/)
    python3 build.py --preview DIR   # same pages with file-relative language links

Text lives in src/i18n.json, markup in src/template.html. CSS/JS/images are
authored directly under site/assets and shared by every language.
"""
import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
SITE = ROOT / "site"
DOMAIN = "https://bennylaufer.com/"
LANGS = ["he", "en", "fr"]
LABELS = {"he": "עב", "en": "EN", "fr": "FR"}
VIDEOS = [4, 3, 5, 2, 7]  # display order of the reels
PHONE = "+972559330757"
EMAIL = "bennylaufermusic.com@gmail.com"


def path_d(svg_file: Path) -> str:
    d = re.search(r'\sd="([^"]+)"', svg_file.read_text()).group(1)
    return re.sub(r"\s+", " ", d).strip()


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def version() -> str:
    h = hashlib.sha1()
    for f in ("assets/css/main.css", "assets/js/main.js"):
        h.update((SITE / f).read_bytes())
    return h.hexdigest()[:10]


def lang_href(target: str, current: str, preview: bool) -> str:
    """Link from the `current` language page to the `target` language page."""
    if not preview:
        return "/" if target == "he" else f"/{target}/"
    up = "" if current == "he" else "../"
    return f"{up}index.html" if target == "he" else f"{up}{target}/index.html"


def lang_switch(cur: str, preview: bool, label: str) -> str:
    links = []
    for l in LANGS:
        cur_attr = ' aria-current="page"' if l == cur else ""
        links.append(f'<a href="{lang_href(l, cur, preview)}" hreflang="{l}" lang="{l}"{cur_attr}>{LABELS[l]}</a>')
    return f'<div class="lang" role="group" aria-label="{esc(label)}">' + "".join(links) + "</div>"


def seo(t: dict, lang: str) -> str:
    url = DOMAIN + t["path"]
    alt = "\n".join(
        f'<link rel="alternate" hreflang="{l}" href="{DOMAIN}{"" if l == "he" else l + "/"}">' for l in LANGS
    )
    others = [L for L in ("he_IL", "en_US", "fr_FR") if L != t["og_locale"]]
    ld = {
        "@context": "https://schema.org",
        "@type": "MusicGroup",
        "name": "Benny Laufer Orchestra",
        "alternateName": ["תזמורת בני לאופר", "Orchestre Benny Laufer"],
        "url": url,
        "description": t["desc"],
        "genre": ["Orchestral", "Wedding music", "Classical"],
        "areaServed": "Worldwide",
        "knowsLanguage": LANGS,
        "email": EMAIL,
        "telephone": PHONE,
        "image": DOMAIN + "assets/img/about-1500.jpg",
        "logo": DOMAIN + "apple-touch-icon.png",
        "member": {"@type": "Person", "name": "Benny Laufer", "jobTitle": "Conductor"},
        "sameAs": ["https://www.instagram.com/benny_laufer", "https://www.youtube.com/@bennylaufer"],
    }
    return "\n".join([
        f'<link rel="canonical" href="{url}">',
        alt,
        f'<link rel="alternate" hreflang="x-default" href="{DOMAIN}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Benny Laufer">',
        f'<meta property="og:locale" content="{t["og_locale"]}">',
        *[f'<meta property="og:locale:alternate" content="{o}">' for o in others],
        f'<meta property="og:title" content="{esc(t["title"])}">',
        f'<meta property="og:description" content="{esc(t["desc"])}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{DOMAIN}og.jpg">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:image" content="{DOMAIN}og.jpg">',
        '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>",
    ])


def font_preload(lang: str, R: str) -> str:
    files = (["frank-ruhl-libre-hebrew-wght-normal", "heebo-hebrew-wght-normal"] if lang == "he"
             else ["bodoni-moda-latin-opsz-normal", "bodoni-moda-latin-opsz-italic", "inter-latin-wght-normal"])
    return "\n".join(
        f'<link rel="preload" href="{R}assets/fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>' for f in files
    )


def reels(t: dict, R: str) -> tuple[str, str]:
    items, dots = [], []
    for i, n in enumerate(VIDEOS, 1):
        label = esc(f'{t["vd_open"]} · {t["vd_item"]} {i}')
        items.append(
            f'<li class="reel" data-full="{R}media/v{n}.mp4" data-poster="{R}assets/img/poster-{n}.jpg">'
            f'<img src="{R}assets/img/poster-{n}.webp" alt="" loading="lazy" decoding="async" width="480" height="854">'
            f'<video muted playsinline preload="none" data-src="{R}media/loop-{n}.mp4" aria-hidden="true"></video>'
            f'<button class="reel-open" type="button" aria-label="{label}">'
            f'<span class="reel-chip"><svg aria-hidden="true"><use href="#i-play"/></svg>{t["vd_open"]}</span></button></li>'
        )
        dots.append(f'<button class="dot" type="button" aria-label="{esc(t["vd_item"])} {i}"><i></i></button>')
    return "".join(items), "".join(dots)


def render(lang: str, data: dict, preview: bool, mono: str, ver: str) -> str:
    t = data[lang]
    R = "" if lang == "he" else "../"
    tpl = (SRC / "template.html").read_text()
    roles = "".join(f"<li>{r}</li>" for r in t["roles"])
    group = "".join(f'<span dir="{t["dir"]}">{w}</span><i></i>' for w in t["marquee"])
    marquee = f'<div class="marquee-group">{group}</div>' * 2
    reel_html, dot_html = reels(t, R)
    special = {
        "R": R,
        "V": ver,
        "SEO": seo(t, lang),
        "MONO_D": mono,
        "LANG_SWITCH": lang_switch(lang, preview, t["lang_label"]),
        "ROLES": roles,
        "MARQUEE": marquee,
        "FONT_PRELOAD": font_preload(lang, R),
        "REELS": reel_html,
        "DOTS": dot_html,
        "WA_JSON": json.dumps(t["wa_text"], ensure_ascii=False),
        "TYPES_JSON": json.dumps({k: t[k] for k in ("o1", "o2", "o3", "o4", "o5")}, ensure_ascii=False),
    }

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key.startswith("@"):
            return esc(str(t[key[1:]]))
        if key in special:
            return special[key]
        if key not in t:
            raise KeyError(f"missing translation '{key}' for {lang}")
        return str(t[key])

    out = re.sub(r"\{\{(@?[A-Za-z0-9_]+)\}\}", sub, tpl)
    left = re.findall(r"\{\{[^}]+\}\}", out)
    if left:
        raise ValueError(f"unrendered placeholders: {left[:5]}")
    return out


def main() -> None:
    preview = "--preview" in sys.argv
    out_dir = Path(sys.argv[sys.argv.index("--preview") + 1]).resolve() if preview else SITE
    data = json.loads((SRC / "i18n.json").read_text())
    keys = set(data["he"])
    for l in LANGS:
        missing = keys ^ set(data[l])
        if missing:
            raise KeyError(f"{l}: keys differ from he: {sorted(missing)}")
    mono = path_d(SRC / "brand" / "mono.svg")
    ver = version()
    for l in LANGS:
        dest = out_dir / ("index.html" if l == "he" else f"{l}/index.html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(l, data, preview, mono, ver))
        print("wrote", dest.relative_to(out_dir.parent) if out_dir != SITE else dest.relative_to(ROOT))
    if not preview:
        urls = "".join(
            "<url><loc>{}</loc>{}</url>\n".format(
                DOMAIN + data[l]["path"],
                "".join(
                    f'<xhtml:link rel="alternate" hreflang="{a}" href="{DOMAIN}{data[a]["path"]}"/>' for a in LANGS
                ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{DOMAIN}"/>',
            )
            for l in LANGS
        )
        (SITE / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            + urls + "</urlset>\n"
        )
        (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}sitemap.xml\n")
        print("wrote site/sitemap.xml, site/robots.txt")


if __name__ == "__main__":
    main()
