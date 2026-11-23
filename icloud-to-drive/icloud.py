"""
לקוח ל-API הלא-רשמי של אלבומים משותפים ב-iCloud ("Shared Streams").

=== איך ה-API עובד (אין תיעוד רשמי של אפל – זה מה שהאתר icloud.com עצמו עושה) ===

1. קישור של אלבום משותף נראה כך:
       https://www.icloud.com/sharedalbum/#B0aGWZuqDGrgQmN
   החלק שאחרי ה-# הוא ה-token של האלבום. הוא לא נשלח לשרת של אפל בבקשת ה-HTTP
   (fragment), ולכן צריך לחלץ אותו בעצמנו.

2. כל אלבום יושב על "מחיצה" (partition) אחרת בשרתי אפל. מספר המחיצה מקודד
   בתוך ה-token עצמו ב-Base62:
       - אם התו הראשון הוא 'A'  → המחיצה היא התו השני (ספרה אחת ב-Base62)
       - אחרת                    → המחיצה היא התווים 2-3 (שתי ספרות ב-Base62)
   ומכאן כתובת הבסיס:
       https://pNN-sharedstreams.icloud.com/<TOKEN>/sharedstreams/

3. POST אל  .../webstream  עם גוף  {"streamCtag": null}
   מחזיר JSON עם שם האלבום (streamName) ורשימת photos. לכל פריט יש photoGuid
   ומילון derivatives – גרסאות שונות של אותו קובץ (גדלים שונים), ולכל גרסה
   checksum ו-fileSize.
   * אם השרת מחזיר סטטוס 330, האלבום עבר למחיצה אחרת: בגוף התשובה יש
     "X-Apple-MMe-Host" עם שם השרת הנכון, וצריך לחזור על הבקשה מולו.

4. POST אל  .../webasseturls  עם גוף  {"photoGuids": [...]}
   מחזיר מילון items שממפה checksum → {url_location, url_path, url_expiry}.
   כתובת ההורדה היא  https://<url_location><url_path>  והיא חתומה ותקפה לזמן
   מוגבל (בערך שעה), לכן מבקשים אותה סמוך להורדה.
"""

from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import requests

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
TOKEN_RE = re.compile(r"^[A-Za-z0-9]{8,64}$")

# כמה photoGuids שולחים בכל בקשת webasseturls (האתר של אפל שולח במנות קטנות)
ASSET_URL_BATCH = 25
REQUEST_TIMEOUT = 30

# מותר להוריד רק מדומיינים של אפל – הגנה מפני SSRF אם התשובה תכיל כתובת זרה
ALLOWED_API_SUFFIX = ".icloud.com"
ALLOWED_ASSET_SUFFIXES = (".icloud-content.com", ".icloud.com", ".apple.com")

HEADERS = {
    "Origin": "https://www.icloud.com",
    "Referer": "https://www.icloud.com/",
    "Content-Type": "text/plain",
    "Accept": "*/*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
}


class ICloudError(Exception):
    """שגיאה שההודעה שלה (בעברית) מוצגת למשתמש כמו שהיא."""


@dataclass
class Asset:
    """קובץ אחד (תמונה או סרטון) באלבום."""

    guid: str
    checksums: list[str]  # גרסאות הקובץ, מהגדולה לקטנה
    sizes: dict[str, int]  # checksum → גודל בבייטים
    is_video: bool
    url: str | None = None
    size: int | None = None
    filename: str = ""
    mime_type: str = "application/octet-stream"


@dataclass
class Album:
    name: str
    assets: list[Asset]
    base_url: str


def extract_token(link: str) -> str:
    """מחלץ את ה-token מקישור של אלבום משותף (או מקבל token חשוף)."""
    link = (link or "").strip()
    if not link:
        raise ICloudError("לא הוזן קישור.")

    if TOKEN_RE.match(link):
        return link

    parsed = urlparse(link if "://" in link else "https://" + link)
    host = (parsed.hostname or "").lower()
    if not (host == "icloud.com" or host.endswith(".icloud.com")):
        raise ICloudError("זה לא קישור של iCloud. הקישור צריך להתחיל ב-https://www.icloud.com/sharedalbum/")
    if "sharedalbum" not in parsed.path:
        raise ICloudError("זה לא קישור של אלבום משותף. הקישור צריך להכיל /sharedalbum/")

    # ה-token נמצא אחרי ה-#. לפעמים מצורף אליו סיומת אחרי ';' שאינה חלק ממנו.
    token = parsed.fragment.split(";")[0].strip("/ ")
    if not TOKEN_RE.match(token):
        raise ICloudError("הקישור לא מכיל מזהה אלבום תקין (החלק שאחרי ה-#).")
    return token


def _base62_to_int(value: str) -> int:
    result = 0
    for char in value:
        result = result * 62 + BASE62.index(char)
    return result


def base_url_for(token: str) -> str:
    """מחשב את כתובת השרת (pNN-sharedstreams.icloud.com) מתוך ה-token."""
    partition = _base62_to_int(token[1]) if token[0] == "A" else _base62_to_int(token[1:3])
    return f"https://p{partition:02d}-sharedstreams.icloud.com/{token}/sharedstreams/"


