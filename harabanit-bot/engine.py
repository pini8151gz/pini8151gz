"""
Harabanit Studio - rendering engine for the Telegram bot.

The look comes from the studio itself (harabanit/index.html), run in headless
Chromium through window.__botRender. Photos come back as a finished JPG. For
videos the studio returns a transparent design layer + the media rectangle,
and ffmpeg places the clip(s) underneath, with crossfades between clips.
"""
import base64
import functools
import http.server
import json
import os
import re
import subprocess
import tempfile
import threading

XF = 0.7          # crossfade between clips, seconds (same as the studio)
PHOTO_SECS = 4.0  # how long a photo stays on screen inside a video
FPS = 30

# Longest first, so "צילום וידאו:" wins over "צילום:".
CREDIT_TYPES = ['צילום וידאו:', 'צילום תמונה:', 'צילום:', 'בהפקת:', 'מפיק:', 'באדיבות:', 'קרדיט:', 'מתוך:']


# ---------------------------------------------------------------- text
def parse_text(text):
    """Turn a free-form message into kicker / headline / extra / credits / format / theme.

    Accepted, for example:
        מזל טוב!
        בכירי תעשיית המוזיקה בחגיגות יום הולדת 36 לזמר מוטי ויזל
        צילום וידאו: דודי קפלר. צילום תמונה: דודי פרידמן.
    Hashtags: #פוסט / #סטורי pick the format, any other #name picks a colour (e.g. #סגול).
    """
    text = (text or '').replace('\r', '')
    fmt, theme = None, None
    for tag in re.findall(r'#(\S+)', text):
        t = tag.strip('.,')
        if t in ('פוסט', 'post'):
            fmt = 'post'
        elif t in ('סטורי', 'story', 'סטוריז'):
            fmt = 'story'
        else:
            theme = t
    text = re.sub(r'#\S+', '', text)

    credit_re = re.compile('|'.join(re.escape(t) for t in CREDIT_TYPES))
    credits, blocks, cur = [], [], []
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        hits = list(credit_re.finditer(line))
        if hits:
            before = line[:hits[0].start()].strip()
            if before:
                cur.append(before)
            for i, m in enumerate(hits):
                end = hits[i + 1].start() if i + 1 < len(hits) else len(line)
                name = line[m.end():end].strip(' .,:-|·')
                if name:
                    credits.append([m.group(0), name])
            continue
        cur.append(line)
    if cur:
        blocks.append(cur)

    kicker = ''
    if blocks:
        first = blocks[0][0]
        rest_of_text = len(blocks[0]) > 1 or len(blocks) > 1
        if rest_of_text and len(first.split()) <= 4 and first.endswith(('!', ':')):
            kicker = first
            blocks[0] = blocks[0][1:]
            if not blocks[0]:
                blocks.pop(0)
    head = ' '.join(blocks[0]) if blocks else ''
    extra = ' '.join(' '.join(b) for b in blocks[1:]) if len(blocks) > 1 else ''
    return {'kicker': kicker, 'head': head, 'extra': extra, 'credits': credits[:2],
            'format': fmt, 'theme': theme}


