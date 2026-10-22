# רובוט טלגרם – הרבנית סטודיו

שולחים לרובוט תמונה או סרטונים עם הטקסט (מילת פתיחה, כותרת, קרדיט), והוא מחזיר עיצוב מוכן בשפת המותג.
הרובוט מריץ את קוד העיצוב של הסטודיו עצמו (`harabanit/index.html`), כך שהתוצאה זהה לאתר.

## משתני סביבה
| משתנה | תפקיד |
|---|---|
| `BOT_TOKEN` | הטוקן מ־@BotFather (חובה) |
| `ALLOWED_IDS` | מזהי טלגרם מורשים, מופרדים בפסיק |
| `WEBHOOK_SECRET` | נוצר אוטומטית ב־Render |

## פורמט הודעה
```
מזל טוב!
בכירי תעשיית המוזיקה בחגיגות יום הולדת לזמר
צילום וידאו: דודי קפלר. צילום תמונה: דודי פרידמן.
```
`#פוסט` / `#סטורי` לפורמט, `#סגול` / `#אדום` וכו׳ לצבע. כמה קבצים באלבום = סרטון אחד עם מעברים.

## הרצה על מחשב (בלי Render)
```
pip install playwright==1.48.0 && playwright install chromium
BOT_TOKEN=... ALLOWED_IDS=... python harabanit-bot/bot.py
```


## בנייה מהירה בחינם (Modal)

השרת החינמי של Render חלש (0.1 מעבד). אפשר להעביר את בניית הסרטון ל־[Modal](https://modal.com):
30$ קרדיט חינם בכל חודש, בלי כרטיס אשראי, על מכונות עם 4 ליבות – סרטון נבנה תוך שניות ובאיכות 1080.

1. נרשמים ב־modal.com (עם GitHub או Google).
2. ב־Modal: **Settings → API Tokens → New Token**. מקבלים `MODAL_TOKEN_ID` ו־`MODAL_TOKEN_SECRET`.
3. ב־Render: **harabanit-bot → Environment → Add variable** – מוסיפים את שני הערכים בשמות האלה.
4. **Save, rebuild, and deploy**. בעמוד `/status` תופיע השורה `fast builds (Modal): on`.

הרובוט מפרסם ב־Modal את `modal_app.py` בעצמו בכל עלייה. אם Modal לא זמין – הסרטון נבנה ב־Render כרגיל.
