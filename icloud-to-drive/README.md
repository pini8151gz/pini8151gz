# iCloud → Drive

אפליקציית ווב של דף אחד שמעתיקה אלבום משותף מ-iCloud לתיקייה חדשה ב-Google Drive.
מדביקים קישור, לוחצים "העלה לדרייב", ומקבלים קישור לתיקייה.

- כל ההורדות וההעלאות נעשות בשרת, במקביל. הקבצים מוזרמים ישירות מ-iCloud ל-Drive ולא נשמרים בדיסק או בזיכרון.
- ההרשאה היחידה מגוגל היא `drive.file` – האפליקציה רואה רק קבצים שהיא עצמה יצרה.
- אין מסד נתונים. הטוקנים נשמרים מוצפנים ב-cookie של הסשן בלבד ונמחקים כשהדפדפן נסגר.

## מבנה הפרויקט

```
icloud-to-drive/
├── main.py            שרת Flask: OAuth, סשן, נקודות קצה
├── icloud.py          לקוח ל-API הלא-רשמי של אלבומים משותפים (עם הסבר מפורט בראש הקובץ)
├── drive.py           יצירת תיקייה והעלאה בהזרמה ל-Drive
├── transfer.py        התהליך המלא: thread pool, ניסיונות חוזרים, אירועי התקדמות
├── static/
│   ├── index.html     הדף
│   ├── style.css      עיצוב
│   └── app.js         לוגיקת הדף (JavaScript נקי)
├── tests/test_flow.py בדיקות מקצה לקצה מול שרת דמה
├── requirements.txt
├── Dockerfile
├── .dockerignore
└── .env.example
```

## 1. הגדרת Google Cloud OAuth

