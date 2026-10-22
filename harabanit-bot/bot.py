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
import hmac
import sys
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

import bigfiles
import engine

TOKEN = os.environ.get('BOT_TOKEN', '').strip()
API = f'https://api.telegram.org/bot{TOKEN}/'
FILE_API = f'https://api.telegram.org/file/bot{TOKEN}/'
ALLOWED = {int(x) for x in re.findall(r'\d+', os.environ.get('ALLOWED_IDS', ''))}
# The first ID in ALLOWED_IDS is the admin: people ask for access and the admin approves them with one tap.
ADMIN = int((re.findall(r'\d+', os.environ.get('ALLOWED_IDS', '')) or ['0'])[0])
EXTRA = {}        # user id -> name, approved by the admin (kept in a pinned message in the admin's chat)
STORE_TAG = '🔐 רשימת המורשים לרובוט'
store_msg = [None]
asked = {}        # user id -> time of the last access request (no spamming the admin)


def is_allowed(uid):
    return uid in ALLOWED or uid in EXTRA


def load_users():
    """Read the approved list back from the pinned message (survives restarts and updates)."""
    if not ADMIN:
        return
    pm = (api('getChat', {'chat_id': ADMIN}).get('result') or {}).get('pinned_message') or {}
    text = pm.get('text') or ''
    if not text.startswith(STORE_TAG):
        return
    store_msg[0] = pm.get('message_id')
    for uid, name in re.findall(r'^• (\d+) – (.*)$', text, re.M):
        EXTRA[int(uid)] = name


def save_users():
    lines = [STORE_TAG, '(הרובוט שומר כאן את מי שאישרת. לא למחוק ולא לבטל את הנעיצה)', '']
    lines += [f'• {uid} – {name}' for uid, name in EXTRA.items()] or ['אין עדיין']
    text = '\n'.join(lines)
    if store_msg[0]:
        r = api('editMessageText', {'chat_id': ADMIN, 'message_id': store_msg[0], 'text': text})
        if r.get('ok') or 'not modified' in r.get('description', ''):
            return
    r = api('sendMessage', {'chat_id': ADMIN, 'text': text, 'disable_notification': True})
    if r.get('ok'):
        store_msg[0] = r['result']['message_id']
        api('pinChatMessage', {'chat_id': ADMIN, 'message_id': store_msg[0], 'disable_notification': True})


def who(u):
    name = ' '.join(x for x in (u.get('first_name'), u.get('last_name')) if x) or 'ללא שם'
    return name + (f' (@{u["username"]})' if u.get('username') else '')


def users_kb():
    rows = [[{'text': f'🗑 הסרה: {name[:28]}', 'callback_data': f'ur:{uid}'}] for uid, name in EXTRA.items()]
    return {'inline_keyboard': rows}


def admin_callback(cq, user, data):
    """Approve / deny / remove (admin only). Returns True when handled."""
    act, _, uid = data.partition(':')
    if act not in ('ua', 'ud', 'ur'):
        return False
    msg = cq.get('message') or {}
    if user != ADMIN:
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': '🔒 רק המנהל'})
        return True
    uid = int(uid)
    if act == 'ua':
        name = (msg.get('text') or '').split('\n')[1].replace('👤 ', '') if '\n' in (msg.get('text') or '') else str(uid)
        EXTRA[uid] = name
        save_users()
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': '✅ אושר'})
        api('editMessageText', {'chat_id': msg['chat']['id'], 'message_id': msg['message_id'],
                                'text': f'✅ אושר: {name}'})
        send(uid, '✅ קיבלת גישה לרובוט הרבנית סטודיו!\n\n' + HELP)
    elif act == 'ud':
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': 'נדחה'})
        api('editMessageText', {'chat_id': msg['chat']['id'], 'message_id': msg['message_id'],
                                'text': '❌ ' + ((msg.get('text') or '').split('\n')[1] if '\n' in (msg.get('text') or '') else str(uid)) + ' – נדחה'})
    else:
        name = EXTRA.pop(uid, str(uid))
        save_users()
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': '🗑 הוסר'})
        api('editMessageText', {'chat_id': msg['chat']['id'], 'message_id': msg['message_id'],
                                'text': users_text(), 'parse_mode': 'HTML', 'reply_markup': users_kb()})
    return True


