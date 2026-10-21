"""
Harabanit Studio - Telegram bot.

Send the bot a photo or video(s) with the text (opening word, headline, credits)
and it replies with a finished story/post in the brand style.

Environment:
  BOT_TOKEN       token from @BotFather (required)
  ALLOWED_IDS     Telegram user IDs allowed to use the bot, comma separated
  WEBHOOK_SECRET  random string; Telegram sends it back on every update
  RENDER_EXTERNAL_URL  set automatically on Render -> webhook mode.
                  Without it the bot uses long polling (handy on a home computer).
  SITE_DIR        folder of the studio (default: ../harabanit)
"""
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine

TOKEN = os.environ.get('BOT_TOKEN', '').strip()
API = f'https://api.telegram.org/bot{TOKEN}/'
FILE_API = f'https://api.telegram.org/file/bot{TOKEN}/'
ALLOWED = {int(x) for x in re.findall(r'\d+', os.environ.get('ALLOWED_IDS', ''))}
_RAW_SECRET = os.environ.get('WEBHOOK_SECRET', '').strip()
# Telegram only accepts A-Z a-z 0-9 _ - in secret tokens, so derive a safe one.
SECRET = hashlib.sha256(_RAW_SECRET.encode()).hexdigest() if _RAW_SECRET else ''
PUBLIC_URL = os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')
PORT = int(os.environ.get('PORT', '10000'))
HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.environ.get('SITE_DIR') or os.path.normpath(os.path.join(HERE, '..', 'harabanit'))
MAX_DOWNLOAD = 20 * 1024 * 1024   # Telegram's limit for bots
ALBUM_WAIT = 2.5                  # seconds to collect all items of an album
PENDING_TTL = 120                 # media or text waits this long for its other half

HELP = (
    '👋 <b>הרבנית סטודיו</b>\n\n'
    'שלחו תמונה או סרטון (או כמה ביחד באלבום) עם הטקסט בכיתוב:\n\n'
    '<code>מזל טוב!\n'
    'בכירי תעשיית המוזיקה בחגיגות יום הולדת לזמר\n'
    'צילום וידאו: דודי קפלר. צילום תמונה: דודי פרידמן.</code>\n\n'
    '• שורה ראשונה קצרה עם ! – מילת פתיחה\n'
    '• הכותרת – בשורה הבאה. פסקה נוספת אחרי שורה ריקה = טקסט נוסף\n'
    '• קרדיטים – צילום: / צילום וידאו: / צילום תמונה: / באדיבות: / בהפקת: / מפיק: / קרדיט: / מתוך:\n'
    '• #פוסט או #סטורי לבחירת פורמט, #סגול / #אדום וכו׳ לבחירת צבע\n\n'
    'אפשר גם לשלוח קודם את המדיה ואחר כך את הטקסט (או הפוך).\n'
    'פקודות: /post פוסט כברירת מחדל · /story סטורי כברירת מחדל · /id המזהה שלי'
)

studio = None
jobs = queue.Queue()
lock = threading.Lock()
albums = {}       # media_group_id -> {'chat', 'user', 'items', 'caption', 'timer'}
pending = {}      # chat_id -> {'items': [...], 'text': str, 't': time}
prefs = {}        # chat_id -> {'format': 'story'|'post'}


