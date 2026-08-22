# Aether — סוכן AI לא מצונזר

אתר בסגנון Google עם אנימציות פסיכדליות + חיבור מלא לבוט טלגרם שלך.

כשמישהו שואל שאלה באתר → אתה מקבל אותה בטלגרם → אתה עונה (Reply) → התשובה מופיעה אצלו בצ'אט בזמן אמת.

---

## מה כלול

- דף נחיתה עם רקע Three.js פסיכדלי (חלקיקים זוהרים + אינטראקציה עם העכבר)
- שורת קלט ממורכזת בסגנון Google
- דף צ'אט מלא עם WebSocket (זמן אמת)
- שליחת שאלות לטלגרם שלך
- תשובות שלך חוזרות אוטומטית לאתר
- תמיכה בשיחה מתמשכת (לא רק שאלה אחת)
- עיצוב כהה + ניאון, מותאם מובייל

---

## התקנה מהירה (5 דקות)

### 1. הורד / העתק את התיקייה

```bash
cd uncensored-ai-agent
```

### 2. צור סביבה וירטואלית והתקן תלויות

```bash
python3 -m venv venv
source venv/bin/activate   # ב-Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. הגדר את ה-.env

```bash
cp .env.example .env
```

פתח את `.env` ומלא:

```env
TELEGRAM_BOT_TOKEN=הטוקן_של_הבוט_שלך

AGENT_NAME=Aether
AGENT_TAGLINE=סוכן AI לא מצונזר
```

**אין צורך למצוא Chat ID ידנית!** אחרי שהשרת רץ, שלח `/start` לבוט שלך בטלגרם —
השולח הראשון נתפס אוטומטית כבעלים, והבוט גם יגיד לך את ה-Chat ID שלך.
כדי לקבע את הבעלות לתמיד (גם אחרי דיפלוי מחדש), הוסף אחר כך:

```env
TELEGRAM_OWNER_CHAT_ID=המספר_שהבוט_נתן_לך
```

> ⚠️ **אבטחה:** אל תעלה את הטוקן לגיט אף פעם (הקובץ `.env` כבר ב-.gitignore).
> אם הטוקן דלף — היכנס ל-@BotFather בטלגרם → `/mybots` → הבוט שלך → API Token → Revoke.

### 4. הרץ את השרת

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

פתח בדפדפן: [http://localhost:8000](http://localhost:8000)

---

## איך זה עובד בפועל

1. משתמש נכנס לאתר וכותב שאלה.
2. נוצר Session ID ייחודי.
3. השאלה נשלחת אליך לטלגרם (עם ה-Session).
4. **אתה עושה Reply להודעה** של הבוט.
5. התשובה שלך מופיעה מיד אצל המשתמש בדף הצ'אט.
6. המשתמש יכול להמשיך לכתוב — כל הודעה נוספת מגיעה אליך גם כן.

---

## פריסה לאינטרנט (Production)

הפרויקט כולל כבר קבצי פריסה מוכנים — `Procfile`, `render.yaml`, `railway.json`, `runtime.txt` ו-`Dockerfile`.

### Render (הכי פשוט – יש `render.yaml` גם בשורש הריפו)

1. העלה את הקוד ל-GitHub.
2. ב-[render.com](https://render.com) → **New → Blueprint** → בחר את הריפו ואת הענף הנכון.
3. Render יקרא את `render.yaml` לבד. הדבק את `TELEGRAM_BOT_TOKEN`
   (את `TELEGRAM_OWNER_CHAT_ID` אפשר להשאיר ריק — שלח `/start` לבוט אחרי הדיפלוי).
4. Deploy. תקבל כתובת כמו `https://aether.onrender.com`.
5. שלח `/start` לבוט בטלגרם → אתה הבעלים → מוכן.

### Railway

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
2. Root Directory: `uncensored-ai-agent`.
3. Variables → הוסף `TELEGRAM_BOT_TOKEN` ו-`TELEGRAM_OWNER_CHAT_ID`.
4. Railway יקרא את `railway.json` ויריץ אוטומטית.

### Docker / Fly.io / VPS

```bash
docker build -t aether .
docker run -p 8000:8000 \
  -e TELEGRAM_BOT_TOKEN=... \
  -e TELEGRAM_OWNER_CHAT_ID=... \
  -v $(pwd)/data:/app/data \
  aether
```

הפקודה להרצה בכל פלטפורמה:
```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

> **שים לב:** במסלול החינמי של Render השרת נרדם אחרי חוסר פעילות, ומסד ה-SQLite נמחק בכל דיפלוי.
> להיסטוריה קבועה — חבר Persistent Disk (Render) / Volume (Railway/Fly) לנתיב `data/`.

**חשוב:** אחרי שהאתר עולה לאוויר, הבוט יעבוד עם Polling אוטומטית (אין צורך ב-Webhook).

### ngrok לבדיקות מקומיות

אם אתה רוצה לבדוק מהטלפון בזמן שאתה מריץ מקומית:

```bash
ngrok http 8000
```

---

## מבנה הפרויקט

```
uncensored-ai-agent/
├── app/
│   ├── main.py          # FastAPI + Telegram + WebSockets
│   ├── database.py      # SQLite
│   └── __init__.py
├── static/
│   ├── css/
│   │   ├── style.css
│   │   └── chat.css
│   └── js/
│       ├── psychedelic.js   # Three.js אנימציה
│       ├── main.js
│       └── chat.js
├── templates/
│   ├── index.html
│   └── chat.html
├── data/                # נוצר אוטומטית (SQLite)
├── .env.example
├── requirements.txt
└── README.md
```

---

## טיפים

- **שנה את שם הסוכן** ב-`.env` → זה משנה את הכותרת בכל מקום.
- אפשר להוסיף יותר אנימציות ב-`psychedelic.js` (shaders וכו').
- אם אתה מקבל הרבה שאלות – כדאי להוסיף rate limiting בהמשך.
- הנתונים נשמרים ב-SQLite מקומי (`data/chats.db`). לפרודקשן אפשר לעבור ל-Supabase בקלות.

---

## בעיות נפוצות

| בעיה | פתרון |
|------|--------|
| הבוט לא מקבל הודעות | וודא שה-TOKEN וה-CHAT_ID נכונים, ושהרצת את השרת |
| תשובות לא מגיעות לאתר | **חובה לעשות Reply** להודעה של הבוט (לא לשלוח הודעה חדשה) |
| WebSocket לא מתחבר | בדוק שהפורט פתוח / השתמש ב-HTTPS בפרודקשן |
| אנימציה לא מופיעה | וודא שיש חיבור לאינטרנט (Three.js נטען מ-CDN) |

---

נבנה עבורך מוכן לשימוש.  
תשנה את השם, תריץ, ותתחיל לקבל שאלות.
