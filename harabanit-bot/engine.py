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
# Video output width. 720 keeps memory and time low on a small server; set OUT_W=1080 on a bigger one.
OUT_W = int(os.environ.get('OUT_W', '720'))
# Encoder settings: a small server uses 2 threads / ultrafast; a strong one (Modal) uses all cores / veryfast.
FF_THREADS = os.environ.get('FF_THREADS', '2')
FF_PRESET = os.environ.get('FF_PRESET', 'ultrafast')
FF_MAXRATE = os.environ.get('FF_MAXRATE', '7M')

# Credit labels as people actually type them -> the label the studio shows.
# Any of : ; - – may follow the label ("צילום; איציק אוחנה" works too).
CREDIT_ALIASES = [
    ('צילום וידאו', 'צילום וידאו:'), ('צילום וידיאו', 'צילום וידאו:'), ('וידאו', 'צילום וידאו:'),
    ('צילום תמונה', 'צילום תמונה:'), ('צילום תמונות', 'צילום תמונה:'), ('צילומים', 'צילום:'),
    ('צלם תמונה', 'צילום תמונה:'), ('צלם וידאו', 'צילום וידאו:'), ('צלמת וידאו', 'צילום וידאו:'),
    ('צילום', 'צילום:'), ('צלם', 'צילום:'), ('צלמת', 'צילום:'),
    ('בהפקת', 'בהפקת:'), ('הפקה', 'בהפקת:'), ('הפקת', 'בהפקת:'), ('מפיק', 'מפיק:'), ('מפיקה', 'מפיק:'),
    ('באדיבות', 'באדיבות:'), ('קרדיט', 'קרדיט:'), ('מתוך', 'מתוך:'),
]
CREDIT_TYPES = sorted({v for _, v in CREDIT_ALIASES}, key=len, reverse=True)
_ALIAS = {k: v for k, v in CREDIT_ALIASES}


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

    labels = sorted(_ALIAS, key=len, reverse=True)   # longest first
    credit_re = re.compile(r'(?:(?<=^)|(?<=[\s.,;|·]))(' + '|'.join(re.escape(t) for t in labels) + r')\s*[:;\-–—]\s*')
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
                name = line[m.end():end].strip(' .,:;-–—|·')
                if name:
                    credits.append([_ALIAS[m.group(1)], name])
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
    a = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), None)
    has_audio = a is not None
    try:
        num, den = (v.get('avg_frame_rate') or v.get('r_frame_rate') or '30/1').split('/')
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    dur = float(info.get('format', {}).get('duration') or (v or {}).get('duration') or 0)
    w, h = int(v['width']), int(v['height'])
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    rot = int((v.get('tags') or {}).get('rotate', rot) or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {'w': w, 'h': h, 'dur': dur, 'audio': has_audio, 'fps': fps or 30.0, 'acodec': (a or {}).get('codec_name', ''), 'vcodec': (v or {}).get('codec_name', '')}


def playable(path, workdir):
    """Make sure a video plays everywhere in Telegram (H.264 + AAC). Converts only when needed."""
    p = probe(path)
    if p['vcodec'] == 'h264' and p['acodec'] in ('aac', ''):
        return path, p
    out = os.path.join(workdir, 'phone_fixed.mp4')
    vc = ['-c:v', 'copy'] if p['vcodec'] == 'h264' else ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '21', '-pix_fmt', 'yuv420p']
    run(['ffmpeg', '-y', '-v', 'error', '-i', path] + vc + ['-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', out])
    return out, probe(out)


def kind_of(path):
    """'image' or 'video' for a downloaded file of unknown type."""
    try:
        info = json.loads(run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path]).stdout)
    except Exception:
        raise RuntimeError('הקובץ מהקישור אינו תמונה או סרטון.')
    fmt = info.get('format', {}).get('format_name', '')
    v = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not v:
        raise RuntimeError('הקובץ מהקישור אינו תמונה או סרטון.')
    if 'image2' in fmt or fmt.endswith('_pipe') or v.get('codec_name') in ('mjpeg', 'png', 'webp', 'heic', 'gif') and float(info.get('format', {}).get('duration') or 0) < 0.2:
        return 'image'
    return 'video'


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