def users_text():
    lines = ['👥 <b>מורשים לרובוט</b>', f'• {ADMIN} – מנהל']
    lines += [f'• {u} – (קבוע ב־Render)' for u in ALLOWED if u != ADMIN]
    lines += [f'• {u} – {n}' for u, n in EXTRA.items()]
    return '\n'.join(lines) + ('\n\nלהסרה – לחצו על הכפתור.' if EXTRA else '\n\nאנשים חדשים: שולחים לרובוט /start ואתם מאשרים בלחיצה.')
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
    '<b>ברוכים הבאים לסטודיו של הרבנית 📲</b>\n\n'
    'שלחו סרטון או תמונה (או כמה ביחד) עם טקסט מצורף ותקבלו קובץ מוכן עם אפשרויות עריכה מתקדמות &gt;&gt;\n\n'
    '__\n'
    'מילת פתיחה &gt; טקסט גוף &gt; קרדיט\n\n'
    'טקסט לדוגמה:\n'
    'מזל טוב! בכירי תעשיית המוזיקה בחגיגות יום הולדת לזמר החסידי המצליח באולמי אווניו בנמל התעופה\n\n'
    'צילום וידאו: דודי קפלר. צילום תמונה: דודי פרידמן.'
)

studio = None
BIG = bigfiles.BigFiles(TOKEN)   # files over 20 MB (needs TG_API_ID / TG_API_HASH)
jobs = queue.Queue()
lock = threading.Lock()
albums = {}       # media_group_id -> {'chat', 'user', 'items', 'caption', 'timer'}
pending = {}      # chat_id -> {'items': [...], 'text': str, 't': time}
prefs = {}        # chat_id -> {'format': 'story'|'post'}
sessions = {}     # sid -> a design waiting for approval (preview already sent)
SESSION_TTL = 45 * 60
ASSETS = os.path.join(HERE, 'assets')
# Fast builds on Modal (modal.com, $30/month free): set MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in Render.
MODAL_ON = bool(os.environ.get('MODAL_TOKEN_ID') and os.environ.get('MODAL_TOKEN_SECRET'))
MODAL_APP = os.environ.get('MODAL_APP', 'harabanit')
remote = {'ok': False, 'err': '', 'fn': None, 'dict': None}


