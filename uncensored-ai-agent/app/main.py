import os
import uuid
import asyncio
import json
from datetime import datetime
from typing import Dict, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from .database import (
    init_db, create_session, add_message, get_messages,
    get_session_by_telegram_msg, update_telegram_message_id
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(BASE_DIR, ".env"))

# ====================== CONFIG ======================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID")
AGENT_NAME = os.getenv("AGENT_NAME", "Aether")
AGENT_TAGLINE = os.getenv("AGENT_TAGLINE", "סוכן AI לא מצונזר")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_CHAT_ID:
    print("⚠️  חסר TELEGRAM_BOT_TOKEN או TELEGRAM_OWNER_CHAT_ID בקובץ .env")

# WebSocket connections: session_id -> set of websockets
active_connections: Dict[str, Set[WebSocket]] = {}

# Telegram Application
telegram_app: Application = None


# ====================== WEBSOCKET MANAGER ======================
async def connect_ws(session_id: str, websocket: WebSocket):
    await websocket.accept()
    if session_id not in active_connections:
        active_connections[session_id] = set()
    active_connections[session_id].add(websocket)
    print(f"✅ WS connected: {session_id} (total: {len(active_connections[session_id])})")


async def disconnect_ws(session_id: str, websocket: WebSocket):
    if session_id in active_connections:
        active_connections[session_id].discard(websocket)
        if not active_connections[session_id]:
            del active_connections[session_id]
    print(f"❌ WS disconnected: {session_id}")


async def broadcast_to_session(session_id: str, data: dict):
    if session_id not in active_connections:
        return
    dead = set()
    for ws in active_connections[session_id]:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    for ws in dead:
        active_connections[session_id].discard(ws)


# ====================== TELEGRAM HANDLERS ======================
async def handle_owner_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """כשהבעלים עונה להודעה של הבוט – שולחים את התשובה למשתמש באתר"""
    if not update.message or not update.message.reply_to_message:
        return

    # רק הודעות מהבעלים
    if str(update.effective_user.id) != str(TELEGRAM_OWNER_CHAT_ID):
        return

    replied_msg = update.message.reply_to_message
    telegram_msg_id = replied_msg.message_id

    session_id = await get_session_by_telegram_msg(telegram_msg_id)
    if not session_id:
        # ניסיון לחלץ session_id מהטקסט של ההודעה המקורית
        original_text = replied_msg.text or ""
        if "Session:" in original_text:
            try:
                session_id = original_text.split("Session:")[1].split("\n")[0].strip()
            except Exception:
                await update.message.reply_text("❌ לא מצאתי Session ID. ענה ישירות להודעה של הבוט.")
                return
        else:
            await update.message.reply_text("❌ לא מצאתי Session. ענה ישירות להודעה של השאלה.")
            return

    answer = update.message.text or update.message.caption or ""
    if not answer.strip():
        return

    # שמירה במסד
    await add_message(session_id, "assistant", answer)

    # שליחה ל-WebSocket
    await broadcast_to_session(session_id, {
        "type": "new_message",
        "role": "assistant",
        "content": answer,
        "created_at": datetime.utcnow().isoformat()
    })

    # אישור לבעלים
    await update.message.reply_text(f"✅ נשלח למשתמש\nSession: `{session_id[:8]}...`", parse_mode=ParseMode.MARKDOWN)


async def send_to_owner(text: str):
    """שולח לבעלים בטלגרם. אם ה-Markdown נשבר (תווים מיוחדים בשאלה) – שולח כטקסט רגיל."""
    bot: Bot = telegram_app.bot
    try:
        return await bot.send_message(
            chat_id=TELEGRAM_OWNER_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        return await bot.send_message(
            chat_id=TELEGRAM_OWNER_CHAT_ID,
            text=text.replace("*", "").replace("`", "").replace("_", "")
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Telegram error: {context.error}")


# ====================== LIFESPAN ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    print("✅ Database ready")

    global telegram_app
    if TELEGRAM_BOT_TOKEN:
        telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        telegram_app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_owner_reply))
        telegram_app.add_error_handler(error_handler)

        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        print("✅ Telegram bot started (polling)")
    else:
        print("⚠️  Telegram bot not started – missing token")

    yield

    # Shutdown
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        print("🛑 Telegram bot stopped")


