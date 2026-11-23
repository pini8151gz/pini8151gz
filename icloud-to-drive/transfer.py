"""
התהליך המלא: iCloud → Google Drive.

run_transfer הוא generator שמחזיר "אירועים" (מילונים) תוך כדי עבודה.
השרת מזרים אותם לדפדפן שורה-שורה (NDJSON), וכך המשתמש רואה התקדמות חיה
והבקשה נשארת פתוחה – מה שמבטיח ש-Cloud Run ימשיך להקצות CPU עד הסיום.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

import requests

import icloud
from drive import DriveClient, DriveError, DriveFatalError

log = logging.getLogger(__name__)

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "6"))
ATTEMPTS_PER_FILE = 3
HEARTBEAT_SECONDS = 10
TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Jerusalem")


def _transfer_one(asset: icloud.Asset, drive: DriveClient, folder_id: str, cancel: threading.Event) -> None:
    """מוריד קובץ אחד מ-iCloud ומזרים אותו ישר ל-Drive. רץ בתוך thread."""
    last_error: Exception | None = None

    for attempt in range(1, ATTEMPTS_PER_FILE + 1):
        if cancel.is_set():
            raise DriveError("בוטל")
        try:
            # stream=True: הגוף לא נטען לזיכרון, אלא נקרא בהדרגה תוך כדי ההעלאה
            with requests.get(asset.url, stream=True, timeout=(15, 120)) as download:
                if download.status_code != 200:
                    raise DriveError(f"iCloud החזיר שגיאה {download.status_code}")
                size = int(download.headers.get("Content-Length") or asset.size or 0)
                if size <= 0:
                    raise DriveError("גודל הקובץ לא ידוע")
                drive.upload_stream(download.raw, size, asset.filename, asset.mime_type, folder_id)
            return
        except DriveFatalError:
            raise
        except (DriveError, requests.RequestException) as exc:
            last_error = exc
            log.warning("ניסיון %d נכשל עבור %s: %s", attempt, asset.filename, exc)
            time.sleep(1.5 * attempt)

    raise DriveError(str(last_error))


def run_transfer(link: str, drive: DriveClient) -> Iterator[dict]:
    """מריץ את כל התהליך ומחזיר אירועי התקדמות. האירוע האחרון הוא done או error."""
    try:
        token = icloud.extract_token(link)
        album = icloud.fetch_album(token)
        if not album.assets:
            yield {"type": "error", "message": "האלבום ריק – אין בו תמונות או סרטונים."}
            return

        yield {"type": "album", "name": album.name, "total": len(album.assets)}
        icloud.resolve_urls(album)

        today = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")
        folder_name = f"{album.name} {today}"
        folder = drive.create_folder(folder_name)
        folder_url = folder.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder['id']}"
    except icloud.ICloudError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    except DriveFatalError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    except Exception:  # noqa: BLE001
        log.exception("כשל בהכנת ההעברה")
        yield {"type": "error", "message": "לא הצלחנו ליצור תיקייה ב-Google Drive. נסה להתחבר מחדש."}
        return

    total = len(album.assets)
    done = 0
    failed: list[str] = []
    fatal: str | None = None
    cancel = threading.Event()

    # פריטים שאפל לא החזירה להם כתובת הורדה נספרים מראש ככישלון
    ready = []
    for asset in album.assets:
        if asset.url:
            ready.append(asset)
        else:
            failed.append(asset.filename)

    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        # כל הקבצים מועברים במקביל, MAX_WORKERS בו-זמנית
        pending = {executor.submit(_transfer_one, a, drive, folder["id"], cancel): a for a in ready}

        while pending:
            finished, _ = wait(pending, timeout=HEARTBEAT_SECONDS, return_when=FIRST_COMPLETED)
            if not finished:
                # שום קובץ לא הסתיים בזמן הזה – שולחים "דופק" כדי שהחיבור לא ייחשב רדום
                yield {"type": "ping"}
                continue

            for future in finished:
                asset = pending.pop(future)
                try:
                    future.result()
                    done += 1
                except DriveFatalError as exc:
                    fatal = str(exc)
                    failed.append(asset.filename)
                except Exception as exc:  # noqa: BLE001
                    log.warning("הקובץ %s נכשל סופית: %s", asset.filename, exc)
                    failed.append(asset.filename)

            if fatal:
                break
            yield {"type": "progress", "done": done, "failed": len(failed), "total": total}
    finally:
        # מגיעים לכאן גם אם המשתמש סגר את הדף באמצע (ה-generator נסגר)
        cancel.set()
        executor.shutdown(wait=False, cancel_futures=True)

    if fatal:
        yield {"type": "error", "message": fatal, "folder_url": folder_url if done else None}
    elif done == 0:
        yield {"type": "error", "message": "אף קובץ לא הועלה. נסה שוב בעוד כמה דקות."}
    else:
        yield {
            "type": "done",
            "folder_url": folder_url,
            "folder_name": folder_name,
            "uploaded": done,
            "total": total,
            "failed": failed,
        }