def modal_setup():
    """Deploy the build function to Modal (image cached after the first time) and connect to it."""
    if not MODAL_ON:
        return
    try:
        import subprocess
        r = subprocess.run([sys.executable, '-m', 'modal', 'deploy', os.path.join(HERE, 'modal_app.py')],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            remote['err'] = (r.stderr or r.stdout)[-400:]
            print('modal deploy failed:', remote['err'], flush=True)
            return
        import modal
        remote['fn'] = modal.Function.from_name(MODAL_APP, 'build')
        remote['dict'] = modal.Dict.from_name(MODAL_APP + '-progress', create_if_missing=True)
        remote['ok'] = True
        print('modal ready', flush=True)
    except Exception as e:
        remote['err'] = str(e)[-400:]
        traceback.print_exc()


def remote_build(s, progress, max_bytes, caption):
    """Build the video on Modal; Modal sends it to the chat itself when it fits 50 MB.
    Returns (local_path or None, report dict)."""
    st = s['state']
    jid = uuid.uuid4().hex[:10]
    keys = ('kind', 'dur', 'audio', 'fps', 'acodec', 'w', 'h', 'vcodec')
    items = [dict({k: it[k] for k in keys if k in it}, url=f'{PUBLIC_URL}/m/{s["token"]}/{i}') for i, it in enumerate(st['items'])]
    with open(st['base'], 'rb') as f:
        base = f.read()
    with open(st['top'], 'rb') as f:
        top = f.read()
    # the clips are served to Modal through /m/<token>/<i>, so the session stays reachable while it builds
    sessions[s['sid']] = s
    tokens[s['token']] = s['sid']
    try:
        call = remote['fn'].spawn({'id': jid, 'items': items, 'geo': st['geo'], 'info': st['info'], 'max_bytes': max_bytes,
                                   'tg': {'token': TOKEN, 'chat': s['chat'], 'caption': caption}}, base, top)
        progress('video', 0.0)
        data = None
        while data is None:
            try:
                data = call.get(timeout=2)
            except TimeoutError:
                pr = remote['dict'].get(jid) if remote['dict'] is not None else None
                if pr and pr.get('stage') == 'video':
                    progress('video', pr.get('p') or 0)
                elif pr and pr.get('stage') == 'send':
                    progress('send')
    finally:
        sessions.pop(s['sid'], None)
        tokens.pop(s['token'], None)
        try:
            del remote['dict'][jid]
        except Exception:
            pass
    if data.get('sent'):
        return None, data
    out = os.path.join(s['work'], 'harabanit_remote.mp4')
    with open(out, 'wb') as f:
        f.write(data['data'])
    data.pop('data', None)
    return out, data
STICKER_IDS = {}  # colour -> Telegram file id of its logo sticker (uploaded once)
LAST = {}         # timings of the last video (shown on /status)
tokens = {}       # long random token -> sid (for the phone build page)
ME = {}           # the bot's own profile (username, has_main_web_app)
# The studio, opened inside Telegram to build the video on the phone (much faster than this server).
SITE_URL = os.environ.get('SITE_URL', 'https://pini8151gz.github.io/pini8151gz/harabanit/')
ORIGINS = {o.strip().rstrip('/') for o in os.environ.get('SITE_ORIGINS', 'https://pini8151gz.github.io').split(',') if o.strip()}
MAX_UPLOAD = 2 * 1024 * 1024 * 1024

# The studio's 16 brand colours (id, emoji, name) for the colour buttons.
COLORS = [('red', '🔴', 'אדום'), ('orange', '🟠', 'כתום'), ('yellow', '🟡', 'צהוב'), ('lime', '🟢', 'ירוק'),
          ('blue', '🔵', 'כחול'), ('purple', '🟣', 'סגול'),
          ('sky', '🩵', 'תכלת'), ('indigo', '🟦', 'אינדיגו'), ('forest', '🌲', 'ירוק כהה'), ('mint', '🌿', 'מנטה'),
          ('teal', '💠', 'טורקיז'), ('pink', '🩷', 'ורוד'), ('magenta', '🌸', 'מג׳נטה'), ('coral', '🪸', 'אלמוג'),
          ('silver', '⚪', 'כסף'), ('copper', '🟤', 'נחושת')]
COLOR = {c[0]: c for c in COLORS}


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


def edit_caption(chat, msg_id, text, kb=None):
    api('editMessageCaption', dict(chat_id=chat, message_id=msg_id, caption=text, parse_mode='HTML',
                                   reply_markup=kb))


def fmt_name(f):
    return 'סטורי 9:16' if f == 'story' else 'פוסט 4:5'


def color_label(theme):
    c = COLOR.get(theme)
    return f'{c[1]} {c[2]}' if c else '🎨 אוטומטי'


def preview_caption(s):
    info = s['state']['info']
    return f'👀 &gt; <b>תצוגה מקדימה</b>\n· {fmt_name(info["format"])} · {color_label(info.get("theme"))}'


def main_kb(s):
    sid, info = s['sid'], s['state']['info']
    f = info['format']
    return {'inline_keyboard': [
        [{'text': ('✓ ' if f == 'story' else '') + 'סטורי 9:16', 'callback_data': f'f:story:{sid}'},
         {'text': ('✓ ' if f == 'post' else '') + 'פוסט 4:5', 'callback_data': f'f:post:{sid}'}],
        [{'text': f'צבע: {color_label(info.get("theme"))} ▾', 'callback_data': f'cm:{sid}'}]] + (
        ([[edit_button(s)]] if phone_ok(s) and edit_button(s) else []) +
        [[{'text': '✅ אישור תצוגה', 'callback_data': f'ok:{sid}'}]])}


def edit_button(s):
    """'Full edit' opens the studio inside Telegram. Private chat: a web_app button.
    Groups don't allow those, so there it is a t.me link to the bot's main Mini App (when one is set in BotFather)."""
    if s['chat'] > 0:
        return {'text': '✏️ עריכה מלאה', 'web_app': {'url': f'{SITE_URL}?tg={s["token"]}'}}
    if ME.get('username') and ME.get('has_main_web_app'):
        return {'text': '✏️ עריכה מלאה', 'url': f'https://t.me/{ME["username"]}?startapp={s["token"]}'}
    return None


def phone_ok(s):
    """The phone can build one video or two videos (with a crossfade)."""
    its = s['items']
    return s['state']['mode'] == 'video' and 1 <= len(its) <= 2 and all(i['kind'] == 'video' for i in its)


def colors_kb(s):
    sid, cur = s['sid'], s['state']['info'].get('theme')
    rows, row = [], []
    for cid, emo, name in COLORS:
        row.append({'text': ('✓' if cid == cur else emo) + ' ' + name, 'callback_data': f'c:{cid}:{sid}'})
        if len(row) == 4:
            rows.append(row)
            row = []
    rows.append([{'text': '↩️ חזרה', 'callback_data': f'cb:{sid}'}])
    return {'inline_keyboard': rows}


def download(file_id, dest_dir):
    info = api('getFile', {'file_id': file_id})
    if not info.get('ok'):
        raise RuntimeError(info.get('description', 'getFile failed'))
    path = info['result']['file_path']
    dest = os.path.join(dest_dir, f'{uuid.uuid4().hex[:8]}_{os.path.basename(path)}')
    with urllib.request.urlopen(FILE_API + urllib.parse.quote(path), timeout=180) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    return dest


URL_RE = re.compile(r'https?://[^\s<>"]+')
MAX_URL_BYTES = 2 * 1024 * 1024 * 1024


def direct_url(url):
    """Turn share links into direct download links (Google Drive, Dropbox)."""
    m = re.search(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=download&)?id=)([\w-]{10,})', url)
    if m:
        return f'https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t'
    if 'dropbox.com' in url:
        url = re.sub(r'([?&])dl=0', r'\1dl=1', url)
        if 'dl=1' not in url and 'raw=1' not in url:
            url += ('&' if '?' in url else '?') + 'dl=1'
    return url