עושים את זה פעם אחת, ב-[Google Cloud Console](https://console.cloud.google.com/).

1. **יוצרים פרויקט** (או בוחרים קיים) ורושמים את ה-Project ID.
2. **מפעילים את Drive API**: ‏APIs & Services ← Library ← מחפשים "Google Drive API" ← Enable.
3. **מסך ההסכמה**: ‏APIs & Services ← OAuth consent screen (נקרא גם "Google Auth Platform"):
   - User type: **External**. ממלאים שם אפליקציה ואימייל לתמיכה.
   - תחת Data Access / Scopes מוסיפים את `https://www.googleapis.com/auth/drive.file` בלבד.
   - כל עוד האפליקציה במצב **Testing**, רק משתמשים שהוספתם תחת Test users (Audience) יכולים להתחבר, וההתחברות שלהם פגה אחרי 7 ימים. כדי לפתוח לכולם לוחצים **Publish app**. ‏`drive.file` הוא scope לא-רגיש, כך שלא נדרש תהליך אימות אבטחה של גוגל.
4. **יוצרים OAuth Client**: ‏APIs & Services ← Credentials ← Create Credentials ← OAuth client ID:
   - Application type: **Web application**
   - **Authorized JavaScript origins**:
     - `http://localhost:8080`
     - `https://<כתובת-השירות-ב-Cloud-Run>` (מוסיפים אחרי הפריסה הראשונה, ראו סעיף 3)
   - **Authorized redirect URIs**:
     - `http://localhost:8080/auth/callback`
     - `https://<כתובת-השירות-ב-Cloud-Run>/auth/callback`
5. שומרים את ה-**Client ID** וה-**Client secret**.

> הכתובות חייבות להיות זהות תו-בתו למה שהאפליקציה שולחת (כולל `http`/`https` ובלי `/` בסוף). אחרת גוגל מחזירה `redirect_uri_mismatch`.

## 2. הרצה מקומית

דרוש Python 3.10 ומעלה.

```bash
cd icloud-to-drive
python3 -m venv .venv
source .venv/bin/activate          # ב-Windows: .venv\Scripts\activate
pip install -r requirements.txt

export GOOGLE_CLIENT_ID="xxxx.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="GOCSPX-xxxx"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

python main.py
```

פותחים את <http://localhost:8080> (דווקא `localhost` ולא `127.0.0.1` – כך הוגדר ה-redirect URI).

להרצה עם Docker:

```bash
docker build -t icloud-to-drive .
docker run --rm -p 8080:8080 \
  -e GOOGLE_CLIENT_ID -e GOOGLE_CLIENT_SECRET -e SECRET_KEY \
  icloud-to-drive
```

בדיקות:

```bash
pip install pytest
pytest
```

### משתני סביבה

| משתנה | חובה | תיאור |
|---|---|---|
| `GOOGLE_CLIENT_ID` | כן | מה-OAuth Client |
| `GOOGLE_CLIENT_SECRET` | כן | מה-OAuth Client |
| `SECRET_KEY` | כן בענן | מחרוזת אקראית ארוכה. חותמת ומצפינה את ה-cookie. מקומית נוצרת אוטומטית אם חסרה |
| `OAUTH_REDIRECT_URI` | לא | כתובת ה-callback המלאה. אם ריק, נגזרת מהכתובת שבה ניגשים לשרת |
| `MAX_WORKERS` | לא | כמה קבצים מועברים במקביל (ברירת מחדל 6) |
| `APP_TIMEZONE` | לא | אזור הזמן לתאריך בשם התיקייה (ברירת מחדל `Asia/Jerusalem`) |

## 3. פריסה ל-Cloud Run

דרוש [gcloud CLI](https://cloud.google.com/sdk/docs/install) וחשבון חיוב מקושר לפרויקט (גם כשנשארים במכסה החינמית).

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

cd icloud-to-drive
gcloud run deploy icloud-to-drive \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --timeout 3600 \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 4 \
  --max-instances 3 \
  --set-env-vars "GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com,GOOGLE_CLIENT_SECRET=GOCSPX-xxxx,SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

בסיום מודפסת כתובת השירות (`Service URL`). עכשיו:

1. חוזרים ל-OAuth Client (סעיף 1, שלב 4) ומוסיפים את הכתובת ל-Authorized JavaScript origins, ואת הכתובת עם `/auth/callback` ל-Authorized redirect URIs.
2. מקבעים את כתובת ה-callback בשירות (ל-Cloud Run יש לפעמים שתי כתובות לאותו שירות, וכך מובטח שתמיד נשלחת זו שרשמתם):

```bash
gcloud run services update icloud-to-drive --region europe-west1 \
  --update-env-vars "OAUTH_REDIRECT_URI=https://<SERVICE_URL>/auth/callback"
```

מה עושים הדגלים:

- `--timeout 3600` – המקסימום של Cloud Run. העברה היא בקשה אחת ארוכה, ולכן אלבום צריך להסתיים בתוך שעה.
- `--concurrency 4` – עד 4 העברות בו-זמנית למופע; מעבר לזה נפתח מופע נוסף.
- `--max-instances 3` – תקרה שמגבילה גם עלות.
- `--memory 512Mi` – מספיק, כי הקבצים מוזרמים ולא נטענים לזיכרון.

**סודות**: לשימוש רציני עדיף לשמור את `GOOGLE_CLIENT_SECRET` ו-`SECRET_KEY` ב-Secret Manager ולהחליף את `--set-env-vars` ב-`--set-secrets "GOOGLE_CLIENT_SECRET=<שם-הסוד>:latest,SECRET_KEY=<שם-הסוד>:latest"`.

**עלות**: המכסה החינמית של Cloud Run כוללת 2 מיליון בקשות בחודש, אבל גם זמן CPU וזיכרון מוגבלים (בסדר גודל של 50 שעות vCPU בחודש). העברות ארוכות צורכות זמן CPU, כך ששימוש כבד יכול לחרוג מהמכסה. מומלץ להגדיר התראת תקציב ב-Billing.

**עדכון גרסה**: מריצים שוב את אותה פקודת `gcloud run deploy --source .` (משתני הסביבה נשמרים, אין צורך לציין אותם שוב).

## 4. איך זה עובד מול iCloud, ומה המגבלות

לאפל אין API רשמי לאלבומים משותפים. האפליקציה משתמשת באותן קריאות שהאתר icloud.com עצמו מבצע כשפותחים קישור של אלבום משותף. ההסבר המלא נמצא בראש `icloud.py`; בקצרה:

1. ה-token של האלבום הוא החלק שאחרי ה-`#` בקישור.
2. מה-token מחשבים את שם השרת: שני התווים שאחרי התו הראשון הם מספר ב-Base62, למשל `B0a…` ← `p36-sharedstreams.icloud.com`.
3. ‏`POST https://pNN-sharedstreams.icloud.com/<TOKEN>/sharedstreams/webstream` עם הגוף `{"streamCtag": null}` מחזיר JSON עם שם האלבום ורשימת הפריטים. תשובה בסטטוס 330 מפנה לשרת אחר (השדה `X-Apple-MMe-Host`).
4. ‏`POST …/webasseturls` עם `{"photoGuids": [...]}` מחזיר כתובות הורדה חתומות לכל קובץ.

אפשר לראות את ה-JSON בעצמכם:

```bash
curl -s -X POST 'https://p36-sharedstreams.icloud.com/<TOKEN>/sharedstreams/webstream' \
  -H 'Content-Type: text/plain' -H 'Origin: https://www.icloud.com' \
  -d '{"streamCtag":null}'
```

מגבלות שכדאי להכיר:

- **ה-API לא רשמי.** אפל יכולה לשנות או לחסום אותו בלי הודעה, ואז יהיה צריך לעדכן את `icloud.py`.
- **רק אלבומים עם "אתר ציבורי".** בעל האלבום צריך להפעיל Public Website בהגדרות האלבום; אלבום ששותף רק עם אנשים מסוימים לא נגיש בקישור.
- **איכות מוקטנת.** אפל שומרת באלבומים משותפים גרסאות מוקטנות (תמונות עד כ-2048 פיקסלים בצלע הארוכה, סרטונים עד 720p). זה מה שקיים בשרת, ואין דרך לקבל את המקור. האפליקציה תמיד בוחרת את הגרסה הגדולה ביותר שזמינה.
- **Live Photos** מגיעות כתמונה רגילה, בלי קטע הווידאו.
- **כתובות ההורדה פגות** אחרי כשעה. יחד עם מגבלת 60 הדקות של Cloud Run, אלבום גדול מאוד או עם סרטונים רבים עלול לא להסתיים. במקרה כזה הקבצים שכבר הועלו נשארים בתיקייה.
- **אין המשך מנקודת העצירה.** הרצה חוזרת יוצרת תיקייה חדשה ומעתיקה הכול מחדש.
- **הדף צריך להישאר פתוח.** סגירת הדף באמצע עוצרת את ההעברה.
- **קבצים שנכשלו** אחרי 3 ניסיונות מדווחים בסוף ברשימה, והשאר מועלים כרגיל.
- **תנאי שימוש.** השתמשו באפליקציה רק לאלבומים שיש לכם רשות להעתיק.
