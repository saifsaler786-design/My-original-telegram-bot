import os
import logging
import asyncio
from aiohttp import web
from pyrogram import Client
from pyrogram.types import Message as PyroMessage
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL"))
# Koyeb default port 8000 use karta hai, isay fix kar diya hai
PORT = int(os.environ.get("PORT", 8000)) 
BASE_URL = os.environ.get("BASE_URL")

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT ---
# Ye background mein chalega files stream karne ke liye
pyro_client = Client(
    "stream_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True
)

# --- WEB SERVER HANDLERS ---

async def health_check(request):
    """Koyeb ko batane ke liye ke bot zinda hai"""
    return web.Response(text="Bot is Running!", status=200)

async def stream_handler(request):
    """File streaming logic"""
    try:
        message_id = int(request.match_info['message_id'])
        msg: PyroMessage = await pyro_client.get_messages(BIN_CHANNEL, message_id)
        
        if not msg or (not msg.video and not msg.document):
            return web.Response(status=404, text="File Not Found")

        file_size = msg.video.file_size if msg.video else msg.document.file_size
        file_name = msg.video.file_name if msg.video else (msg.document.file_name or "video.mp4")
        
        # Range handling for streaming (seek support)
        range_header = request.headers.get('Range')
        offset = 0
        length = file_size

        if range_header:
            parts = range_header.replace('bytes=', '').split('-')
            offset = int(parts[0])
            if parts[1]:
                length = int(parts[1]) - offset + 1
            else:
                length = file_size - offset

        headers = {
            'Content-Type': msg.video.mime_type if msg.video else msg.document.mime_type,
            'Content-Range': f'bytes {offset}-{offset + length - 1}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Disposition': f'inline; filename="{file_name}"'
        }

        response = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await response.prepare(request)

        async for chunk in pyro_client.stream_media(msg, offset=offset, limit=length):
            await response.write(chunk)

        return response

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")

# --- TELEGRAM BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **Bot Online Hai!**\nFile bhejein aur link hasil karein.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    status = await msg.reply_text("🔄 **Processing...**")
    
    try:
        # File ko channel mein bhejna
        fwd = await msg.copy(chat_id=BIN_CHANNEL)
        msg_id = fwd.message_id
        
        file_name = msg.video.file_name if msg.video else (msg.document.file_name or "file")
        
        stream_link = f"{BASE_URL}/stream/{msg_id}"
        download_link = f"{BASE_URL}/stream/{msg_id}"
        
        await status.edit_text(
            f"✅ **File Saved!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"🎬 **Stream:** {stream_link}\n"
            f"⬇️ **Download:** {download_link}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(e)
        await status.edit_text("❌ Error uploading file.")

# --- MAIN EXECUTION ---

async def main():
    # 1. Start Pyrogram
    await pyro_client.start()
    
    # 2. Start Web Server
    app = web.Application()
    app.router.add_get('/', health_check)  # Root path for Health Check
    app.router.add_get('/stream/{message_id}', stream_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb requires listening on 0.0.0.0 and PORT 8000
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web Server running on port {PORT}")

    # 3. Start Bot (PTB)
    ptb = ApplicationBuilder().token(BOT_TOKEN).build()
    ptb.add_handler(CommandHandler("start", start))
    ptb.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_file))
    
    await ptb.initialize()
    await ptb.start()
    await ptb.updater.start_polling()
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
