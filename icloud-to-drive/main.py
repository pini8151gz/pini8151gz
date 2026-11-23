"""
שרת Flask: התחברות עם גוגל (OAuth 2.0) ונקודת קצה אחת להעברת אלבום.

ניהול הסשן:
- הטוקנים של גוגל נשמרים אך ורק ב-cookie של הסשן, מוצפנים (Fernet) עם מפתח
  שנגזר מ-SECRET_KEY. השרת עצמו לא שומר שום דבר – אין מסד נתונים ואין קבצים.
- ה-cookie הוא "session cookie": נמחק כשהדפדפן נסגר, כך שאין שמירה בין סשנים.
- הגישה הזו stateless, ולכן עובדת גם כש-Cloud Run מריץ כמה מופעים במקביל.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, Response, jsonify, redirect, request, session, url_for
from google.oauth2.credentials import Credentials
from werkzeug.middleware.proxy_fix import ProxyFix

import icloud
from drive import DriveClient, DriveFatalError
from transfer import run_transfer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("icloud-to-drive")

# ה-scope היחיד: גישה רק לקבצים שהאפליקציה עצמה יוצרת. אין גישה לשאר הדרייב.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# K_SERVICE מוגדר אוטומטית בכל קונטיינר של Cloud Run
ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if ON_CLOUD_RUN:
        raise RuntimeError("חובה להגדיר את משתנה הסביבה SECRET_KEY")
    SECRET_KEY = secrets.token_hex(32)  # בהרצה מקומית: מפתח זמני, מתחלף בכל הפעלה

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,  # JavaScript בדף לא יכול לקרוא את ה-cookie
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=ON_CLOUD_RUN,  # מקומית עובדים ב-http, בענן רק https
    SESSION_PERMANENT=False,
    MAX_CONTENT_LENGTH=16 * 1024,
)
# Cloud Run יושב מאחורי proxy; בלי זה Flask יחשוב שהכתובת היא http ולא https
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()))


# ---------- שמירת הטוקנים בסשן ----------


def _save_credentials(credentials: Credentials) -> None:
    payload = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
    }
    session["creds"] = _fernet.encrypt(json.dumps(payload).encode()).decode()


def _load_credentials() -> Credentials | None:
    blob = session.get("creds")
    if not blob:
        return None
    try:
        data = json.loads(_fernet.decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        session.clear()
        return None
    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES,
        expiry=datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None,
    )


def _redirect_uri() -> str:
    # אפשר לקבע ידנית עם OAUTH_REDIRECT_URI; אחרת נגזר מהכתובת שבה ניגשו לשרת
    return os.environ.get("OAUTH_REDIRECT_URI") or url_for("auth_callback", _external=True)


def _error(message: str, status: int):
    return jsonify({"error": message}), status


# ---------- דפים ----------


@app.get("/")
def index():
    response = app.send_static_file("index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/healthz")
def healthz():
    return "ok"


# ---------- OAuth ----------


@app.get("/auth/login")
def auth_login():
    """שלב 1: שולחים את המשתמש למסך ההסכמה של גוגל."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return "חסרים GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET בהגדרות השרת.", 500

    # state אקראי שנבדק בחזרה – מגן מפני CSRF על תהליך ההתחברות
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",  # מקבלים refresh token, להעלאות שנמשכות מעל שעה
        "prompt": "consent",
    }
    return redirect(f"{AUTH_URL}?{urlencode(params)}")


@app.get("/auth/callback")
def auth_callback():
    """שלב 2: גוגל מחזירה code, ואנחנו מחליפים אותו בטוקנים."""
    expected_state = session.pop("oauth_state", None)
    if request.args.get("error"):
        return redirect("/?auth=cancelled")
    if not expected_state or not secrets.compare_digest(expected_state, request.args.get("state", "")):
        return redirect("/?auth=failed")

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": request.args.get("code", ""),
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        tokens = response.json()
    except (requests.RequestException, ValueError):
        return redirect("/?auth=failed")

    if response.status_code != 200 or "access_token" not in tokens:
        log.warning("החלפת הקוד נכשלה: %s", tokens.get("error"))
        return redirect("/?auth=failed")

    # המשתמש יכול לבטל את הסימון של ההרשאה במסך ההסכמה – בודקים שהיא באמת ניתנה
    if SCOPES[0] not in tokens.get("scope", "").split():
        return redirect("/?auth=scope")

    # google-auth מצפה ל-expiry כ-datetime "נאיבי" ב-UTC
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    credentials = Credentials(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        token_uri=TOKEN_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES,
        expiry=expiry,
    )

    try:
        user = DriveClient(credentials).user_info()
    except Exception:  # noqa: BLE001
        log.exception("קריאת פרטי המשתמש נכשלה")
        return redirect("/?auth=failed")

    session.clear()
    _save_credentials(credentials)
    session["user"] = {
        "name": user.get("displayName") or user.get("emailAddress") or "משתמש",
        "email": user.get("emailAddress", ""),
        "picture": user.get("photoLink", ""),
    }
    return redirect("/")


@app.post("/auth/logout")
def auth_logout():
    """התנתקות: מבטלים את הטוקן אצל גוגל ומוחקים את הסשן."""
    credentials = _load_credentials()
    if credentials:
        try:
            requests.post(
                REVOKE_URL, data={"token": credentials.refresh_token or credentials.token}, timeout=10
            )
        except requests.RequestException:
            pass  # גם אם הביטול נכשל – הסשן נמחק
    session.clear()
    return jsonify({"ok": True})


# ---------- API ----------


@app.get("/api/me")
def api_me():
    if not _load_credentials():
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "user": session.get("user", {})})


@app.post("/api/upload")
def api_upload():
    """
    מעביר אלבום. התשובה היא זרם NDJSON – שורת JSON לכל אירוע התקדמות.
    דורשים Content-Type של JSON: דפדפן לא שולח כזה מאתר אחר בלי CORS,
    וזה (יחד עם SameSite=Lax) חוסם בקשות זדוניות מאתרים זרים.
    """
    if not request.is_json:
        return _error("בקשה לא תקינה.", 415)

    credentials = _load_credentials()
    if not credentials:
        return _error("צריך להתחבר עם גוגל לפני ההעלאה.", 401)

    link = (request.get_json(silent=True) or {}).get("url", "")
    try:
        icloud.extract_token(link)  # בדיקה מוקדמת, לפני שפותחים זרם
    except icloud.ICloudError as exc:
        return _error(str(exc), 400)

    # מרעננים את הטוקן עכשיו, כל עוד אפשר לעדכן את ה-cookie (אחרי תחילת הזרם כבר אי אפשר)
    drive = DriveClient(credentials)
    try:
        drive._token()  # noqa: SLF001
    except DriveFatalError as exc:
        session.clear()
        return _error(str(exc), 401)
    _save_credentials(credentials)

    def stream():
        for event in run_transfer(link, drive):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return Response(
        stream(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


if __name__ == "__main__":
    # הרצה מקומית לפיתוח בלבד. בענן מריצים עם gunicorn (ראו Dockerfile).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False, threaded=True)
