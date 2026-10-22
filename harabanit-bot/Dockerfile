# Harabanit Studio bot: Chromium (to run the studio's own design code) + ffmpeg.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY harabanit-bot/requirements.txt /app/harabanit-bot/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /app/harabanit-bot/requirements.txt
# Faster encryption for big Telegram downloads (optional: skip if no wheel is available)
RUN python3 -m pip install --no-cache-dir --only-binary=:all: cryptg || true
COPY harabanit /app/harabanit
COPY harabanit-bot /app/harabanit-bot
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/harabanit-bot/bot.py"]
