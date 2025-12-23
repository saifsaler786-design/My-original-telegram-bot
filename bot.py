import os
import asyncio
import logging
import math
from pyrogram import Client, filters
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
PORT = int(os.environ.get("PORT", 8080))
WEB_URL = os.environ.get("WEB_URL", "").rstrip("/")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT (FIXED SETTINGS) ---
app = Client(
    "my_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    ipv6=True,           # <-- KOYEB FIX: IPv6 ON
    in_memory=True       # <-- SPEED FIX: Memory caching
)

# --- WEB SERVER ROUTES ---
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "Online", "server": "Koyeb-IPv6"})

@routes.get("/file/{message_id}", allow_head=True)
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        return await media_streamer(request, message_id)
    except Exception as e:
        return web.Response(status=500, text=f"Server Error: {e}")

async def media_streamer(request, message_id):
    try:
        # File details fetch karna
        msg = await app.get_messages(CHANNEL_ID, message_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="File Not Found")
            
        file = getattr(msg, msg.media.value)
        filename = getattr(file, "file_name", "Video.mp4")
        file_size = getattr(file, "file_size", 0)
        mime_type = getattr(file, "mime_type", "video/mp4") # Default to video
        
    except Exception as e:
        return web.Response(status=404, text=f"File Fetch Error: {e}")

    # Headers setup
    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
    }

    # Range Handling (Video Seeking ke liye ZAROORI)
    range_header = request.headers.get("Range")
    
    if range_header:
        # Example Range: bytes=0- or bytes=100-200
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
        
        # Content-Range header
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        headers["Content-Length"] = str(until_bytes - from_bytes + 1)
        status_code = 206
    else:
        from_bytes = 0
        until_bytes = file_size - 1
        headers["Content-Length"] = str(file_size)
        status_code = 200

    # Generator Function (Data Streamer)
    async def file_generator():
        try:
            # Chunk size 1MB (1024*1024) best balance hai speed/memory ka
            async for chunk in app.stream_media(msg, offset=from_bytes, limit=until_bytes - from_bytes + 1):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming Error: {e}")

    return web.Response(
        status=status_code,
        headers=headers,
        body=file_generator()
    )

# --- BOT COMMANDS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "👋 **Bot is Online!**\n\n"
        "Send me a video to get a **Fast Stream Link**.\n"
        "⚡ IPv6 Enabled"
    )

@app.on_message(filters.document | filters.video | filters.audio)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**")

    try:
        # 1. Message copy to DB channel
        db_msg = await message.copy(chat_id=CHANNEL_ID)
        
        # 2. Generate Link
        stream_link = f"{WEB_URL}/file/{db_msg.id}"
        
        # 3. File Info
        media = getattr(message, message.media.value)
        filename = getattr(media, "file_name", "File")
        
        # 4. Reply
        await status_msg.edit_text(
            f"✅ **Ready to Watch!**\n\n"
            f"📂 `{filename}`\n\n"
            f"▶️ [Click to Watch Video]({stream_link})\n\n"
            f"⚠️ *Agar video load hone mein time le, toh 10 sec wait karein.*",
            disable_web_page_preview=True
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")

# --- SERVER STARTUP ---

async def start_services():
    print("🤖 Starting Bot...")
    await app.start()
    
    print("🌍 Starting Web Server...")
    runner = web.AppRunner(web.Application())
    runner.app.add_routes(routes)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    print(f"🚀 Services Running on Port {PORT}")
    from pyrogram import idle
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
