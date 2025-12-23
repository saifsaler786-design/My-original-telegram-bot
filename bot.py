import os
import asyncio
import math
import logging
import mimetypes
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client, errors
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) 
PORT = int(os.environ.get("PORT", "8000")) 
HOST_URL = os.environ.get("HOST_URL", "https://your-app.koyeb.app")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT ---
# ipv6=False zaroori hai taki connection fast bane
pyro_client = Client(
    "stream_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True,
    ipv6=False 
)

# --- PTB CLIENT ---
ptb_app = Application.builder().token(BOT_TOKEN).build()

# --- HELPER: FILE INFO ---
async def get_file_properties(message):
    media = message.video or message.document or message.audio
    if not media: return None
    file_name = getattr(media, "file_name", "video.mp4")
    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", mimetypes.guess_type(file_name)[0] or "application/octet-stream")
    return media, file_name, file_size, mime_type

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **Bot Ready!**\nFile bhejo, main Stream Link dunga.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not (msg.document or msg.video or msg.audio): return
    
    status = await msg.reply_text("🔄 **Processing...**")
    try:
        f_msg = await msg.forward(chat_id=CHANNEL_ID)
        mid = f_msg.message_id
        link = f"{HOST_URL}/watch/{mid}"
        dl_link = f"{HOST_URL}/download/{mid}"
        
        fname = msg.document.file_name if msg.document else (msg.video.file_name if msg.video else "file")
        
        text = (
            f"📄 **File:** `{fname}`\n\n"
            f"🎬 **Stream:** [Click to Play]({link})\n"
            f"📥 **Download:** [Click to Download]({dl_link})"
        )
        kb = [[InlineKeyboardButton("🎬 Play Now", url=link)]]
        await status.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await status.edit_text(f"Error: {e}")

# --- NEW ROBUST STREAMING ENGINE ---
# Yeh function browser ko data chunks mein bhejta hai
async def media_streamer(request, mode="inline"):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await pyro_client.get_messages(CHANNEL_ID, message_id)
        media, file_name, file_size, mime_type = await get_file_properties(msg)
        
        # Range Headers Calculation (Video seeking ke liye)
        range_header = request.headers.get("Range")
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1

        content_length = (until_bytes - from_bytes) + 1
        
        # Response Headers set karna
        headers = {
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(content_length),
            "Content-Disposition": f'{mode}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        }

        # StreamResponse create karein (Important fix for buffering)
        resp = web.StreamResponse(
            status=206 if range_header else 200,
            reason='Partial Content' if range_header else 'OK',
            headers=headers
        )
        
        # Browser ko batayein hum ready hain
        await resp.prepare(request)
        
        # Pyrogram se data le kar sidha browser ko bhejein
        # Chunk size 1MB (1024*1024) rakha hai taaki smooth chale
        async for chunk in pyro_client.stream_media(msg, offset=from_bytes, limit=content_length):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")

async def watch_handler(request): return await media_streamer(request, mode="inline")
async def download_handler(request): return await media_streamer(request, mode="attachment")
async def health_check(request): return web.Response(text="Bot Alive", status=200)

# --- BACKGROUND TASKS ---
async def on_startup(app):
    asyncio.create_task(run_bot_logic())

async def run_bot_logic():
    await pyro_client.start()
    print("✅ Pyrogram Started")
    
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling()
    print("✅ Bot Started")

# --- MAIN ---
if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/watch/{message_id}", watch_handler)
    app.router.add_get("/download/{message_id}", download_handler)
    app.on_startup.append(on_startup)
    
    print(f"🚀 Server running on Port {PORT}")
    web.run_app(app, port=PORT)
