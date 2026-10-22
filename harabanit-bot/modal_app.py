"""
Harabanit Studio - the heavy video build, on Modal (modal.com).

Modal gives $30/month of compute for free (no card), on fast multi-core machines, so a video that
takes a minute on the free Render server is built here in seconds, at full 1080 quality.
The bot deploys this app itself at start-up when MODAL_TOKEN_ID / MODAL_TOKEN_SECRET are set.
"""
import os
import modal

APP_NAME = os.environ.get('MODAL_APP', 'harabanit')
HERE = os.path.dirname(os.path.abspath(__file__))

image = (modal.Image.debian_slim(python_version='3.11')
         .apt_install('ffmpeg')
         .env({'FF_THREADS': '0', 'FF_PRESET': 'veryfast', 'OUT_W': '1080', 'FF_MAXRATE': '5M'})
         .add_local_file(os.path.join(HERE, 'engine.py'), '/root/engine.py'))
app = modal.App(APP_NAME)
progress = modal.Dict.from_name(APP_NAME + '-progress', create_if_missing=True)


@app.function(image=image, cpu=4.0, memory=4096, timeout=900)
def build(job: dict, base: bytes, top: bytes) -> dict:
    """job: {'id', 'items': [{'url','kind','dur','audio','fps','acodec'}...], 'geo', 'info', 'max_bytes'}"""
    import shutil
    import tempfile
    import time
    import urllib.request
    import engine

    t0 = time.time()
    work = tempfile.mkdtemp(prefix='hb_')
    try:
        items = []
        for i, it in enumerate(job['items']):
            path = os.path.join(work, f'clip{i}' + ('.jpg' if it['kind'] == 'image' else '.mp4'))
            req = urllib.request.Request(it['url'], headers={'User-Agent': 'HarabanitModal'})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, 'wb') as f:
                shutil.copyfileobj(r, f, 1 << 20)
            d = dict(it)
            d['path'] = path
            items.append(d)
            progress[job['id']] = {'stage': 'download', 'p': (i + 1) / len(job['items'])}
        base_png, top_png = os.path.join(work, 'base.png'), os.path.join(work, 'top.png')
        with open(base_png, 'wb') as f:
            f.write(base)
        with open(top_png, 'wb') as f:
            f.write(top)
        state = {'mode': 'video', 'items': items, 'geo': job['geo'], 'info': job['info'], 'base': base_png, 'top': top_png}

        def prog(stage, p=None):
            if stage == 'video':
                progress[job['id']] = {'stage': 'video', 'p': p or 0}
        out, kind, info = engine.finish(None, state, work, prog, max_bytes=job.get('max_bytes', 48 * 1024 * 1024))
        t_built = time.time()
        size = os.path.getsize(out)
        tg = job.get('tg')
        # Send straight to Telegram from here (fast machine, fast network) when it fits the Bot API's 50 MB.
        if tg and size <= 49 * 1024 * 1024:
            progress[job['id']] = {'stage': 'send', 'p': 1}
            r = send_video(tg, out, info)
            if r.get('ok'):
                return {'sent': True, 'size': size, 'build': round(t_built - t0, 1), 'send': round(time.time() - t_built, 1),
                        'dur': info.get('dur', 0)}
        with open(out, 'rb') as f:
            data = f.read()
        return {'sent': False, 'data': data, 'size': size, 'build': round(t_built - t0, 1), 'dur': info.get('dur', 0)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def send_video(tg, path, info):
    """sendVideo through the Bot API (multipart, streamed from disk)."""
    import json
    import uuid
    import urllib.request
    boundary = uuid.uuid4().hex
    fields = {'chat_id': str(tg['chat']), 'caption': tg.get('caption', ''), 'supports_streaming': 'true',
              'width': str(info['W']), 'height': str(info['H']), 'duration': str(int(info.get('dur', 0)))}
    head = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    head += (f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="harabanit.mp4"\r\n'
             f'Content-Type: video/mp4\r\n\r\n').encode()
    tail = f'\r\n--{boundary}--\r\n'.encode()
    with open(path, 'rb') as f:
        body = head + f.read() + tail
    req = urllib.request.Request(f'https://api.telegram.org/bot{tg["token"]}/sendVideo', data=body,
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'ok': False, 'description': str(e)}