# ---------------------------------------------------------------- Telegram API
def api(method, params=None, files=None, timeout=60):
    url = API + method
    if files:
        boundary = uuid.uuid4().hex
        body = bytearray()
        for k, v in (params or {}).items():
            if v is None:
                continue
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
            body += (v if isinstance(v, str) else json.dumps(v)).encode() + b'\r\n'
        for k, path in files.items():
            mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
                     f'filename="{os.path.basename(path)}"\r\nContent-Type: {mime}\r\n\r\n').encode()
            with open(path, 'rb') as f:
                body += f.read()
            body += b'\r\n'
        body += f'--{boundary}--\r\n'.encode()
        req = urllib.request.Request(url, data=bytes(body), headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    else:
        data = json.dumps({k: v for k, v in (params or {}).items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {'ok': False, 'description': str(e)}


def send(chat, text, **kw):
    return api('sendMessage', dict(chat_id=chat, text=text, parse_mode='HTML', disable_web_page_preview=True, **kw))


def edit(chat, msg_id, text):
    api('editMessageText', dict(chat_id=chat, message_id=msg_id, text=text, parse_mode='HTML'))


def download(file_id, dest_dir):
    info = api('getFile', {'file_id': file_id})
    if not info.get('ok'):
        raise RuntimeError(info.get('description', 'getFile failed'))
    path = info['result']['file_path']
    dest = os.path.join(dest_dir, f'{uuid.uuid4().hex[:8]}_{os.path.basename(path)}')
    with urllib.request.urlopen(FILE_API + urllib.parse.quote(path), timeout=180) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    return dest


# ---------------------------------------------------------------- incoming messages
def media_of(msg):
    """Return {'file_id', 'kind', 'size'} for a photo/video/document message, else None."""
    if msg.get('photo'):
        p = msg['photo'][-1]
        return {'file_id': p['file_id'], 'kind': 'image', 'size': p.get('file_size', 0)}
    for key in ('video', 'animation', 'video_note'):
        if msg.get(key):
            v = msg[key]
            return {'file_id': v['file_id'], 'kind': 'video', 'size': v.get('file_size', 0)}
    doc = msg.get('document')
    if doc:
        mime = doc.get('mime_type', '')
        if mime.startswith('image/'):
            return {'file_id': doc['file_id'], 'kind': 'image', 'size': doc.get('file_size', 0)}
        if mime.startswith('video/'):
            return {'file_id': doc['file_id'], 'kind': 'video', 'size': doc.get('file_size', 0)}
    return None


def handle_update(upd):
    msg = upd.get('message') or upd.get('channel_post')
    if not msg:
        return
    chat = msg['chat']['id']
    user = (msg.get('from') or {}).get('id', chat)
    text = (msg.get('text') or '').strip()

    if text.startswith('/id'):
        send(chat, f'המזהה שלך: <code>{user}</code>')
        return
    if user not in ALLOWED:
        send(chat, f'🔒 אין לך הרשאה להשתמש ברובוט.\nהמזהה שלך: <code>{user}</code>\nשלחו אותו למנהל כדי לקבל גישה.')
        return
    if text.startswith('/start') or text.startswith('/help'):
        send(chat, HELP)
        return
    if text.startswith('/post') or text.startswith('/story'):
        prefs.setdefault(chat, {})['format'] = 'post' if text.startswith('/post') else 'story'
        send(chat, 'מעכשיו ברירת המחדל: ' + ('פוסט 4:5' if text.startswith('/post') else 'סטורי 9:16'))
        return

    item = media_of(msg)
    caption = (msg.get('caption') or '').strip()
    if item:
        if item['size'] and item['size'] > MAX_DOWNLOAD:
            send(chat, '⚠️ הקובץ גדול מ־20MB, וטלגרם לא מאפשר לרובוטים להוריד קבצים כאלה.\nשלחו גרסה קצרה או דחוסה יותר.')
            return
        item['order'] = msg['message_id']
        gid = msg.get('media_group_id')
        if gid:
            with lock:
                al = albums.get(gid)
                if not al:
                    al = albums[gid] = {'chat': chat, 'items': [], 'caption': ''}
                al['items'].append(item)
                if caption:
                    al['caption'] = caption
                if al.get('timer'):
                    al['timer'].cancel()
                al['timer'] = threading.Timer(ALBUM_WAIT, finish_album, args=(gid,))
                al['timer'].start()
            return
        arrived(chat, [item], caption)
        return
    if text and not text.startswith('/'):
        with lock:
            p = pending.get(chat)
            if p and p.get('items') and time.time() - p['t'] < PENDING_TTL:
                pending.pop(chat, None)
                enqueue(chat, p['items'], text)
                return
            pending[chat] = {'text': text, 't': time.time()}
        send(chat, '📝 קיבלתי את הטקסט. עכשיו שלחו תמונה או סרטון.')


def finish_album(gid):
    with lock:
        al = albums.pop(gid, None)
    if al:
        items = sorted(al['items'], key=lambda i: i['order'])
        arrived(al['chat'], items, al['caption'])


def arrived(chat, items, caption):
    with lock:
        p = pending.get(chat)
        if not caption and p and p.get('text') and time.time() - p['t'] < PENDING_TTL:
            pending.pop(chat, None)
            caption = p['text']
        if not caption:
            pending[chat] = {'items': items, 't': time.time()}
            send(chat, '🖼 קיבלתי. עכשיו שלחו את הטקסט: מילת פתיחה, כותרת וקרדיט.')
            return
    enqueue(chat, items, caption)


def enqueue(chat, items, caption):
    ahead = jobs.qsize()
    note = f' (בתור: {ahead} לפניך)' if ahead else ''
    r = send(chat, f'⏳ מתחיל לעבוד{note}…')
    msg_id = (r.get('result') or {}).get('message_id')
    jobs.put({'chat': chat, 'items': items, 'caption': caption, 'msg': msg_id})


# ---------------------------------------------------------------- worker
def worker():
    # Open the studio in the browser once, right away, so the first job doesn't wait for it.
    try:
        studio.warm()
        print('studio ready', flush=True)
    except Exception:
        traceback.print_exc()
    while True:
        job = jobs.get()
        try:
            process(job)
            try:
                studio.warm()
            except Exception:
                pass
        except Exception as e:
            traceback.print_exc()
            msg = str(e)
            if 'ffmpeg' in msg:
                msg = 'לא הצלחתי לעבד את הסרטון. נסו קובץ MP4 רגיל.'
            send(job['chat'], f'❌ משהו השתבש: {msg[:300]}')
        finally:
            jobs.task_done()


def process(job):
    chat, msg_id = job['chat'], job['msg']
    last = [0.0]

    def status(text, force=False):
        if msg_id and (force or time.time() - last[0] > 3):
            last[0] = time.time()
            edit(chat, msg_id, text)

    meta = engine.parse_text(job['caption'])
    if not meta['format']:
        meta['format'] = prefs.get(chat, {}).get('format', 'story')
    if not meta['head'] and not meta['kicker']:
        send(chat, '⚠️ לא מצאתי כותרת בטקסט. שלחו שוב עם כותרת.')
        return

    work = tempfile.mkdtemp(prefix='hb_')
    try:
        status('⬇️ מוריד את הקבצים…', True)
        items = [{'path': download(it['file_id'], work), 'kind': it['kind']} for it in job['items']]

        t_video = [None]

        def progress(stage, p=None):
            if stage == 'design':
                status('🎨 מעצב בשפת המותג…', True)
            elif stage == 'video':
                now = time.time()
                if t_video[0] is None:
                    t_video[0] = now
                p = p or 0
                pct = int(p * 100)
                bar = '▰' * (pct // 10) + '▱' * (10 - pct // 10)
                spent = int(now - t_video[0])
                eta = ''
                if p > 0.04 and spent > 2:
                    left = int(spent * (1 - p) / p)
                    eta = f'\nעוד כ־{left} שנ׳' if left < 120 else f'\nעוד כ־{round(left / 60)} דק׳'
                status(f'🎬 מרכיב את הסרטון\n{bar} {pct}%{eta}')

        out, kind, info = engine.make(studio, items, meta, work, progress)
        status('📤 שולח…', True)
        fmt = 'סטורי 9:16' if info['format'] == 'story' else 'פוסט 4:5'
        caption = f'✅ מוכן · {fmt}'
        if kind == 'image':
            r = api('sendDocument', {'chat_id': str(chat), 'caption': caption + ' · איכות מלאה'}, {'document': out}, timeout=300)
        else:
            r = api('sendVideo', {'chat_id': str(chat), 'caption': caption, 'supports_streaming': 'true',
                                  'width': str(info['W']), 'height': str(info['H']), 'duration': str(int(info.get('dur', 0)))},
                    {'video': out}, timeout=600)
        if not r.get('ok'):
            raise RuntimeError(r.get('description', 'send failed'))
        if msg_id:
            api('deleteMessage', {'chat_id': chat, 'message_id': msg_id})
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- web server (webhook + health)
class Hook(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        body = 'הרבנית סטודיו – הרובוט פעיל · גרסה ' + os.environ.get('RENDER_GIT_COMMIT', 'local')[:7]
        if self.path.startswith('/status'):
            info = api('getWebhookInfo').get('result', {})
            body += f"\nwebhook: {bool(info.get('url'))} pending: {info.get('pending_update_count')} error: {info.get('last_error_message', '-')}"
            body += f"\nallowed users: {len(ALLOWED)}"
        self.wfile.write(body.encode())

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path != '/tg' or (SECRET and self.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET):
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length') or 0)
        try:
            upd = json.loads(self.rfile.read(length).decode() or '{}')
        except ValueError:
            upd = {}
        self.send_response(200)
        self.end_headers()
        threading.Thread(target=safe_handle, args=(upd,), daemon=True).start()

    def log_message(self, *a):
        pass


def safe_handle(upd):
    try:
        handle_update(upd)
    except Exception:
        traceback.print_exc()


def polling():
    api('deleteWebhook', {'drop_pending_updates': False})
    offset = None
    while True:
        r = api('getUpdates', {'timeout': 50, 'offset': offset, 'allowed_updates': ['message']}, timeout=70)
        for upd in r.get('result', []) if r.get('ok') else []:
            offset = upd['update_id'] + 1
            safe_handle(upd)
        if not r.get('ok'):
            time.sleep(3)


def keep_awake():
    """Render's free plan sleeps after 15 idle minutes; a light ping every 10 minutes keeps replies instant."""
    if not PUBLIC_URL or os.environ.get('KEEP_AWAKE', '1') == '0':
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(PUBLIC_URL + '/', timeout=20).read()
        except Exception:
            pass


def main():
    global studio
    if not TOKEN:
        raise SystemExit('BOT_TOKEN is missing')
    studio = engine.Studio(SITE_DIR)
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=keep_awake, daemon=True).start()
    api('setMyCommands', {'commands': [
        {'command': 'start', 'description': 'הסבר קצר'},
        {'command': 'story', 'description': 'סטורי 9:16 כברירת מחדל'},
        {'command': 'post', 'description': 'פוסט 4:5 כברירת מחדל'},
        {'command': 'id', 'description': 'המזהה שלי'}]})
    if PUBLIC_URL:
        r = api('setWebhook', {'url': PUBLIC_URL + '/tg', 'secret_token': SECRET or None,
                               'allowed_updates': ['message'], 'max_connections': 10})
        print('webhook:', r, flush=True)
        if r.get('ok'):
            ThreadingHTTPServer(('0.0.0.0', PORT), Hook).serve_forever()
            return
        print('webhook failed, falling back to polling', flush=True)
    if True:
        threading.Thread(target=lambda: ThreadingHTTPServer(('0.0.0.0', PORT), Hook).serve_forever(), daemon=True).start()
        print('polling mode', flush=True)
        polling()


if __name__ == '__main__':
    main()
