# קונטיינר ל-Google Cloud Run
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# מתקינים תלויות בשכבה נפרדת, כדי שבנייה חוזרת אחרי שינוי קוד תהיה מהירה
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py icloud.py drive.py transfer.py ./
COPY static ./static

# לא מריצים כ-root
RUN useradd --create-home appuser
USER appuser

# Cloud Run מעביר את הפורט במשתנה PORT.
# worker אחד עם threads: כל העברה היא בקשה אחת ארוכה שרובה המתנה לרשת.
# timeout 0: לא להרוג בקשות ארוכות – את המגבלה אוכף Cloud Run עצמו (עד 60 דקות).
CMD exec gunicorn main:app \
    --bind 0.0.0.0:${PORT:-8080} \
    --workers 1 \
    --worker-class gthread \
    --threads 8 \
    --timeout 0
