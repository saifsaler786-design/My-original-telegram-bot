import os
import logging
import asyncio
import time
from aiohttp import web
from pyrogram import Client
from pyrogram.types import Message as PyroMessage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURATION (Environment Variables) ---
# Ye variables hum Koyeb ke environment settings mein dalenge
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL"))  # Private Channel ID (-100xxxx)
PORT = int(os.environ.get("PORT", 8080))
BASE_URL = os.environ.get("BASE_URL")  # e.g., https://myapp.koyeb.app

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT (Backend Streamer) ---
# Ye client background mein chalega aur files ko stream karega
pyro_client = Client(
    "stream_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True  # Conflict se bachne ke liye updates off rakhein
)

# --- WEB SERVER (Streaming Logic) ---
routes = web.RouteTableDef()

@routes.get("/")
async def root_route(request):
    """Simple health check route."""
    return web.json_response({"status": "running", "uptime": "forever"})

@routes.get("/stream/{message_id}")
async def stream_handler(request):
    """
    Ye function file ko chunks mein download karke seedha user ko stream karega.
    Permanent link yahan hit karega.
    """
    try:
        message_id = int(request.match_info['message_id'])
        
        # Pyrogram se message fetch karein
        msg: PyroMessage = await pyro_client.get_messages(BIN_CHANNEL, message_id)
        
        if not msg or not msg.video and not msg.document:
            return web.Response(status=404, text="File Not Found")

        file_size = msg.video.file_size if msg.video else msg.document.file_size
        mime_type = msg.video.mime_type if msg.video else msg.document.mime_type
        file_name = msg.video.file_name if msg.video else (msg.document.file_name or "video.mp4")

        # Range Header Handle karna (Video seek/forwarding ke liye zaroori hai)
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

        # Response Headers set karein
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {offset}-{offset + length - 1}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Disposition': f'inline; filename="{file_name}"'
        }

        # Streaming Response Function
        response = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await response.prepare(request)

        # Pyrogram ke through file ke chunks yield karna
        async for chunk in pyro_client.stream_media(msg, offset=offset, limit=length):
            await response.write(chunk)

        return response

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Internal Server Error")

# --- PYTHON-TELEGRAM-BOT HANDLERS (Frontend) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command ka response."""
    await update.message.reply_text(
        "👋 **Welcome!**\n\n"
        "Mujhe koi bhi file ya video bhejein, main uska permanent link generate kar dunga.\n"
        "Ye service lifetime free hai! ⚡️"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Jab user file bhejta hai, ye function trigger hota hai.
    1. File ko channel mein forward karega.
    2. Link generate karega.
    3. User ko formatted message bhejega.
    """
    message = update.message
    
    # User ko wait message bhejein
    status_msg = await message.reply_text("🔄 Processing... Please wait.")

    try:
        # 1. File ko Private Channel mein copy karein
        # copy_message method efficient hai kyunki ye re-upload nahi karta
        forwarded_msg = await message.copy(chat_id=BIN_CHANNEL)
        
        # 2. Details extract karein
        file_name = "Unknown"
        file_size = 0
        
        if message.video:
            file_name = message.video.file_name or "Video.mp4"
            file_size = message.video.file_size
        elif message.document:
            file_name = message.document.file_name
            file_size = message.document.file_size
            
        size_mb = round(file_size / (1024 * 1024), 2)
        msg_id = forwarded_msg.message_id
        
        # 3. Links generate karein
        # Hamesha online rehne ke liye BASE_URL environment variable se ayega
        stream_link = f"{BASE_URL}/stream/{msg_id}"
        download_link = f"{BASE_URL}/stream/{msg_id}?download=true"

        # 4. Final formatted reply bhejein
        text = (
            "✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"📦 **Size:** `{size_mb} MB`\n\n"
            f"🎬 **Stream:** {stream_link}\n"
            f"⬇️ **Download:** {download_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️"
        )

        # protect_content=True se forwarding disable hoti hai
        await status_msg.edit_text(
            text, 
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text("❌ Error occurred processing file.")

# --- MAIN EXECUTION ---
async def main():
    # 1. Start Pyrogram Client (Streamer)
    await pyro_client.start()
    logger.info("Pyrogram Client Started!")

    # 2. Start Web Server (Aiohttp)
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web Server running on port {PORT}")

    # 3. Start Python-Telegram-Bot (Frontend)
    # PTB v20 ApplicationBuilder use karta hai
    ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO | filters.Document.ALL, handle_file))

    # PTB Polling start karein (Async way mein)
    await ptb_app.initialize()
    await ptb_app.start()
    
    logger.info("Bot is Polling...")
    
    # Keep the loop running
    await ptb_app.updater.start_polling()
    
    # Process ko zinda rakhne ke liye infinite wait
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
