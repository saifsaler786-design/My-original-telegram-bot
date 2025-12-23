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
WEB_URL = os.environ.get("WEB_URL", "").rstrip("/")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)

# --- BOT CLIENT ---
# ipv6=True aur workers=4 speed ke liye zaroori hain
app = Client(
    "my_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    ipv6=True, 
    workers=4
)

# --- WEB SERVER ---
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "High Speed Bot Running"})

@routes.get("/file/{message_id}", allow_head=True)
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        return await media_streamer(request, message_id)
    except Exception as e:
        return web.Response(status=500, text=str(e))

async def media_streamer(request, message_id):
    try:
        # File dhoondna
        msg = await app.get_messages(CHANNEL_ID, message_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="File Not Found")

        file = getattr(msg, msg.media.value)
        filename = getattr(file, "file_name", "Video.mp4")
        file_size = getattr(file, "file_size", 0)
        mime_type = getattr(file, "mime_type", "video/mp4")
    except:
        return web.Response(status=404, text="File fetch failed")

    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
    }

    # Range Handling (Video Seeking)
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
        headers["Content-Length"] = str(file_size)
        status_code = 200

    # Generator: Ismein 1MB ka chunk size rakha hai (Fast Loading)
    async def file_generator():
        chunk_size = 1024 * 1024 # 1 MB chunks
        try:
            async for chunk in app.stream_media(msg, offset=from_bytes, limit=until_bytes - from_bytes + 1):
                yield chunk
        except Exception as e:
            print(f"Error streaming: {e}")

    return web.Response(
        status=status_code,
        headers=headers,
        body=file_generator()
    )

# --- COMMANDS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 Bot Online Hai! Video Bhejein.")

@app.on_message(filters.document | filters.video | filters.audio)
async def file_handler(client, message):
    status = await message.reply_text("🔄 **Link bana raha hoon...**")
    try:
        # DB Channel mein copy karna
        db_msg = await message.copy(chat_id=CHANNEL_ID)
        link = f"{WEB_URL}/file/{db_msg.id}"
        
        await status.edit_text(
            f"✅ **Link Ready!**\n\n"
            f"▶️ [Watch Video]({link})\n"
            f"⬇️ [Download]({link})",
            disable_web_page_preview=True
        )
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")

# --- STARTUP ---
async def start_services():
    print("🤖 Bot Starting...")
    await app.start()
    print("🌍 Server Starting...")
    runner = web.AppRunner(web.Application())
    runner.app.add_routes(routes)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    from pyrogram import idle
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
