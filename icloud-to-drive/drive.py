"""
עבודה מול Google Drive: יצירת תיקייה והעלאת קבצים.

יצירת התיקייה ופרטי המשתמש נעשים עם google-api-python-client.
העלאת הקבצים עצמם נעשית ב-"resumable upload" ישירות עם requests, כדי שנוכל
להזרים (stream) את הקובץ מ-iCloud ל-Drive בלי להחזיק אותו בזיכרון או בדיסק –
חשוב ב-Cloud Run, שבו גם /tmp נספר כזיכרון.
"""

from __future__ import annotations

import threading

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 256 * 1024


class DriveError(Exception):
    """שגיאת העלאה רגילה – אפשר לנסות שוב."""


class DriveFatalError(Exception):
    """שגיאה שאין טעם לנסות אחריה שוב (למשל: נגמר המקום בדרייב)."""


class _SizedStream:
    """
    עוטף זרם הורדה כך ש-requests יידע את אורכו מראש וישלח Content-Length
    (אחרת הוא עובר ל-chunked encoding, ש-Drive לא מקבל בהעלאה כזו).
    """

    def __init__(self, raw, length: int):
        self._raw = raw
        self.len = length  # requests קורא את השדה הזה כדי לקבוע Content-Length

    def read(self, amount: int = -1) -> bytes:
        return self._raw.read(amount)

    def __iter__(self):
        while True:
            chunk = self._raw.read(CHUNK)
            if not chunk:
                return
            yield chunk


class DriveClient:
    """לקוח Drive לבקשה אחת. בטוח לשימוש מכמה threads במקביל."""

    def __init__(self, credentials: Credentials):
        self._credentials = credentials
        self._lock = threading.Lock()
        # Session אחד משותף: connection pool של requests בטוח לשימוש מקבילי
        self._http = requests.Session()

    # ---------- טוקן ----------

    def _token(self, force_refresh: bool = False) -> str:
        """מחזיר access token תקף; מרענן אותו אם פג (העלאות ארוכות עוברות שעה)."""
        with self._lock:
            if force_refresh or not self._credentials.valid:
                if not self._credentials.refresh_token:
                    raise DriveFatalError("פג תוקף ההתחברות לגוגל. התחבר מחדש ונסה שוב.")
                try:
                    self._credentials.refresh(Request())
                except Exception as exc:  # noqa: BLE001
                    raise DriveFatalError("פג תוקף ההתחברות לגוגל. התחבר מחדש ונסה שוב.") from exc
            return self._credentials.token

    def _service(self):
        return build("drive", "v3", credentials=self._credentials, cache_discovery=False)

    # ---------- פעולות ----------

    def user_info(self) -> dict:
        """שם ואימייל של המשתמש – עובד גם עם ה-scope המצומצם drive.file."""
        self._token()
        about = self._service().about().get(fields="user(displayName,emailAddress,photoLink)").execute()
        return about.get("user", {})

    def create_folder(self, name: str) -> dict:
        self._token()
        return (
            self._service()
            .files()
            .create(body={"name": name, "mimeType": FOLDER_MIME}, fields="id,webViewLink")
            .execute()
        )

    def upload_stream(self, raw, size: int, name: str, mime_type: str, folder_id: str) -> None:
        """
        מעלה קובץ בהזרמה, בשני שלבים:
        1. POST שפותח "סשן העלאה" ומחזיר כתובת ייעודית בכותרת Location
        2. PUT של תוכן הקובץ לכתובת הזו
        """
        start = self._start_session(size, name, mime_type, folder_id)
        try:
            result = self._http.put(
                start.headers["Location"],
                data=_SizedStream(raw, size),
                headers={"Content-Type": mime_type},
                timeout=(30, 600),
            )
        except requests.RequestException as exc:
            raise DriveError(f"החיבור ל-Drive נקטע: {exc}") from exc
        self._check(result)

    def _start_session(self, size: int, name: str, mime_type: str, folder_id: str) -> requests.Response:
        for attempt in (1, 2):
            try:
                response = self._http.post(
                    UPLOAD_URL,
                    params={"uploadType": "resumable", "fields": "id"},
                    json={"name": name, "parents": [folder_id]},
                    headers={
                        "Authorization": f"Bearer {self._token(force_refresh=attempt == 2)}",
                        "X-Upload-Content-Type": mime_type,
                        "X-Upload-Content-Length": str(size),
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                raise DriveError(f"החיבור ל-Drive נכשל: {exc}") from exc
            # 401 = הטוקן פג באמצע; מרעננים ומנסים פעם אחת נוספת
            if response.status_code == 401 and attempt == 1:
                continue
            self._check(response)
            if "Location" not in response.headers:
                raise DriveError("Drive לא החזיר כתובת העלאה.")
            return response
        raise DriveError("Drive דחה את ההתחברות.")

    @staticmethod
    def _check(response: requests.Response) -> None:
        if response.status_code in (200, 201):
            return
        text = response.text[:500]
        if "storageQuotaExceeded" in text:
            raise DriveFatalError("נגמר המקום הפנוי ב-Google Drive שלך.")
        if response.status_code == 401:
            raise DriveFatalError("פג תוקף ההתחברות לגוגל. התחבר מחדש ונסה שוב.")
        raise DriveError(f"Drive החזיר שגיאה {response.status_code}")