# ---------------------------------------------------------------- media helpers
def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def probe(path):
    """Display size (after rotation), duration and whether there is sound."""
    out = run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path]).stdout
    info = json.loads(out)
    v = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    has_audio = any(s.get('codec_type') == 'audio' for s in info.get('streams', []))
    dur = float(info.get('format', {}).get('duration') or (v or {}).get('duration') or 0)
    w, h = int(v['width']), int(v['height'])
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    rot = int((v.get('tags') or {}).get('rotate', rot) or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {'w': w, 'h': h, 'dur': dur, 'audio': has_audio}


def poster_of(path, kind, dur, out_jpg):
    if kind == 'image':
        run(['ffmpeg', '-y', '-v', 'error', '-i', path, '-frames:v', '1', '-q:v', '2', out_jpg])
    else:
        t = min(1.0, max(0.0, dur * 0.3))
        run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{t:.2f}', '-i', path, '-frames:v', '1', '-q:v', '2', out_jpg])
    return out_jpg


def data_url(path, mime='image/jpeg'):
    with open(path, 'rb') as f:
        return f'data:{mime};base64,' + base64.b64encode(f.read()).decode()


def save_data_url(url, path):
    with open(path, 'wb') as f:
        f.write(base64.b64decode(url.split(',', 1)[1]))
    return path


def even(n):
    n = int(round(n))
    return max(2, n - (n % 2))


# ---------------------------------------------------------------- studio (headless)
class Studio:
    """Serves the studio folder on localhost and calls window.__botRender in Chromium."""

    def __init__(self, site_dir):
        handler = functools.partial(_QuietHandler, directory=site_dir)
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/index.html?bot=1'

        self._pw = self._browser = self._page = None

    # The browser stays open between jobs (launching it costs seconds every time).
    # Playwright's sync API is single-threaded: always call from the worker thread.
    def warm(self):
        if self._page:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                                                       '--disable-extensions', '--mute-audio'])
        self._page = self._browser.new_page(viewport={'width': 420, 'height': 860})
        self._page.goto(self.url, wait_until='load', timeout=60000)
        self._page.wait_for_function('() => typeof window.__botRender === "function"', timeout=30000)
        self._page.evaluate('() => document.fonts.ready')

    def close(self):
        for x in (self._browser, self._pw):
            try:
                x and (x.close() if x is self._browser else x.stop())
            except Exception:
                pass
        self._pw = self._browser = self._page = None

    def render(self, opts):
        for attempt in (1, 2):
            try:
                self.warm()
                return self._page.evaluate('o => window.__botRender(o)', opts)
            except Exception:
                self.close()
                if attempt == 2:
                    raise


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