# ---------------------------------------------------------------- progress picture
# While the video is built, the chat shows the brand logo filling with colour (like the studio's export screen).
THEME_HEX = {'sky': '#19A3F3', 'purple': '#784ECE', 'indigo': '#350AD3', 'blue': '#2B6AE6', 'lime': '#73BA3C',
             'forest': '#064520', 'mint': '#15E78E', 'teal': '#00AFB4', 'pink': '#F90B78', 'magenta': '#EC00C7',
             'red': '#EF2A1A', 'coral': '#F96249', 'orange': '#E98139', 'yellow': '#EFE15A', 'silver': '#A9ABB0',
             'copper': '#9A6436'}
_FONT = next((f for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                          '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf') if os.path.exists(f)), None)


def fill_frames(site_dir, theme, out_dir, steps=10):
    """Pictures of the logo filled 0%..100% (steps+1 files). Returns their paths ([] if Pillow is missing)."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return []
    logo_path = os.path.join(site_dir, 'logos', f'{theme}.webp')
    if not os.path.exists(logo_path):
        theme, logo_path = 'red', os.path.join(site_dir, 'logos', 'red.webp')
    col = THEME_HEX.get(theme, '#F93A34')
    rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    W, H = 720, 900
    mix = lambda k: tuple(round(c * (1 - k) + 255 * k) for c in rgb)
    bg = Image.new('RGB', (W, H))
    top_c, bot_c = mix(.86), mix(.97)
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(round(a * (1 - t) + b * t) for a, b in zip(top_c, bot_c)))
    logo = Image.open(logo_path).convert('RGBA')
    LW = 470
    logo = logo.resize((LW, round(logo.height * LW / logo.width)), Image.LANCZOS)
    LH = logo.height
    x0, y0 = (W - LW) // 2, 150
    alpha = logo.split()[3]
    gray = logo.convert('LA').convert('RGBA')
    gray.putalpha(alpha.point(lambda a: int(a * .2)))
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sh = Image.new('RGBA', logo.size, rgb + (0,))
    sh.putalpha(alpha.point(lambda a: int(a * .35)))
    shadow.paste(sh, (x0, y0 + 14), sh)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    font = ImageFont.truetype(_FONT, 64) if _FONT else ImageFont.load_default()
    ink = tuple(round(c * .55) for c in rgb) if sum(rgb) > 380 else rgb
    paths = []
    for i in range(steps + 1):
        p = i / steps
        im = bg.convert('RGBA')
        im.alpha_composite(gray, (x0, y0))
        fh = round(LH * p)
        if fh > 0:
            sl = shadow.crop((0, 0, W, H))
            # the shadow follows the filled part only
            m = Image.new('L', (W, H), 0)
            ImageDraw.Draw(m).rectangle([0, y0 + LH - fh, W, H], fill=255)
            im.alpha_composite(Image.composite(sl, Image.new('RGBA', (W, H), (0, 0, 0, 0)), m))
            part = logo.crop((0, LH - fh, LW, LH))
            im.alpha_composite(part, (x0, y0 + LH - fh))
            if p < 1:
                # a soft shine on the fill line, inside the logo only
                band = Image.new('L', (LW, LH), 0)
                yb = LH - fh
                ImageDraw.Draw(band).rectangle([0, max(0, yb - 5), LW, min(LH, yb + 5)], fill=170)
                band = band.filter(ImageFilter.GaussianBlur(4))
                band = Image.composite(band, Image.new('L', (LW, LH), 0), alpha)
                shine = Image.new('RGBA', (LW, LH), (255, 255, 255, 0))
                shine.putalpha(band)
                im.alpha_composite(shine, (x0, y0))
        txt = f'{round(p * 100)}%'
        tw = ImageDraw.Draw(im).textlength(txt, font=font)
        ImageDraw.Draw(im).text(((W - tw) / 2, y0 + LH + 70), txt, font=font, fill=ink)
        # thin progress line under the number
        bx, by, bw = 180, y0 + LH + 175, W - 360
        ImageDraw.Draw(im).rounded_rectangle([bx, by, bx + bw, by + 10], 5, fill=mix(.8))
        if p > 0:
            ImageDraw.Draw(im).rounded_rectangle([bx, by, bx + max(10, round(bw * p)), by + 10], 5, fill=rgb)
        out = os.path.join(out_dir, f'fill_{i:02d}.jpg')
        im.convert('RGB').save(out, quality=88)
        paths.append(out)
    return paths


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
                                                       '--disable-extensions', '--mute-audio', '--no-zygote',
                                                       '--renderer-process-limit=1', '--disable-site-isolation-trials',
                                                       '--disable-features=site-per-process,Translate,MediaRouter',
                                                       '--js-flags=--max-old-space-size=160'])
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
# Two steps: prepare() designs and returns a quick preview picture (seconds),
# finish() builds the final file (the slow part for videos) after approval.
def split_corner(items):
    """A photo sent together with video(s): the videos are the main media, the (first) photo goes in the corner."""
    vids = [i for i in items if i['kind'] == 'video']
    imgs = [i for i in items if i['kind'] == 'image']
    if vids and imgs:
        return vids[:2], imgs[0]
    return items, None


def corner_data_url(path, workdir):
    """The corner photo, at most 1024 px, as a data URL (PNG keeps transparency)."""
    keep_alpha = os.path.splitext(path)[1].lower() in ('.png', '.webp')
    out = os.path.join(workdir, 'corner.png' if keep_alpha else 'corner.jpg')
    if not os.path.exists(out):
        run(['ffmpeg', '-y', '-v', 'error', '-i', path, '-vf',
             "scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease", '-frames:v', '1']
            + ([] if keep_alpha else ['-q:v', '3']) + [out])
    return data_url(out, 'image/png' if keep_alpha else 'image/jpeg'), out


RVM_ONNX = os.environ.get('RVM_ONNX', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'rvm.onnx'))


def person_matte(path, workdir, max_side=512):
    """Where the people are in a photo (alpha 0..255), found with the RVM model on the CPU.
    Same model the studio runs on the phone; here it takes seconds instead of minutes in the browser.
    Returns {'w','h','b64'} or None (no model / no library)."""
    cache = os.path.join(workdir, 'corner_matte.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    try:
        import numpy as np
        import onnxruntime as ort
        from PIL import Image
    except ImportError:
        return None
    if not os.path.exists(RVM_ONNX):
        return None
    im = Image.open(path).convert('RGB')
    k = min(1.0, max_side / max(im.size))
    w, h = max(2, round(im.width * k)), max(2, round(im.height * k))
    im = im.resize((w, h), Image.BILINEAR)
    x = (np.asarray(im, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(RVM_ONNX, so, providers=['CPUExecutionProvider'])
    rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4
    ratio = np.array([min(1.0, 448 / max(w, h))], np.float32)
    pha = None
    for _ in range(2):   # a second pass lets the recurrent state settle on a still photo
        out = sess.run(None, {'src': x, 'r1i': rec[0], 'r2i': rec[1], 'r3i': rec[2], 'r4i': rec[3], 'downsample_ratio': ratio})
        pha, rec = out[1], out[2:6]
    del sess
    a = np.clip(pha[0, 0] * 255 + .5, 0, 255).astype(np.uint8)
    res = {'w': int(a.shape[1]), 'h': int(a.shape[0]), 'b64': base64.b64encode(a.tobytes()).decode()}
    with open(cache, 'w') as f:
        json.dump(res, f)
    return res


def prepare(studio, items, meta, workdir, corner=None):
    """items: [{'path':..., 'kind':'image'|'video'}] in order; corner: optional photo path for the corner.
    Returns a state dict with 'preview' (JPG path)."""
    for it in items:
        if 'w' not in it:
            it.update(probe(it['path']))
            if it['kind'] == 'image':
                it['dur'] = PHOTO_SECS
                it['audio'] = False
    fmt = meta.get('format') or 'story'
    first = items[0]
    poster = os.path.join(workdir, 'poster.jpg')
    if not os.path.exists(poster):
        poster_of(first['path'], first['kind'], first['dur'], poster)
    opts = {'format': fmt, 'kicker': meta.get('kicker', ''), 'head': meta.get('head', ''),
            'extra': meta.get('extra', ''), 'credits': meta.get('credits', []), 'theme': meta.get('theme'),
            'poster': data_url(poster)}
    if corner:
        opts['cut'], cfile = corner_data_url(corner, workdir)
        try:
            opts['cutMatte'] = person_matte(cfile, workdir)
        except Exception as e:   # the studio falls back to its own detection
            print('matte failed:', e, flush=True)

    # A single photo -> the preview is already the finished picture.
    if len(items) == 1 and first['kind'] == 'image':
        opts['kind'] = 'image'
        res = studio.render(opts)
        out = save_data_url(res['jpg'], os.path.join(workdir, 'harabanit.jpg'))
        return {'mode': 'image', 'out': out, 'preview': out, 'items': items,
                'info': {'theme': res.get('theme'), 'format': fmt, 'W': res['W'], 'H': res['H']}}

    k = min(1.0, 1280 / max(first['w'], first['h']))
    opts.update({'kind': 'video', 'mw': even(first['w'] * k), 'mh': even(first['h'] * k)})
    res = studio.render(opts)
    overlay = save_data_url(res['png'], os.path.join(workdir, 'overlay.png'))
    # Everything below works at the output size (default 720 wide): the design layer is scaled once.
    q = min(1.0, OUT_W / res['W'])
    W, H = even(res['W'] * q), even(res['H'] * q)
    m = {k2: res['media'][k2] * q for k2 in ('x', 'y', 'w', 'h', 'dw', 'dh')}
    dw, dh = even(m['dw']), even(m['dh'])
    X = round(m['x'] + (m['w'] - m['dw']) * res['fx'])
    Y = round(m['y'] + (m['h'] - m['dh']) * res['fy'])
    gray = ',hue=s=0' if res.get('gray') else ''
    # Visible part of the media area (inside the frame). Clips are cut to exactly this, early.
    x0, y0 = even(max(0, m['x'], X)), even(max(0, m['y'], Y))
    x1, y1 = min(W, m['x'] + m['w'], X + dw), min(H, m['y'] + m['h'], Y + dh)
    cw, ch = even(x1 - x0), even(y1 - y0)
    # Two still images, made once: the full design over black (base), and the design layer
    # cut to the media area (top: credit, logo, corner picture over the video).
    base_png, top_png = os.path.join(workdir, 'base.png'), os.path.join(workdir, 'top.png')
    preview = os.path.join(workdir, 'preview.jpg')
    clip = (f"scale={dw}:{dh}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={dw}:{dh},crop={cw}:{ch}:{x0 - X}:{y0 - Y}{gray},setsar=1")
    run(['ffmpeg', '-y', '-v', 'error', '-i', overlay, '-i', poster, '-filter_complex',
         f"[0:v]scale={W}:{H}:flags=lanczos,format=rgba,split[a][b];color=c=black:s={W}x{H}:d=1[bk];"
         f"[bk][a]overlay=0:0:format=auto,format=rgb24,split[base][base2];[b]crop={cw}:{ch}:{x0}:{y0},split[top][top2];"
         f"[1:v]{clip}[p];[base2][p]overlay={x0}:{y0}[pb];[pb][top2]overlay={x0}:{y0}[prev]",
         '-map', '[base]', '-frames:v', '1', base_png, '-map', '[top]', '-frames:v', '1', top_png,
         '-map', '[prev]', '-frames:v', '1', '-q:v', '3', preview])
    return {'mode': 'video', 'preview': preview, 'items': items, 'base': base_png, 'top': top_png, 'corner': res.get('corner'),
            'geo': {'W': W, 'H': H, 'dw': dw, 'dh': dh, 'X': X, 'Y': Y, 'x0': x0, 'y0': y0, 'cw': cw, 'ch': ch, 'gray': gray},
            'info': {'theme': res.get('theme'), 'format': fmt, 'W': W, 'H': H,
                     'fx': res.get('fx', .5), 'fy': res.get('fy', .5), 'gray': bool(res.get('gray'))}}


def finish(studio, state, workdir, progress=lambda stage, p=None: None, max_bytes=48 * 1024 * 1024):
    """Build the final file from a prepared state. Returns (path, kind, info)."""
    if state['mode'] == 'image':
        return state['out'], 'image', state['info']
    # Free the browser's memory before ffmpeg starts (a small server can't hold both).
    if studio is not None:
        studio.close()
    items, g = state['items'], state['geo']
    W, H, dw, dh, X, Y = g['W'], g['H'], g['dw'], g['dh'], g['X'], g['Y']
    x0, y0, cw, ch, gray = g['x0'], g['y0'], g['cw'], g['ch'], g['gray']
    base_png, top_png = state['base'], state['top']
    res = state['info']
    fmt = res['format']
    # Frame rate: never above the source (a 25 fps clip stays 25, 50/60 fps drops to 30).
    fps = max(15, min(FPS, round(min(it.get('fps', FPS) if it['kind'] == 'video' else FPS for it in items))))
    total = sum(it['dur'] for it in items) - XF * (len(items) - 1)

    cmd = ['ffmpeg', '-y', '-v', 'error', '-nostats', '-progress', 'pipe:1', '-filter_complex_threads', '1']
    for it in items:
        if it['kind'] == 'image':
            cmd += ['-loop', '1', '-framerate', str(fps), '-t', f"{it['dur']:.3f}", '-i', it['path']]
        else:
            # Faster decoding: skip the in-loop deblocking (invisible once the clip is scaled down).
            cmd += ['-skip_loop_filter', 'all', '-flags2', '+fast', '-i', it['path']]
    cmd += ['-i', base_png, '-i', top_png]
    n = len(items)
    ib, it_ = n, n + 1

    f = []
    for i, it in enumerate(items):
        f.append(f"[{i}:v]fps={fps},scale={dw}:{dh}:force_original_aspect_ratio=increase:flags=fast_bilinear,"
                 f"crop={dw}:{dh},crop={cw}:{ch}:{x0 - X}:{y0 - Y}{gray},setsar=1,format=yuv420p,settb=AVTB[v{i}]")
    vcur, off = 'v0', items[0]['dur'] - XF
    for i in range(1, n):
        f.append(f"[{vcur}][v{i}]xfade=transition=fade:duration={XF}:offset={max(0.0, off):.3f}[xv{i}]")
        vcur = f'xv{i}'
        off += items[i]['dur'] - XF
    f.append(f"[{ib}:v]format=yuv420p,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB[base]")
    f.append(f"[{it_}:v]format=yuva420p,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB[top]")
    f.append(f"[base][{vcur}]overlay={x0}:{y0}:shortest=1:format=yuv420[b1]")
    f.append(f"[b1][top]overlay={x0}:{y0}:format=yuv420,format=yuv420p[out]")

    # Sound: a single clip with AAC sound is copied as is (no re-encoding).
    copy_audio = n == 1 and items[0]['audio'] and items[0].get('acodec') == 'aac'
    amap, acodec = [], ['-c:a', 'aac', '-b:a', '160k']
    if copy_audio:
        amap, acodec = ['-map', '0:a:0'], ['-c:a', 'copy']
    else:
        for i, it in enumerate(items):
            if it['audio']:
                f.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{it['dur']:.3f},asetpts=PTS-STARTPTS[a{i}]")
            else:
                f.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{it['dur']:.3f}[a{i}]")
        acur = 'a0'
        for i in range(1, n):
            f.append(f"[{acur}][a{i}]acrossfade=d={XF}[xa{i}]")
            acur = f'xa{i}'
        amap = ['-map', f'[{acur}]']

    out = os.path.join(workdir, 'harabanit.mp4')
    cmd += ['-filter_complex', ';'.join(f), '-map', '[out]'] + amap + [
            '-c:v', 'libx264', '-preset', FF_PRESET, '-crf', '22', '-threads', FF_THREADS, '-maxrate', FF_MAXRATE, '-bufsize', str(int(FF_MAXRATE.rstrip('M')) * 2) + 'M',
            '-pix_fmt', 'yuv420p', '-r', str(fps)] + acodec + [
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
    if os.path.getsize(out) > max_bytes:
        kbps = int(((max_bytes / 1048576) * 0.92 * 8 * 1024) / max(1.0, total)) - 170
        small = os.path.join(workdir, 'harabanit_small.mp4')
        run(['ffmpeg', '-y', '-v', 'error', '-i', out, '-c:v', 'libx264', '-preset', 'veryfast',
             '-b:v', f'{max(800, kbps)}k', '-maxrate', f'{max(800, kbps)}k', '-bufsize', f'{2 * max(800, kbps)}k',
             '-c:a', 'copy', '-movflags', '+faststart', small])
        out = small
    return out, 'video', {'theme': res.get('theme'), 'format': fmt, 'W': W, 'H': H, 'dur': total}


def make(studio, items, meta, workdir, progress=lambda stage, p=None: None, max_bytes=48 * 1024 * 1024):
    """Design and build in one go (no preview step)."""
    progress('design')
    return finish(studio, prepare(studio, items, meta, workdir), workdir, progress, max_bytes)
