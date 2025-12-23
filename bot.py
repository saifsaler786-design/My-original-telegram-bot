import os
import asyncio
import math
import logging
import mimetypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) 
# Koyeb usually 8000 port expect karta hai
PORT = int(os.environ.get("PORT", "8000")) 
HOST_URL = os.environ.get("HOST_URL", "https://your-app.koyeb.app")

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT (BACKEND) ---
pyro_client = Client(
    "stream_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True,
    max_concurrent_transmissions=5,
    in_memory=True # Disk write error bachane ke liye
)

# --- PTB APPLICATION (FRONTEND) ---
ptb_app = Application.builder().token(BOT_TOKEN).build()

# --- HELPER FUNCTIONS ---
async def get_file_properties(message):
    media = message.video or message.document or message.audio
    if not media: return None
    file_name = getattr(media, "file_name", "video.mp4")
    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", mimetypes.guess_type(file_name)[0] or "application/octet-stream")
    return media, file_name, file_size, mime_type

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Bot Online Hai!**\n\nKoi bhi video bhejo, main Playable Link dunga.",
        parse_mode="Markdown"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not (msg.document or msg.video or msg.audio): return
    
    status_msg = await msg.reply_text("🔄 **Processing...**")
    try:
        forwarded_msg = await msg.forward(chat_id=CHANNEL_ID)
        msg_id = forwarded_msg.message_id
        
        stream_link = f"{HOST_URL}/watch/{msg_id}"
        download_link = f"{HOST_URL}/download/{msg_id}"
        
        file_name = msg.document.file_name if msg.document else (msg.video.file_name if msg.video else "file")
        
        text = (
            "✅ **Link Ready!**\n\n"
            f"📂 **File:** `{file_name}`\n"
            f"🔗 **Stream:** [Click to Play]({stream_link})\n"
            f"📥 **Download:** [Click to Download]({download_link})"
        )
        kb = [[InlineKeyboardButton("▶️ Play Video", url=stream_link)]]
        await status_msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- STREAMING LOGIC ---
async def media_streamer(request, mode="inline"):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await pyro_client.get_messages(CHANNEL_ID, message_id)
        if msg.empty or not (msg.video or msg.document or msg.audio):
            return web.Response(status=404, text="File not found")

        media, file_name, file_size, mime_type = await get_file_properties(msg)
        range_header = request.headers.get("Range")
        
        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
            content_length = (until_bytes - from_bytes) + 1
            headers = {
                "Content-Type": mime_type,
                "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                "Content-Length": str(content_length),
                "Content-Disposition": f'{mode}; filename="{file_name}"',
                "Accept-Ranges": "bytes",
            }
            generator = pyro_client.stream_media(msg, offset=from_bytes, limit=content_length)
            return web.Response(body=generator, status=206, headers=headers)
        else:
            headers = {
                "Content-Type": mime_type,
                "Content-Length": str(file_size),
                "Content-Disposition": f'{mode}; filename="{file_name}"',
                "Accept-Ranges": "bytes",
            }
            generator = pyro_client.stream_media(msg)
            return web.Response(body=generator, status=200, headers=headers)
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")

async def watch_handler(request): return await media_streamer(request, mode="inline")
async def download_handler(request): return await media_streamer(request, mode="attachment")
async def health_check(request): return web.Response(text="Bot Alive", status=200)

# --- BACKGROUND TASKS (THE FIX) ---
async def on_startup(app):
    # Bot ko background mein start karein taaki web server na ruke
    asyncio.create_task(start_bots())

async def start_bots():
    try:
        print("🔵 Starting Pyrogram...")
        await pyro_client.start()
        print("✅ Pyrogram Started")
        
        print("🔵 Starting Telegram Bot...")
        ptb_app.add_handler(CommandHandler("start", start))
        ptb_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))
        await ptb_app.initialize()
        await ptb_app.start()
        await ptb_app.updater.start_polling()
        print("✅ Telegram Bot Started Polling")
    except Exception as e:
        print(f"❌ Error starting bots: {e}")

async def on_cleanup(app):
    print("🔴 Stopping Bots...")
    try:
        await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()
        await pyro_client.stop()
    except:
        pass

# --- MAIN ENTRY POINT ---
if __name__ == "__main__":
    # Web App Setup
    server = web.Application()
    server.router.add_get("/", health_check)
    server.router.add_get("/watch/{message_id}", watch_handler)
    server.router.add_get("/download/{message_id}", download_handler)
    
    # Background Tasks Connect karein
    server.on_startup.append(on_startup)
    server.on_cleanup.append(on_cleanup)

    # Server Run karein
    print(f"🚀 Server starting on Port {PORT}")
    web.run_app(server, port=PORT)
