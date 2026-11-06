# דרישות מחייבות – רשימת בדיקה

זו רשימת כל הדרישות של הסקיל. מקורן בהוראות המקוריות של המשתמש (נשמרו מילה במילה ב-`original/SKILL.v1.md` וב-`original/technical-spec.v1.md`) ובבקשות שנוספו אחר כך. **שום דרישה לא נמחקת מכאן.** דרישה שעדיין לא מומשה נשארת ברשימה עם הסטטוס "טרם מומש".

**חובה בכל הרצה:** בסוף העבודה, עבור על הרשימה ודווח למשתמש לכל דרישה: בוצע / בוצע חלקית (ומה חסר) / לא בוצע (ולמה). אסור לכתוב "מוכן" או "הושלם" בלי הדיווח הזה.

סטטוס: ✅ מומש ונבדק · ⚠️ חלקי · ❌ טרם מומש

## 1. קליטה וניתוח
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R01 | קבלת קובץ PDF, מספר קבצים או קישור ישיר | ✅ | `probe_pdf.py` per file/page; several floors combined in one viewer (`build_viewer.py` with several models) |
| R02 | אם סופק קישור – לאסוף את כל הנתונים, המידות והתמונות | ⚠️ | download the link first; no crawler for linked image galleries |
| R03 | זיהוי PDF וקטורי או סרוק | ✅ | `probe_pdf.py` |
| R04 | חילוץ מידות, טקסטים וסימונים | ⚠️ | מידות: `calibrate.py`; טקסט מומר לקווים נקרא בעין |
| R05 | זיהוי קומות, דירות וחללים משותפים בנפרד | ✅ | floors = separate models; apartments from `unit` labels → `apartments` + IfcZone; stairs/lifts = common |
| R06 | לא לאחד דירות ולא לערבב קומות | ✅ | |
| R07 | לא להסיק מידות מגודל התמונה | ✅ | `calibrate.py` |
| R08 | תוכנית לא קריאה – לעצור ולדווח | ✅ | נבדק במקרה הבדיקה "scanned-plan" |

## 2. מודל CAD/BIM
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R09 | קנה מידה 1:1, מילימטרים | ✅ | |
| R10 | שחזור מעטפת, קירות ועוביים | ✅ | `extract_walls.py` |
| R11 | פתחים | ✅ | openings cut by paint order; lintels above heads |
| R12 | כיווני פתיחת דלתות | ⚠️ | doors in wall fill: swing from the drawn arc (DERIVED). Doors in partitions drawn only as lines are not detected |
| R13 | חלונות | ✅ | exterior openings → windows / full-height glazing; sill & head UNRESOLVED (assumed) |
| R14 | מרפסות | ✅ | slab outside the wall envelope → balconies + railings (height UNRESOLVED) |
| R15 | מדרגות | ⚠️ | flights from tread lines (going measured); rise & direction UNRESOLVED; stair cores must be labelled in rooms.json |
| R16 | מעליות ופירים | ⚠️ | lift shafts from the X car symbol ✅; service/plumbing shafts not detected |
| R17 | שמירה על זוויות וקימורים מקוריים | ✅ | גאומטריה וקטורית |
| R18 | לא להמציא מידות חסרות | ✅ | |
| R19 | סימון כל אלמנט VERIFIED / DERIVED / UNRESOLVED (+ VISUAL ONLY) | ✅ | |
| R20 | שכבות נפרדות: גאומטריה מאומתת / ריהוט / מידות | ✅ | `walls` / `furniture` / `dimensions` / `elements` – separate in JSON, DXF layers, IFC classes, viewer toggles |
| R21 | פורמטים IFC, DXF, GLB/glTF, JSON | ✅ | `build_model.py` |

## 3. בקרת דיוק
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R22 | מבט אורתוגרפי עליון והשוואה לתוכנית | ✅ | `qa_report.py` → `overlay.png` |
| R23 | בדיקת מידות, פתחים, עוביי קירות וגבולות | ✅ | IoU overlay, plan dimensions, room spans (wall thickness), opening counts |
| R24 | דוח השוואה עם סטיות | ✅ | `qa_report.md` |
| R25 | לא לעבור לוויזואליזציה לפני סיום הבקרה | ✅ | שער PASS/FAIL |
| R26 | בדיקת התנגשויות | ✅ | `qa_report.py`: furniture vs walls, door swings vs furniture, furniture overlaps |
| R27 | בדיקת רציפות בין קומות | ✅ | `qa_report.py --floor-below`: auto alignment, lifts, concrete walls, envelope |
| R28 | בדיקות ביצועים (FPS) | ⚠️ | `perf_test.js` measures FPS/calls/triangles; without a GPU the FPS is only a floor |
| R29 | בדיקת תאימות למובייל | ✅ | `perf_test.js`: iPhone portrait + landscape emulation, no overflow, no errors |