# ---------------------------------------------------------------- pipeline
def make(studio, items, meta, workdir, progress=lambda stage, p=None: None):
    """items: [{'path':..., 'kind':'image'|'video'}] in order. Returns (path, kind, info)."""
    for it in items:
        it.update(probe(it['path']))
        if it['kind'] == 'image':
            it['dur'] = PHOTO_SECS
            it['audio'] = False
    fmt = meta.get('format') or 'story'
    first = items[0]
    poster = poster_of(first['path'], first['kind'], first['dur'], os.path.join(workdir, 'poster.jpg'))
    opts = {'format': fmt, 'kicker': meta.get('kicker', ''), 'head': meta.get('head', ''),
            'extra': meta.get('extra', ''), 'credits': meta.get('credits', []), 'theme': meta.get('theme'),
            'poster': data_url(poster)}

    # A single photo -> a finished picture.
    if len(items) == 1 and first['kind'] == 'image':
        progress('design')
        opts['kind'] = 'image'
        res = studio.render(opts)
        out = save_data_url(res['jpg'], os.path.join(workdir, 'harabanit.jpg'))
        return out, 'image', {'theme': res.get('theme'), 'format': fmt, 'W': res['W'], 'H': res['H']}

    # Video (or several clips / photos) -> MP4.
    # Work at roughly the output size: a 4K phone clip is scaled down once, early.
    k = min(1.0, 1280 / max(first['w'], first['h']))
    mw, mh = even(first['w'] * k), even(first['h'] * k)
    opts.update({'kind': 'video', 'mw': mw, 'mh': mh})
    progress('design')
    res = studio.render(opts)
    overlay = save_data_url(res['png'], os.path.join(workdir, 'overlay.png'))
    W, H, m = res['W'], res['H'], res['media']
    dw, dh = even(m['dw']), even(m['dh'])
    X = round(m['x'] + (m['w'] - m['dw']) * res['fx'])
    Y = round(m['y'] + (m['h'] - m['dh']) * res['fy'])

    cmd = ['ffmpeg', '-y', '-v', 'error', '-nostats', '-progress', 'pipe:1']
    for it in items:
        if it['kind'] == 'image':
            cmd += ['-loop', '1', '-t', f"{it['dur']:.3f}", '-i', it['path']]
        else:
            cmd += ['-i', it['path']]
    cmd += ['-i', overlay]
    n, ov = len(items), len(items)

    f = []
    for i, it in enumerate(items):
        f.append(f"[{i}:v]fps={FPS},scale={mw}:{mh}:force_original_aspect_ratio=increase:flags=fast_bilinear,crop={mw}:{mh},setsar=1,format=yuv420p,settb=AVTB[v{i}]")
        if it['audio']:
            f.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{it['dur']:.3f},asetpts=PTS-STARTPTS[a{i}]")
        else:
            f.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{it['dur']:.3f}[a{i}]")
    vcur, acur, off = 'v0', 'a0', items[0]['dur'] - XF
    for i in range(1, n):
        f.append(f"[{vcur}][v{i}]xfade=transition=fade:duration={XF}:offset={max(0.0, off):.3f}[xv{i}]")
        f.append(f"[{acur}][a{i}]acrossfade=d={XF}[xa{i}]")
        vcur, acur = f'xv{i}', f'xa{i}'
        off += items[i]['dur'] - XF
    total = sum(it['dur'] for it in items) - XF * (n - 1)
    gray = ',hue=s=0' if res.get('gray') else ''
    # Only the visible part of the clip is kept (inside the media area and the frame), then padded
    # to full size: one cheap crop+pad instead of blending over a full-size background.
    x0, y0 = even(max(0, m['x'], X)), even(max(0, m['y'], Y))
    x1, y1 = min(W, m['x'] + m['w'], X + dw), min(H, m['y'] + m['h'], Y + dh)
    cw, ch = even(x1 - x0), even(y1 - y0)
    f.append(f"[{vcur}]scale={dw}:{dh}:flags=fast_bilinear{gray},crop={cw}:{ch}:{x0 - X}:{y0 - Y},"
             f"pad={W}:{H}:{x0}:{y0}:black,format=yuv420p[b1]")
    # The design layer is converted once and repeated (not re-decoded per frame).
    f.append(f"[{ov}:v]format=yuva420p,loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB[ovl]")
    f.append(f"[b1][ovl]overlay=0:0:shortest=1:format=yuv420,format=yuv420p[out]")

    out = os.path.join(workdir, 'harabanit.mp4')
    cmd += ['-filter_complex', ';'.join(f), '-map', '[out]', '-map', f'[{acur}]',
            '-c:v', 'libx264', '-preset', 'superfast', '-crf', '23', '-maxrate', '7M', '-bufsize', '14M',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-b:a', '160k',
            '-t', f'{total:.3f}', '-movflags', '+faststart', out]
    progress('video', 0.0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith('out_time_us=') or line.startswith('out_time_ms='):
            try:
                t = int(line.split('=')[1]) / 1e6
                progress('video', min(1.0, t / max(0.1, total)))
            except ValueError:
                pass
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError('ffmpeg: ' + err[-600:])

    # Telegram bots can send up to 50 MB.
    if os.path.getsize(out) > 48 * 1024 * 1024:
        kbps = int((45 * 8 * 1024) / max(1.0, total)) - 170
        small = os.path.join(workdir, 'harabanit_small.mp4')
        run(['ffmpeg', '-y', '-v', 'error', '-i', out, '-c:v', 'libx264', '-preset', 'veryfast',
             '-b:v', f'{max(800, kbps)}k', '-maxrate', f'{max(800, kbps)}k', '-bufsize', f'{2 * max(800, kbps)}k',
             '-c:a', 'copy', '-movflags', '+faststart', small])
        out = small
    return out, 'video', {'theme': res.get('theme'), 'format': fmt, 'W': W, 'H': H, 'dur': total}