def download_url(url, dest_dir, progress=None):
    """Download a file from a link (up to 2 GB), with progress."""
    req = urllib.request.Request(direct_url(url), headers={'User-Agent': 'Mozilla/5.0 (HarabanitBot)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get('Content-Type', '')
        if 'text/html' in ctype:
            raise RuntimeError('הקישור לא מוביל לקובץ ישיר. בגוגל דרייב ודרופבוקס צריך שיתוף "לכל מי שיש את הקישור".')
        total = int(r.headers.get('Content-Length') or 0)
        if total > MAX_URL_BYTES:
            raise RuntimeError('הקובץ בקישור גדול מ־2GB.')
        name = re.sub(r'[^\w.\-]', '_', os.path.basename(urllib.parse.urlparse(r.geturl()).path)) or 'media'
        dest = os.path.join(dest_dir, f'{uuid.uuid4().hex[:8]}_{name}')
        done, last = 0, 0.0
        with open(dest, 'wb') as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done > MAX_URL_BYTES:
                    raise RuntimeError('הקובץ בקישור גדול מ־2GB.')
                if progress and time.time() - last > 3:
                    last = time.time()
                    progress(done, total)
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


def handle_callback(cq):
    user = (cq.get('from') or {}).get('id')
    data = cq.get('data') or ''

    def answer(text=''):
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': text or None})
    if admin_callback(cq, user, data):
        return
    if not is_allowed(user):
        answer('🔒 אין הרשאה')
        return
    parts = data.split(':')
    sid = parts[-1]
    s = sessions.get(sid)
    if not s:
        answer('⌛ פג התוקף – שלחו שוב את החומר')
        return
    act = parts[0]
    if act == 'cm':
        answer()
        api('editMessageReplyMarkup', {'chat_id': s['chat'], 'message_id': s['pmsg'], 'reply_markup': colors_kb(s)})
        return
    if act == 'cb':
        answer()
        api('editMessageReplyMarkup', {'chat_id': s['chat'], 'message_id': s['pmsg'], 'reply_markup': main_kb(s)})
        return
    if s.get('busy'):
        answer('⏳ רגע, עדיין עובד…')
        return
    info = s['state']['info']
    if act == 'f':
        if parts[1] == info['format']:
            answer()
            return
        s['meta']['format'] = parts[1]
        prefs.setdefault(s['chat'], {})['format'] = parts[1]
    elif act == 'c':
        if parts[1] == info.get('theme'):
            answer()
            api('editMessageReplyMarkup', {'chat_id': s['chat'], 'message_id': s['pmsg'], 'reply_markup': main_kb(s)})
            return
        s['meta']['theme'] = parts[1]
    elif act != 'ok':
        answer()
        return
    s['busy'] = True
    ahead = jobs.qsize()
    answer(('✅ מתחיל' if act == 'ok' else '🎨 מעצב מחדש…') + (f' (בתור: {ahead})' if ahead else ''))
    jobs.put({'type': 'approve' if act == 'ok' else 'restyle', 'sid': sid, 'chat': s['chat']})


def handle_update(upd):
    if upd.get('callback_query'):
        handle_callback(upd['callback_query'])
        return
    msg = upd.get('message') or upd.get('channel_post')
    if not msg:
        return
    chat = msg['chat']['id']
    user = (msg.get('from') or {}).get('id', chat)
    text = (msg.get('text') or '').strip()

    if text.startswith('/id'):
        send(chat, f'המזהה שלך: <code>{user}</code>')
        return
    if not is_allowed(user):
        if chat < 0 and not text.startswith('/start'):
            return   # in a group: people without access are simply ignored (no noise)
        if ADMIN and time.time() - asked.get(user, 0) > 600:
            asked[user] = time.time()
            send(ADMIN, f'🙋 <b>בקשת גישה לרובוט</b>\n👤 {who(msg.get("from") or {})}\nמזהה: <code>{user}</code>',
                 reply_markup={'inline_keyboard': [[{'text': '✅ אשר', 'callback_data': f'ua:{user}'},
                                                    {'text': '❌ דחה', 'callback_data': f'ud:{user}'}]]})
            send(chat, '🔒 עדיין אין לך גישה לרובוט.\n📨 שלחתי בקשה למנהל – תקבל הודעה ברגע שיאשר.')
        else:
            send(chat, '⏳ הבקשה שלך כבר אצל המנהל. תקבל הודעה ברגע שיאשר.')
        return
    if text.startswith('/users') and user == ADMIN:
        send(chat, users_text(), reply_markup=users_kb())
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
        if item['size'] and item['size'] > MAX_DOWNLOAD and not BIG.enabled:
            send(chat, '⚠️ הקובץ גדול מ־20MB. כדי לקבל קבצים גדולים (עד 2GB) צריך להוסיף ב־Render את TG_API_ID ו־TG_API_HASH.\nבינתיים אפשר לשלוח גרסה קצרה או דחוסה יותר.')
            return
        item['order'] = msg['message_id']
        item['msg_id'] = msg['message_id']
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
    urls = URL_RE.findall(text) if text and not text.startswith('/') else []
    if urls:
        rest = URL_RE.sub('', text).strip()
        items = [{'url': u.rstrip('.,)'), 'kind': None, 'size': 0, 'order': i} for i, u in enumerate(urls)]
        arrived(chat, items, rest)
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
    jobs.put({'type': 'new', 'chat': chat, 'items': items, 'caption': caption, 'msg': msg_id})


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
        cleanup_sessions()
        try:
            kind = job.get('type', 'new')
            if kind == 'new':
                process(job)
            elif kind == 'restyle':
                restyle(job)
            else:
                approve(job)
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
            s = sessions.get(job.get('sid'))
            if s:
                s['busy'] = False
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
        items = []
        for n, it in enumerate(job['items'], 1):
            if it.get('url'):
                label = f' {n}/{len(job["items"])}' if len(job['items']) > 1 else ''

                def url_progress(done, total, label=label):
                    mb = done / 1048576
                    if total:
                        pct = int(done * 100 / total)
                        status(f'⬇️ מוריד מהקישור{label}\n' + '▰' * (pct // 10) + '▱' * (10 - pct // 10) + f' {pct}% · {mb:.0f}MB')
                    else:
                        status(f'⬇️ מוריד מהקישור{label}\n{mb:.0f}MB')
                path = download_url(it['url'], work, url_progress)
                items.append({'path': path, 'kind': engine.kind_of(path)})
                continue
            big = it.get('size', 0) > MAX_DOWNLOAD
            path = None
            if not big:
                try:
                    path = download(it['file_id'], work)
                except RuntimeError as e:
                    if not (BIG.enabled and 'too big' in str(e).lower()):
                        raise
                    big = True
            if big:
                label = f' {n}/{len(job["items"])}' if len(job['items']) > 1 else ''
                mb = round(it.get('size', 0) / 1048576)

                def dl_progress(p, label=label, mb=mb):
                    pct = int(p * 100)
                    status(f'⬇️ מוריד קובץ גדול{label} ({mb}MB)\n' + '▰' * (pct // 10) + '▱' * (10 - pct // 10) + f' {pct}%')
                path = BIG.download(it['msg_id'], work, dl_progress)
            items.append({'path': path, 'kind': it['kind']})

        items, corner = engine.split_corner(items)
        status('🎨 מעצב בשפת המותג…' + ('\n🔍 מנתח את התמונה לפינה…' if corner else ''), True)
        state = engine.prepare(studio, items, meta, work, corner=corner and corner['path'])
        sid = uuid.uuid4().hex[:8]
        sess = {'sid': sid, 'chat': chat, 'work': work, 'items': items, 'meta': meta, 'state': state,
                'corner': corner and corner['path'],
                't': time.time(), 'busy': False, 'token': uuid.uuid4().hex + uuid.uuid4().hex[:16]}
        tokens[sess['token']] = sid
        r = api('sendPhoto', {'chat_id': str(chat), 'caption': preview_caption(sess), 'parse_mode': 'HTML',
                              'reply_markup': main_kb(sess)}, {'photo': state['preview']}, timeout=120)
        if not r.get('ok'):
            raise RuntimeError(r.get('description', 'send failed'))
        sess['pmsg'] = r['result']['message_id']
        sessions[sid] = sess
        work = None   # kept for the approval step
        if msg_id:
            api('deleteMessage', {'chat_id': chat, 'message_id': msg_id})
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


def cleanup_sessions():
    now = time.time()
    for sid, s in list(sessions.items()):
        if now - s['t'] > SESSION_TTL and not s.get('busy'):
            sessions.pop(sid, None)
            tokens.pop(s.get('token'), None)
            shutil.rmtree(s['work'], ignore_errors=True)
            api('editMessageReplyMarkup', {'chat_id': s['chat'], 'message_id': s['pmsg'], 'reply_markup': {'inline_keyboard': []}})


def restyle(job):
    s = sessions.get(job['sid'])
    if not s:
        return
    try:
        s['state'] = engine.prepare(studio, s['items'], s['meta'], s['work'], corner=s.get('corner'))
        s['t'] = time.time()
        media = {'type': 'photo', 'media': 'attach://photo', 'caption': preview_caption(s), 'parse_mode': 'HTML'}
        r = api('editMessageMedia', {'chat_id': str(s['chat']), 'message_id': str(s['pmsg']), 'media': media,
                                     'reply_markup': main_kb(s)}, {'photo': s['state']['preview']}, timeout=120)
        if not r.get('ok') and 'not modified' not in r.get('description', ''):
            raise RuntimeError(r.get('description', 'edit failed'))
    finally:
        s['busy'] = False


def approve(job):
    s = sessions.pop(job['sid'], None)
    if not s:
        return
    tokens.pop(s.get('token'), None)
    chat, pmsg, info = s['chat'], s['pmsg'], s['state']['info']
    head = f'{fmt_name(info["format"])} · {color_label(info.get("theme"))}'
    last, stk = [0.0], [None]
    # While the video is built, a sticker of the logo filling with colour plays under the preview
    # (stickers loop on their own, no play button); the real progress is in the preview's caption.
    sticker = None
    if s['state']['mode'] == 'video':
        sticker = info.get('theme') if os.path.exists(os.path.join(ASSETS, f'fill_{info.get("theme")}.webm')) else 'red'

    def drop_sticker():
        if stk[0]:
            api('deleteMessage', {'chat_id': chat, 'message_id': stk[0]})
            stk[0] = None

    def status(text, force=False, p=None):
        now = time.time()
        if sticker and stk[0] is None:
            stk[0] = 0
            fid = STICKER_IDS.get(sticker)
            r = (api('sendSticker', {'chat_id': str(chat), 'sticker': fid, 'disable_notification': True}) if fid else
                 api('sendSticker', {'chat_id': str(chat), 'disable_notification': 'true'},
                     {'sticker': os.path.join(ASSETS, f'fill_{sticker}.webm')}, timeout=60))
            if r.get('ok'):
                stk[0] = r['result']['message_id']
                got = (r['result'].get('sticker') or {}).get('file_id')
                if got:
                    STICKER_IDS[sticker] = got   # next time: no upload
        if force or now - last[0] > 3:
            last[0] = now
            edit_caption(chat, pmsg, f'{text}\n<i>{head}</i>')
    try:
        t_video = [None]

        def progress(stage, p=None):
            if stage == 'send':
                status('📤 שולח…', True)
                return
            if stage == 'video':
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
                status(f'🎬 מרכיב את הסרטון\n{bar} {pct}%{eta}', p=p)

        if s['state']['mode'] == 'video':
            status('🎬 מרכיב את הסרטון\n▱▱▱▱▱▱▱▱▱▱ 0%', True, p=0)
        max_b = 1900 * 1024 * 1024 if BIG.enabled else 48 * 1024 * 1024
        out, sent, how = None, False, 'שרת'
        t_start = time.time()
        caption = f'✅ מוכן · {fmt_name(info["format"])}'
        if remote['ok'] and s['state']['mode'] == 'video' and PUBLIC_URL:
            try:
                out, rep = remote_build(s, progress, max_b, caption)
                sent, how = rep.get('sent', False), 'Modal'
                LAST['modal'] = rep
                if not sent:
                    kind, info = 'video', dict(s['state']['info'], dur=engine.probe(out)['dur'])
            except Exception as e:
                traceback.print_exc()
                LAST['modal_error'] = str(e)[-300:]
                out, sent = None, False   # fall back to building here
        if out is None and not sent:
            out, kind, info = engine.finish(studio, s['state'], s['work'], progress, max_bytes=max_b)
        t_built = time.time()
        if sent:
            r = {'ok': True}
            kind = 'video'
        elif os.path.getsize(out) > 49 * 1024 * 1024 and BIG.enabled:
            status('📤 שולח…', True)
            BIG.send(chat, out, caption, video=(kind == 'video'), w=info['W'], h=info['H'], dur=info.get('dur', 0))
            r = {'ok': True}
        elif kind == 'image':
            status('📤 שולח…', True)
            r = api('sendDocument', {'chat_id': str(chat), 'caption': caption + ' · איכות מלאה'}, {'document': out}, timeout=300)
        else:
            status('📤 שולח…', True)
            r = api('sendVideo', {'chat_id': str(chat), 'caption': caption, 'supports_streaming': 'true',
                                  'width': str(info['W']), 'height': str(info['H']), 'duration': str(int(info.get('dur', 0)))},
                    {'video': out}, timeout=600)
        if not r.get('ok'):
            raise RuntimeError(r.get('description', 'send failed'))
        LAST.update(at=time.strftime('%H:%M:%S'), how=how, total=round(time.time() - t_start, 1),
                    build=round(t_built - t_start, 1), send=round(time.time() - t_built, 1),
                    size_mb=round(os.path.getsize(out) / 1048576, 1) if out else (LAST.get('modal') or {}).get('size', 0) // 1048576)
        print('job timing:', LAST, flush=True)
        drop_sticker()
        if kind == 'video':
            api('deleteMessage', {'chat_id': chat, 'message_id': pmsg})
        else:
            edit_caption(chat, pmsg, f'✅ מוכן · {head}')
    except Exception:
        # Let the user try again from the same preview.
        s['busy'] = False
        s['t'] = time.time()
        sessions[s['sid']] = s
        tokens[s['token']] = s['sid']
        drop_sticker()
        edit_caption(chat, pmsg, preview_caption(s), main_kb(s))
        raise
    shutil.rmtree(s['work'], ignore_errors=True)


# ---------------------------------------------------------------- web server (webhook + health)
def check_init_data(init):
    """Telegram Mini App sign-in: returns the user id if the data was signed by Telegram for this bot."""
    try:
        pairs = dict(urllib.parse.parse_qsl(init or '', keep_blank_values=True))
        got = pairs.pop('hash', '')
        dcs = '\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
        key = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
        if not got or not hmac.compare_digest(hmac.new(key, dcs.encode(), hashlib.sha256).hexdigest(), got):
            return None
        if time.time() - int(pairs.get('auth_date', '0')) > 24 * 3600:
            return None
        return int(json.loads(pairs.get('user', '{}')).get('id', 0)) or None
    except Exception:
        return None


def corner_file(s):
    for n in ('corner.png', 'corner.jpg'):
        p = os.path.join(s['work'], n)
        if os.path.exists(p):
            return p
    return s.get('corner')


def corner_matte(s):
    """The person mask the server already found for the corner photo (the phone reuses it)."""
    try:
        with open(os.path.join(s['work'], 'corner_matte.json')) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def phone_job(token):
    sid = tokens.get(token or '')
    s = sessions.get(sid) if sid else None
    return s if s and phone_ok(s) else None


def deliver_phone_result(s, path, is_image=False):
    """A result made on the phone arrived: send it to the chat and close the preview."""
    chat = s['chat']
    if is_image:
        p = engine.probe(path)
        caption = f'✅ מוכן · {fmt_name("story" if p["h"] / max(1, p["w"]) > 1.5 else "post")} · איכות מלאה'
        r = api('sendDocument', {'chat_id': str(chat), 'caption': caption}, {'document': path}, timeout=300)
        if not r.get('ok'):
            raise RuntimeError(r.get('description', 'send failed'))
        return close_session(s)
    path, p = engine.playable(path, s['work'])
    caption = f'✅ מוכן · {fmt_name("story" if p["h"] / max(1, p["w"]) > 1.5 else "post")}'
    if BIG.enabled:
        BIG.send(chat, path, caption, video=True, w=p['w'], h=p['h'], dur=p['dur'])
    else:
        r = api('sendVideo', {'chat_id': str(chat), 'caption': caption, 'supports_streaming': 'true',
                              'width': str(p['w']), 'height': str(p['h']), 'duration': str(int(p['dur']))},
                {'video': path}, timeout=600)
        if not r.get('ok'):
            raise RuntimeError(r.get('description', 'send failed'))
    close_session(s)


def close_session(s):
    sessions.pop(s['sid'], None)
    tokens.pop(s.get('token'), None)
    api('deleteMessage', {'chat_id': s['chat'], 'message_id': s['pmsg']})
    shutil.rmtree(s['work'], ignore_errors=True)


class Hook(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def cors(self):
        origin = (self.headers.get('Origin') or '').rstrip('/')
        if origin in ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'X-Init-Data, Content-Type')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Max-Age', '600')

    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parts = self.path.split('?')[0].strip('/').split('/')
        if parts[0] == 'j' and len(parts) == 2:
            s = phone_job(parts[1])
            if not s:
                return self.reply(410, {'ok': False, 'error': 'expired'})
            info, meta = s['state']['info'], s['meta']
            return self.reply(200, {'ok': True, 'format': info['format'], 'theme': info.get('theme'),
                                    'fx': info.get('fx', .5), 'fy': info.get('fy', .5),
                                    'kicker': meta.get('kicker', ''), 'head': meta.get('head', ''),
                                    'extra': meta.get('extra', ''), 'credits': meta.get('credits', []),
                                    'items': [{'url': f'/m/{parts[1]}/{i}', 'kind': it['kind'],
                                               'size': os.path.getsize(it['path'])} for i, it in enumerate(s['items'])],
                                    'corner': ({'url': f'/m/{parts[1]}/c', 'size': os.path.getsize(corner_file(s)),
                                                'matte': corner_matte(s)} if s.get('corner') else None)})
        if parts[0] == 'm' and len(parts) == 3:
            sid = tokens.get(parts[1] or '')
            s = sessions.get(sid) if sid else None
            try:
                path = (corner_file(s) if parts[2] == 'c' else s['items'][int(parts[2])]['path']) if s else None
            except (ValueError, IndexError):
                path = None
            if not path or not os.path.exists(path):
                return self.reply(410, {'ok': False, 'error': 'expired'})
            size = os.path.getsize(path)
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', mimetypes.guess_type(path)[0] or 'video/mp4')
            self.send_header('Content-Length', str(size))
            self.end_headers()
            with open(path, 'rb') as f:
                shutil.copyfileobj(f, self.wfile, 1 << 20)
            return
        body ='הרבנית סטודיו – הרובוט פעיל · גרסה ' + os.environ.get('RENDER_GIT_COMMIT', 'local')[:7]
        if self.path.startswith('/status'):
            info = api('getWebhookInfo').get('result', {})
            body += f"\nwebhook: {bool(info.get('url'))} pending: {info.get('pending_update_count')} error: {info.get('last_error_message', '-')}"
            body += f"\nallowed users: {len(ALLOWED) + len(EXTRA)}"
            body += f"\nbig files (2GB): {'on' if BIG.enabled else 'off – add TG_API_ID + TG_API_HASH'}"
            body += f"\nlast video: {json.dumps(LAST, ensure_ascii=False)}"
            body += f"\nfast builds (Modal): {'on' if remote['ok'] else ('error: ' + remote['err'] if remote['err'] else ('starting…' if MODAL_ON else 'off – add MODAL_TOKEN_ID + MODAL_TOKEN_SECRET'))}"
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def upload(self, token):
        length = int(self.headers.get('Content-Length') or 0)
        user = check_init_data(self.headers.get('X-Init-Data'))
        s = phone_job(token)
        if not user or not is_allowed(user):
            self.close_connection = True
            return self.reply(403, {'ok': False, 'error': 'forbidden'})
        if not s:
            self.close_connection = True
            return self.reply(410, {'ok': False, 'error': 'expired'})
        if not 0 < length <= MAX_UPLOAD:
            self.close_connection = True
            return self.reply(413, {'ok': False, 'error': 'size'})
        if s.get('busy'):
            self.close_connection = True
            return self.reply(409, {'ok': False, 'error': 'busy'})
        s['busy'] = True
        try:
            is_image = (self.headers.get('Content-Type') or '').startswith('image/')
            path = os.path.join(s['work'], f'phone_{uuid.uuid4().hex[:6]}.{"jpg" if is_image else "mp4"}')
            left = length
            with open(path, 'wb') as f:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        raise RuntimeError('upload cut')
                    f.write(chunk)
                    left -= len(chunk)
            deliver_phone_result(s, path, is_image)
            self.reply(200, {'ok': True})
        except Exception as e:
            traceback.print_exc()
            s['busy'] = False
            self.close_connection = True
            self.reply(500, {'ok': False, 'error': str(e)[:200]})

    def do_POST(self):
        parts = self.path.split('?')[0].strip('/').split('/')
        if parts[0] == 'u' and len(parts) == 2:
            return self.upload(parts[1])
        if self.path != '/tg' or (SECRET and self.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET):
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length') or 0)
        try:
            upd = json.loads(self.rfile.read(length).decode() or '{}')
        except ValueError:
            upd = {}
        self.send_response(200)
        self.send_header('Content-Length', '0')
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
        r = api('getUpdates', {'timeout': 50, 'offset': offset, 'allowed_updates': ['message', 'callback_query']}, timeout=70)
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
    try:
        ME.update(api('getMe').get('result') or {})
        print('bot:', ME.get('username'), 'main mini app:', ME.get('has_main_web_app'), flush=True)
    except Exception:
        traceback.print_exc()
    try:
        load_users()
        print('approved users:', len(EXTRA), flush=True)
    except Exception:
        traceback.print_exc()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=keep_awake, daemon=True).start()
    threading.Thread(target=modal_setup, daemon=True).start()
    if MODAL_ON:
        engine.OUT_W = int(os.environ.get('OUT_W', '1080'))   # the fast server can afford full quality
    cmds = [{'command': 'start', 'description': 'הסבר קצר'},
            {'command': 'story', 'description': 'סטורי 9:16 כברירת מחדל'},
            {'command': 'post', 'description': 'פוסט 4:5 כברירת מחדל'},
            {'command': 'id', 'description': 'המזהה שלי'}]
    api('setMyCommands', {'commands': cmds})
    if ADMIN:   # the admin also sees /users
        api('setMyCommands', {'commands': cmds + [{'command': 'users', 'description': 'ניהול מורשים'}],
                              'scope': {'type': 'chat', 'chat_id': ADMIN}})
    if PUBLIC_URL:
        r = api('setWebhook', {'url': PUBLIC_URL + '/tg', 'secret_token': SECRET or None,
                               'allowed_updates': ['message', 'callback_query'], 'max_connections': 10})
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
