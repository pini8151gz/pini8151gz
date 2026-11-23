"""
בדיקות מקצה לקצה מול שרת דמה מקומי שמתחזה גם ל-iCloud וגם ל-Drive.
הרצה:  pytest
"""

import hashlib
import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.oauth2.credentials import Credentials  # noqa: E402

import drive  # noqa: E402
import icloud  # noqa: E402
import main  # noqa: E402
import transfer  # noqa: E402

TOKEN = "B0aGWZuqDGrgQmN"
FILES = {
    "sum-photo-big": ("IMG_0001.JPG", os.urandom(300_000)),
    "sum-video": ("IMG_0002.MP4", os.urandom(1_200_000)),
    "sum-dup": ("IMG_0001.JPG", os.urandom(50_000)),  # שם זהה לקובץ הראשון
}


class FakeServer(BaseHTTPRequestHandler):
    uploads: dict = {}
    problems: list = []
    fail_first_put = False
    quota_exceeded = False
    empty_album = False

    def log_message(self, *args):
        pass

    def _json(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_POST(self):
        cls = type(self)
        body = self._body()
        host = self.headers["Host"]
        if self.path.endswith("/webstream"):
            photos = [] if cls.empty_album else [
                {"photoGuid": "g1", "derivatives": {
                    "342": {"checksum": "sum-photo-small", "fileSize": "1000"},
                    "2049": {"checksum": "sum-photo-big", "fileSize": "300000"}}},
                {"photoGuid": "g2", "mediaAssetType": "video", "derivatives": {
                    "PosterFrame": {"checksum": "sum-poster", "fileSize": "9999999"},
                    "720p": {"checksum": "sum-video", "fileSize": "1200000"}}},
                {"photoGuid": "g3", "derivatives": {"2049": {"checksum": "sum-dup", "fileSize": "50000"}}},
                {"photoGuid": "g4", "derivatives": {"2049": {"checksum": "sum-missing", "fileSize": "5"}}},
            ]
            self._json(200, {"streamName": "טיול לצפון", "photos": photos})
        elif self.path.endswith("/webasseturls"):
            assert json.loads(body)["photoGuids"]
            items = {c: {"url_location": host, "url_path": f"/asset/{c}/{name}?o=sig"}
                     for c, (name, _) in FILES.items()}
            self._json(200, {"items": items})
        elif self.path.startswith("/upload"):
            if cls.quota_exceeded:
                return self._json(403, {"error": {"errors": [{"reason": "storageQuotaExceeded"}]}})
            meta = json.loads(body)
            session_id = f"s{len(cls.uploads)}-{threading.get_ident()}"
            cls.uploads[session_id] = {"name": meta["name"], "parents": meta["parents"],
                                       "declared": int(self.headers["X-Upload-Content-Length"]),
                                       "auth": self.headers.get("Authorization")}
            self._json(200, {}, {"Location": f"http://{host}/put/{session_id}"})
        else:
            self._json(404, {})

    def do_GET(self):
        checksum = self.path.split("/")[2]
        data = FILES[checksum][1]
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        cls = type(self)
        if self.headers.get("Transfer-Encoding"):
            cls.problems.append("chunked upload")
        data = self._body()
        if cls.fail_first_put:
            cls.fail_first_put = False
            return self._json(503, {})
        cls.uploads[self.path.rsplit("/", 1)[1]]["sha"] = hashlib.sha256(data).hexdigest()
        self._json(200, {"id": "file"})


@pytest.fixture()
def fake(monkeypatch):
    FakeServer.uploads, FakeServer.problems = {}, []
    FakeServer.fail_first_put = FakeServer.quota_exceeded = FakeServer.empty_album = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    real_get = transfer.requests.get
    monkeypatch.setattr(icloud, "base_url_for", lambda token: f"{base}/{token}/sharedstreams/")
    monkeypatch.setattr(icloud, "ALLOWED_ASSET_SUFFIXES", (f":{server.server_port}",))
    # הקוד בונה כתובות https; השרת המקומי מדבר http
    monkeypatch.setattr(transfer.requests, "get", lambda url, **kw: real_get(url.replace("https://", "http://"), **kw))
    monkeypatch.setattr(drive, "UPLOAD_URL", f"{base}/upload")
    monkeypatch.setattr(drive.DriveClient, "create_folder",
                        lambda self, name: {"id": "FOLDER", "webViewLink": "https://drive.google.com/drive/folders/FOLDER", "name": name})
    monkeypatch.setattr(transfer.time, "sleep", lambda s: None)
    yield FakeServer
    server.shutdown()


def credentials():
    return Credentials(token="tok", refresh_token="r", token_uri="x", client_id="c", client_secret="s",
                       expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1))


