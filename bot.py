import os
import asyncio
import logging
from pyrogram import Client, filters
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
PORT = int(os.environ.get("PORT", 8080))
WEB_URL = os.environ.get("WEB_URL", "")  # Koyeb Public URL

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT ---
app = Client(
    "my_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- WEB SERVER ROUTES ---
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "running", "maintainer": "FreeUser"})

@routes.get("/file/{message_id}", allow_head=True)
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        return await media_streamer(request, message_id)
    except Exception as e:
        return web.Response(status=500, text=str(e))

async def media_streamer(request, message_id):
    try:
        msg = await app.get_messages(CHANNEL_ID, message_id)
        file = getattr(msg, msg.media.value)
        filename = file.file_name or "Unknown_File"
        file_size = file.file_size
        mime_type = file.mime_type or "application/octet-stream"
    except Exception as e:
        return web.Response(status=404, text=f"File Not Found: {e}")

    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Length": str(file_size)
    }

    range_header = request.headers.get("Range")
    
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
        
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        headers["Content-Length"] = str(until_bytes - from_bytes + 1)
        status_code = 206
    else:
        from_bytes = 0
        until_bytes = file_size - 1
        status_code = 200

    async def file_generator():
        # Optimized for Koyeb (stream directly)
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=until_bytes - from_bytes + 1):
            yield chunk

    return web.Response(
        status=status_code,
        headers=headers,
        body=file_generator()
    )

# --- BOT COMMANDS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "👋 **Hello!**\n\n"
        "Send me any file, and I will give you a **Permanent Direct Link**.\n"
        "Streaming is now fixed! 🚀"
    )

@app.on_message(filters.document | filters.video | filters.audio)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**")

    try:
        db_msg = await message.copy(chat_id=CHANNEL_ID)
        
        # Remove trailing slash if present
        base_url = WEB_URL.rstrip("/")
        stream_link = f"{base_url}/file/{db_msg.id}"
        
        media = getattr(message, message.media.value)
        filename = media.file_name or "Unknown"
        size_mb = round(media.file_size / (1024 * 1024), 2)

        await status_msg.edit_text(
            f"✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{filename}`\n"
            f"📦 **Size:** `{size_mb} MB`\n\n"
            f"🎬 **Stream:** [Click Here]({stream_link})\n"
            f"⬇️ **Download:** [Click Here]({stream_link})\n\n"
            f"⚠️ **Note:** Wait 5-10 seconds for the video to start.",
            disable_web_page_preview=True
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- MAIN RUNNER ---

async def start_services():
    print("🤖 Initializing Bot...")
    await app.start()
    print("✅ Bot Started")

    print("🌍 Initializing Web Server...")
    runner = web.AppRunner(web.Application())
    runner.app.add_routes(routes)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🚀 Web Server Running at Port {PORT}")

    # Keep alive
    from pyrogram import idle
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