def _post(session: requests.Session, url: str, payload: dict) -> requests.Response:
    try:
        return session.post(
            url, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=False
        )
    except requests.RequestException as exc:
        raise ICloudError("לא הצלחנו להתחבר לשרתי iCloud. נסה שוב בעוד רגע.") from exc


def _best_derivatives(photo: dict) -> tuple[list[str], dict[str, int]]:
    """
    בוחר את גרסאות הקובץ לפי גודל, מהגדולה לקטנה.
    ב-derivatives של סרטון יש גם "PosterFrame" – תמונת תצוגה מקדימה, לא הסרטון עצמו.
    """
    sizes: dict[str, int] = {}
    for key, derivative in (photo.get("derivatives") or {}).items():
        if key == "PosterFrame":
            continue
        checksum = derivative.get("checksum")
        if not checksum:
            continue
        try:
            sizes[checksum] = int(derivative.get("fileSize") or 0)
        except (TypeError, ValueError):
            sizes[checksum] = 0
    ordered = sorted(sizes, key=lambda c: sizes[c], reverse=True)
    return ordered, sizes


def fetch_album(token: str, session: requests.Session | None = None) -> Album:
    """שלב 3 בתיעוד למעלה: מביא את שם האלבום ורשימת הפריטים."""
    session = session or requests.Session()
    base_url = base_url_for(token)

    response = _post(session, base_url + "webstream", {"streamCtag": None})

    # 330 = האלבום נמצא במחיצה אחרת; שם השרת הנכון מגיע בגוף התשובה
    if response.status_code == 330:
        try:
            new_host = response.json().get("X-Apple-MMe-Host", "")
        except ValueError:
            new_host = ""
        if not new_host.endswith(ALLOWED_API_SUFFIX) or "/" in new_host:
            raise ICloudError("שרת iCloud החזיר תשובה לא צפויה.")
        base_url = f"https://{new_host}/{token}/sharedstreams/"
        response = _post(session, base_url + "webstream", {"streamCtag": None})

    if response.status_code in (400, 404, 410):
        raise ICloudError("האלבום לא נמצא. ייתכן שהקישור שגוי או שהשיתוף הציבורי בוטל.")
    if response.status_code != 200:
        raise ICloudError(f"שרת iCloud החזיר שגיאה ({response.status_code}). נסה שוב מאוחר יותר.")

    try:
        data = response.json()
    except ValueError as exc:
        raise ICloudError("שרת iCloud החזיר תשובה לא תקינה.") from exc

    assets = []
    for photo in data.get("photos") or []:
        checksums, sizes = _best_derivatives(photo)
        if not checksums or not photo.get("photoGuid"):
            continue
        assets.append(
            Asset(
                guid=photo["photoGuid"],
                checksums=checksums,
                sizes=sizes,
                is_video=(photo.get("mediaAssetType") == "video"),
            )
        )

    name = (data.get("streamName") or "").strip() or "אלבום משותף"
    return Album(name=name, assets=assets, base_url=base_url)


def resolve_urls(album: Album, session: requests.Session | None = None) -> None:
    """שלב 4 בתיעוד למעלה: ממלא לכל פריט כתובת הורדה, שם קובץ וסוג MIME."""
    session = session or requests.Session()
    items: dict[str, dict] = {}

    for start in range(0, len(album.assets), ASSET_URL_BATCH):
        batch = album.assets[start : start + ASSET_URL_BATCH]
        response = _post(
            session, album.base_url + "webasseturls", {"photoGuids": [a.guid for a in batch]}
        )
        if response.status_code != 200:
            raise ICloudError(f"לא הצלחנו לקבל כתובות הורדה מ-iCloud ({response.status_code}).")
        try:
            items.update(response.json().get("items") or {})
        except ValueError as exc:
            raise ICloudError("שרת iCloud החזיר תשובה לא תקינה.") from exc

    used_names: set[str] = set()
    for index, asset in enumerate(album.assets, start=1):
        # לוקחים את הגרסה הגדולה ביותר שיש לה כתובת הורדה
        for checksum in asset.checksums:
            item = items.get(checksum)
            if not item:
                continue
            location = item.get("url_location", "")
            path = item.get("url_path", "")
            if not location.endswith(ALLOWED_ASSET_SUFFIXES) or not path.startswith("/"):
                continue
            asset.url = f"https://{location}{path}"
            asset.size = asset.sizes.get(checksum) or None
            break

        _assign_filename(asset, index, used_names)


def _assign_filename(asset: Asset, index: int, used_names: set[str]) -> None:
    """שם הקובץ המקורי (IMG_1234.JPG) מופיע בסוף הנתיב של כתובת ההורדה."""
    name = ""
    if asset.url:
        name = os.path.basename(unquote(urlparse(asset.url).path))
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", name).strip(". ")
    if not name:
        name = f"item_{index:04d}" + (".mp4" if asset.is_video else ".jpg")

    # מונעים התנגשות בין קבצים בעלי אותו שם
    if name.lower() in used_names:
        stem, ext = os.path.splitext(name)
        name = f"{stem}_{index:04d}{ext}"
    used_names.add(name.lower())

    asset.filename = name
    guessed, _ = mimetypes.guess_type(name)
    asset.mime_type = guessed or ("video/mp4" if asset.is_video else "image/jpeg")