def run(link=f"https://www.icloud.com/sharedalbum/#{TOKEN}"):
    return list(transfer.run_transfer(link, drive.DriveClient(credentials())))


def test_token_extraction():
    assert icloud.extract_token(f"https://www.icloud.com/sharedalbum/#{TOKEN}") == TOKEN
    assert icloud.extract_token(f"https://www.icloud.com/sharedalbum/he-il/#{TOKEN};abc") == TOKEN
    assert icloud.extract_token(f"  www.icloud.com/sharedalbum/#{TOKEN} ") == TOKEN
    for bad in ["", "https://example.com/sharedalbum/#" + TOKEN, "https://www.icloud.com/photos/#" + TOKEN,
                "https://www.icloud.com/sharedalbum/", "https://evil.com/?x=icloud.com/sharedalbum/#" + TOKEN]:
        with pytest.raises(icloud.ICloudError):
            icloud.extract_token(bad)


def test_partition_host():
    assert icloud.base_url_for("B0aGWZuqDGrgQmN").startswith("https://p36-sharedstreams.icloud.com/")
    assert icloud.base_url_for("A5GWZuqDGrgQmN").startswith("https://p05-sharedstreams.icloud.com/")


def test_full_transfer(fake):
    events = run()
    assert events[0] == {"type": "album", "name": "טיול לצפון", "total": 4}
    final = events[-1]
    assert final["type"] == "done" and final["uploaded"] == 3 and final["total"] == 4
    assert final["folder_url"].endswith("/FOLDER")
    assert final["folder_name"].startswith("טיול לצפון 20")
    assert len(final["failed"]) == 1  # הפריט שאין לו כתובת הורדה

    assert not fake.problems
    uploaded = {u["name"]: u for u in fake.uploads.values()}
    # הגרסה הגדולה נבחרה, PosterFrame לא נבחר, ושם כפול קיבל סיומת
    assert set(uploaded) == {"IMG_0001.JPG", "IMG_0002.MP4", "IMG_0001_0003.JPG"}
    expected = {"IMG_0001.JPG": "sum-photo-big", "IMG_0002.MP4": "sum-video", "IMG_0001_0003.JPG": "sum-dup"}
    for name, checksum in expected.items():
        assert uploaded[name]["sha"] == hashlib.sha256(FILES[checksum][1]).hexdigest()
        assert uploaded[name]["parents"] == ["FOLDER"]
        assert uploaded[name]["auth"] == "Bearer tok"


def test_retry_after_upload_failure(fake):
    fake.fail_first_put = True
    assert run()[-1]["uploaded"] == 3


def test_quota_exceeded_stops(fake):
    fake.quota_exceeded = True
    final = run()[-1]
    assert final["type"] == "error" and "נגמר המקום" in final["message"]


def test_empty_album(fake):
    fake.empty_album = True
    events = run()
    assert events == [{"type": "error", "message": "האלבום ריק – אין בו תמונות או סרטונים."}]


def test_http_api(fake):
    client = main.app.test_client()
    assert client.get("/api/me").get_json() == {"authenticated": False}
    assert client.get("/").status_code == 200

    payload = {"url": f"https://www.icloud.com/sharedalbum/#{TOKEN}"}
    assert client.post("/api/upload", json=payload).status_code == 401

    login = client.get("/auth/login")
    assert login.status_code == 302 and "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file&" in login.location

    with client.session_transaction() as session, main.app.test_request_context():
        from flask import session as flask_session
        main._save_credentials(credentials())
        session["creds"] = flask_session["creds"]
        session["user"] = {"name": "דנה", "email": "d@example.com"}

    assert client.get("/api/me").get_json()["user"]["name"] == "דנה"
    assert client.post("/api/upload", json={"url": "https://example.com"}).status_code == 400
    assert client.post("/api/upload", data="url=x").status_code == 415

    response = client.post("/api/upload", json=payload)
    lines = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
    assert lines[-1]["type"] == "done" and lines[-1]["uploaded"] == 3

    main.requests.post = lambda *a, **k: None  # לא פונים לגוגל בבדיקה
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/api/me").get_json() == {"authenticated": False}