# ====================== APP ======================
app = FastAPI(title=AGENT_NAME, lifespan=lifespan)

# Static & Templates
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ====================== ROUTES ======================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "agent_name": AGENT_NAME,
        "agent_tagline": AGENT_TAGLINE
    })


@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_page(request: Request, session_id: str):
    messages = await get_messages(session_id)
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": session_id,
        "messages": messages,
        "agent_name": AGENT_NAME
    })


@app.post("/api/ask")
async def ask(question: str = Form(...)):
    question = question.strip()
    if not question:
        raise HTTPException(400, "שאלה ריקה")

    if len(question) > 4000:
        raise HTTPException(400, "השאלה ארוכה מדי")

    session_id = str(uuid.uuid4())
    await create_session(session_id)
    msg_id = await add_message(session_id, "user", question)

    # שליחה לטלגרם
    telegram_msg_id = None
    if telegram_app and TELEGRAM_OWNER_CHAT_ID:
        try:
            text = (
                f"🧠 *שאלה חדשה*\n\n"
                f"{question}\n\n"
                f"────────────────\n"
                f"Session: `{session_id}`\n"
                f"⏰ {datetime.utcnow().strftime('%H:%M:%S')} UTC\n\n"
                f"_ענה להודעה הזו כדי לשלוח תשובה למשתמש_"
            )
            sent = await send_to_owner(text)
            telegram_msg_id = sent.message_id
            await update_telegram_message_id(msg_id, telegram_msg_id)
        except Exception as e:
            print(f"❌ Failed to send to Telegram: {e}")

    return JSONResponse({
        "session_id": session_id,
        "redirect": f"/chat/{session_id}"
    })


@app.post("/api/chat/{session_id}/message")
async def send_followup(session_id: str, message: str = Form(...)):
    """הודעה נוספת בתוך שיחה קיימת"""
    message = message.strip()
    if not message:
        raise HTTPException(400, "הודעה ריקה")

    # בדיקה שה-session קיים
    existing = await get_messages(session_id)
    if not existing:
        raise HTTPException(404, "Session לא קיים")

    msg_id = await add_message(session_id, "user", message)

    # שליחה לטלגרם
    if telegram_app and TELEGRAM_OWNER_CHAT_ID:
        try:
            text = (
                f"💬 *המשך שיחה*\n\n"
                f"{message}\n\n"
                f"────────────────\n"
                f"Session: `{session_id}`\n"
                f"_ענה להודעה הזו_"
            )
            sent = await send_to_owner(text)
            await update_telegram_message_id(msg_id, sent.message_id)
        except Exception as e:
            print(f"❌ Failed to send follow-up: {e}")

    # עדכון ה-WebSocket של המשתמש (שיראה את ההודעה שלו מיד)
    await broadcast_to_session(session_id, {
        "type": "new_message",
        "role": "user",
        "content": message,
        "created_at": datetime.utcnow().isoformat(),
        "message_id": msg_id
    })

    return JSONResponse({"ok": True, "message_id": msg_id})


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await connect_ws(session_id, websocket)
    try:
        # שליחת ההיסטוריה הקיימת מיד עם החיבור
        messages = await get_messages(session_id)
        await websocket.send_json({
            "type": "history",
            "messages": messages
        })

        while True:
            # שמירה על החיבור חי (ping)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await disconnect_ws(session_id, websocket)
    except Exception as e:
        print(f"WS error: {e}")
        await disconnect_ws(session_id, websocket)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "telegram": bool(telegram_app),
        "active_sessions": len(active_connections)
    }