## 4. עיצוב פנים
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R30 | ריהוט בשכבה נפרדת | ✅ | `furnish.py` – placed against walls, avoiding door swings and other spaces |
| R31 | סגנון Modern Minimalist Luxury | ✅ | palette: oak, walnut, linen, bouclé, marble, travertine, brass, glass |
| R32 | חומרי PBR, תאורה טבעית, צללים והשתקפויות | ✅ | הדמיות: path tracing – אור עקיף, צללים רכים, השתקפויות ושבירה אמיתיות; בצופה החי: PBR + השתקפויות סביבה |
| R33 | לא לשנות גאומטריה מאומתת | ✅ | |

## 5. סימולציה בזמן אמת
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R34 | סביבה אינטראקטיבית בדפדפן (Three.js) | ✅ | `assets/viewer.html` |
| R35 | מצבים: Dollhouse, Top View, Walkthrough, Orbit 360°, Floor Selector, Section, 2D/3D Comparison | ✅ | |
| R36 | מערכת מדידה אינטראקטיבית אמיתית | ✅ | נצמדת לפינות קירות |
| R37 | **חוויית משתמש ברמת Apple** – נקי, חלק, רספונסיבי, עברית + אנגלית | ✅ | ראה "שפת עיצוב" ב-SKILL.md |
| R38 | ביצועים: 60FPS בדסקטופ, 30FPS+ במובייל | ⚠️ | budget measured (~106 draw calls, ~216k triangles); real-device FPS not measurable in this container |
| R39 | RTL (עברית) ו-LTR (אנגלית) | ✅ | |
| R40 | מיני-מפה | ✅ | |
| R41 | מעבר בלחיצת כפתור בין חללים | ✅ | |
| R42 | התאמה אוטומטית לפורטרט/לנדסקייפ | ✅ | |
| R43 | תמיכה בגירוסקופ (מובייל) | ⚠️ | walk mode gyroscope implemented; works in the standalone page on a phone, blocked inside claude.ai |
| R44 | הפחתת אנימציות לנגישות | ✅ | |

## 6. תוצרים
| # | דרישה | סטטוס | איפה |
|---|---|---|---|
| R45 | מודל מדיד (IFC / DXF / GLB) | ✅ | |
| R46 | מבט אורתוגרפי עליון **עם מידות** | ✅ | `top-dimensioned.png` (+ `top-dimensioned-3d.png`), DXF layer A-DIMS |
| R47 | מבט אקסונומטרי מרוהט | ✅ | `render_photoreal.py` → `axonometric-furnished.png`, `axonometric-floor.png` |
| R48 | סימולציה אינטראקטיבית 360 עם ניווט ומדידות | ✅ | |
| R49 | דוח בקרת דיוק | ✅ | |
| R50 | קובץ ZIP מלא | ✅ | `package_deliverables.py` |
| R51 | קישור פעיל לסימולציה | ✅ | פרסום `viewer.html` כ-Artifact |
| R52 | סיכום קצר + הקישור | ✅ | |
| R53 | הדמיות פנים בגובה העין – תמונות וסרטונים עם מעברים חלקים וקולנועיים *(נוסף 2026-11-06)* | ✅ | `render_photoreal.py` (Blender Cycles, path tracing) → `interiors/*.png` + סרטון |
| R54 | סרטון קולנועי של מעבר בין החללים *(נוסף 2026-11-06)* | ✅ | `render_photoreal.py --video` → `film/walkthrough.mp4` – ירידה מהאוויר, חללים בתנועה רכה, מעברי fade |

## 7. כללי איכות
| # | דרישה | סטטוס |
|---|---|---|
| R55 | Accuracy over Appearance | ✅ |
| R56 | No Hallucinated Geometry | ✅ |
| R57 | One Verified Geometry Source | ✅ |
| R58 | Measured, Not Guessed | ✅ |
| R59 | Transparent Limitations | ✅ |
