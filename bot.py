import os
import time
import math
import logging
import asyncio
import aiohttp
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURATION (Environment Variables) ---
# Koyeb ya Server par yeh variables set karein
API_ID = int(os.environ.get("API_ID", "12345"))  # Apna API ID yahan default mein na dalein, Env Var use karein
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) # Channel ID jahan files store hongi
BASE_URL = os.environ.get("BASE_URL", "https://your-app-name.koyeb.app") # Koyeb App ka URL
PORT = int(os.environ.get("PORT", "8080"))

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT SETUP ---
# Yeh bot client hai jo Telegram se connect hoga
bot = Client(
    "stream_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50,
    sleep_threshold=10
)

# --- HELPER FUNCTIONS ---

# File size ko human readable format mein convert karne ke liye
def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

# --- WEB SERVER FOR STREAMING ---

routes = web.RouteTableDef()

@routes.get("/")
async def root_route_handler(request):
    return web.json_response({"status": "running", "maintainer": "YourName"})

@routes.get("/stream/{message_id}")
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        return await media_streamer(request, message_id)
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")

async def media_streamer(request, message_id):
    # Channel se message get karte hain
    try:
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="File Not Found")
        
        # File ki details nikalte hain
        file_id = None
        file_size = 0
        mime_type = "application/octet-stream"
        file_name = "file"

        if msg.document:
            file_id = msg.document.file_id
            file_size = msg.document.file_size
            mime_type = msg.document.mime_type
            file_name = msg.document.file_name
        elif msg.video:
            file_id = msg.video.file_id
            file_size = msg.video.file_size
            mime_type = msg.video.mime_type
            file_name = "video.mp4"
        elif msg.audio:
            file_id = msg.audio.file_id
            file_size = msg.audio.file_size
            mime_type = msg.audio.mime_type
            file_name = "audio.mp3"
        else:
            return web.Response(status=400, text="Unsupported Media Type")

        # Range Header Handle karna (Seeking/Forwarding ke liye Zaroori)
        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1

        length = until_bytes - from_bytes + 1
        
        # Response Headers set karte hain
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': f'attachment; filename="{file_name}"',
            'Accept-Ranges': 'bytes',
        }

        # Streaming Response Generator
        async def file_generator():
            # Telegram se file chunks mein download karke direct user ko bhejte hain
            async for chunk in bot.stream_media(message_id=message_id, chat_id=CHANNEL_ID, offset=from_bytes, limit=length):
                yield chunk

        return web.Response(status=206 if range_header else 200, body=file_generator(), headers=headers)

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Internal Server Error")

# --- BOT HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    await message.reply_text(
        "👋 **Hello! Main ek File Stream Bot hun.**\n\n"
        "Mujhe koi bhi Video ya File bhejo, main uska **Direct Download** aur **Stream Link** generate karunga.\n"
        "Ye links **Lifetime** kaam karenge aur **Video Player** mein chalenge!",
        quote=True
    )

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    # User ko wait karwate hain
    status_msg = await message.reply_text("🔄 **Processing... Channel par upload ho raha hai.**", quote=True)

    try:
        # 1. File ko Private Channel mein copy karte hain
        # Copy method use karne se bandwidth bachti hai (Telegram server to server)
        channel_msg = await message.copy(CHANNEL_ID)
        
        # 2. Link generate karte hain
        # URL Format: https://app-url/stream/message_id
        stream_link = f"{BASE_URL}/stream/{channel_msg.id}"
        
        # File name aur size nikalte hain
        file_name = message.video.file_name if message.video and message.video.file_name else (message.document.file_name if message.document else "Unknown_File")
        file_size = humanbytes(message.video.file_size if message.video else message.document.file_size)

        # 3. User ko reply karte hain
        text = (
            "✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"📦 **Size:** `{file_size}`\n\n"
            f"🎬 **Stream Link:**\n{stream_link}\n\n"
            f"⬇️ **Download Link:**\n{stream_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️"
        )
        
        # Buttons add karte hain
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch / Stream", url=stream_link)],
            [InlineKeyboardButton("⬇️ Download Now", url=stream_link)]
        ])

        await status_msg.edit_text(text, reply_markup=buttons)

    except Exception as e:
        logger.error(e)
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- MAIN EXECUTION ---

async def start_services():
    # Web Server Start
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web Server Running on Port {PORT}")

    # Bot Start
    logger.info("Bot Starting...")
    await bot.start()
    
    # Keep idle
    from pyrogram import idle
    await idle()
    await bot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
