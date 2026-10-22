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
         .env({'FF_THREADS': '0', 'FF_PRESET': 'veryfast', 'OUT_W': '1080'})
         .add_local_file(os.path.join(HERE, 'engine.py'), '/root/engine.py'))
app = modal.App(APP_NAME)
progress = modal.Dict.from_name(APP_NAME + '-progress', create_if_missing=True)


@app.function(image=image, cpu=4.0, memory=4096, timeout=900)
def build(job: dict, base: bytes, top: bytes) -> bytes:
    """job: {'id', 'items': [{'url','kind','dur','audio','fps','acodec'}...], 'geo', 'info', 'max_bytes'}"""
    import shutil
    import tempfile
    import urllib.request
    import engine

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
        with open(out, 'rb') as f:
            data = f.read()
        progress[job['id']] = {'stage': 'done', 'p': 1, 'dur': info.get('dur', 0), 'W': info['W'], 'H': info['H']}
        return data
    finally:
        shutil.rmtree(work, ignore_errors=True)
