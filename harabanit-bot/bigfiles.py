"""
Large files (over 20 MB) for the Telegram bot.

The regular Bot API only lets bots download files up to 20 MB. Through MTProto
(the protocol the Telegram apps use) a bot can download files up to 2 GB.
This needs an API ID / API hash from my.telegram.org (set TG_API_ID and
TG_API_HASH). Without them the bot keeps working, just with the 20 MB limit.
"""
import asyncio
import os
import threading

API_ID = os.environ.get('TG_API_ID', '').strip()
API_HASH = os.environ.get('TG_API_HASH', '').strip()


class BigFiles:
    def __init__(self, token):
        self.token = token
        self.enabled = bool(API_ID.isdigit() and API_HASH and token)
        self.client = None
        self.loop = None
        if self.enabled:
            self.loop = asyncio.new_event_loop()
            threading.Thread(target=self.loop.run_forever, daemon=True, name='mtproto').start()

    def _run(self, coro, timeout=1800):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    async def _ensure(self):
        if self.client and self.client.is_connected():
            return self.client
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(), int(API_ID), API_HASH,
                                connection_retries=5, request_retries=5, flood_sleep_threshold=60)
        await client.start(bot_token=self.token)
        self.client = client
        return client

    async def _download(self, msg_id, dest_dir, progress):
        client = await self._ensure()
        # In private chats a bot's message IDs are its own, so the message can be fetched by ID alone.
        msg = await client.get_messages(None, ids=int(msg_id))
        if not msg or not msg.media:
            raise RuntimeError('לא מצאתי את הקובץ בהודעה')

        def cb(done, total):
            if progress and total:
                progress(done / total)
        return await client.download_media(msg, file=dest_dir + os.sep, progress_callback=cb)

    def download(self, msg_id, dest_dir, progress=None):
        if not self.enabled:
            raise RuntimeError('big files are not configured')
        path = self._run(self._download(msg_id, dest_dir, progress))
        if not path or not os.path.exists(path):
            raise RuntimeError('ההורדה נכשלה')
        return path

    async def _send(self, chat, path, caption, video, w, h, dur):
        client = await self._ensure()
        attrs = None
        if video:
            from telethon.tl.types import DocumentAttributeVideo
            attrs = [DocumentAttributeVideo(duration=int(dur or 0), w=int(w or 0), h=int(h or 0), supports_streaming=True)]
        await client.send_file(int(chat), path, caption=caption, attributes=attrs,
                               supports_streaming=video, force_document=not video)

    def send(self, chat, path, caption='', video=True, w=0, h=0, dur=0):
        """Send a result bigger than the Bot API's 50 MB upload limit (up to 2 GB)."""
        if not self.enabled:
            raise RuntimeError('big files are not configured')
        self._run(self._send(chat, path, caption, video, w, h, dur))
