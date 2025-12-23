import os
import time
import asyncio
import logging
import re
import math
from aiohttp import web
from pyrogram import Client, filters, enums

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0")) 
PORT = int(os.environ.get("PORT", "8080"))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT SETUP ---
app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- WEB SERVER ROUTES ---
async def handle_stream(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        # File Details
        file_name = "file"
        file_size = 0
        mime_type = "application/octet-stream"

        if msg.document:
            file_name = msg.document.file_name
            file_size = msg.document.file_size
            mime_type = msg.document.mime_type
        elif msg.video:
            file_name = msg.video.file_name or "video.mp4"
            file_size = msg.video.file_size
            mime_type = msg.video.mime_type
        elif msg.audio:
            file_name = msg.audio.file_name or "audio.mp3"
            file_size = msg.audio.file_size
            mime_type = msg.audio.mime_type

        # --- RANGE HANDLING (FIXED LOGIC) ---
        range_header = request.headers.get("Range")
        
        from_bytes = 0
        until_bytes = file_size - 1
        status_code = 200
        content_length = file_size

        if range_header:
            try:
                ranges = re.findall(r"bytes=(\d+)-(\d*)", range_header)
                if ranges:
                    from_bytes = int(ranges[0][0])
                    if ranges[0][1]:
                        until_bytes = int(ranges[0][1])
                    
                    if from_bytes >= file_size:
                         return web.Response(status=416, headers={'Content-Range': f'bytes */{file_size}'})

                    content_length = until_bytes - from_bytes + 1
                    status_code = 206
            except Exception as e:
                logger.error(f"Range Error: {e}")

        # Headers
        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(content_length),
        }

        if status_code == 206:
            headers['Content-Range'] = f'bytes {from_bytes}-{until_bytes}/{file_size}'

        resp = web.StreamResponse(status=status_code, headers=headers)
        await resp.prepare(request)

        # --- IMPORTANT FIX HERE ---
        # Pyrogram chunks are 1MB (1024 * 1024 bytes)
        # We must calculate which CHUNK to start from, not which Byte.
        CHUNK_SIZE = 1024 * 1024
        
        # Calculate start chunk index
        start_chunk_index = from_bytes // CHUNK_SIZE
        
        # Calculate how many bytes to skip inside that first chunk
        skip_in_first_chunk = from_bytes % CHUNK_SIZE
        
        # Start streaming from the correct chunk
        # offset expects number of chunks, NOT bytes
        async for chunk in app.stream_media(msg, offset=start_chunk_index):
            
            # Agar hume chunk ke beech mein se data chahiye (Skip logic)
            if skip_in_first_chunk > 0:
                if len(chunk) > skip_in_first_chunk:
                    chunk = chunk[skip_in_first_chunk:]
                    skip_in_first_chunk = 0 # Skip done
                else:
                    skip_in_first_chunk -= len(chunk)
                    continue # Ye pura chunk skip karo
            
            # Agar user ne specific range maangi thi, to extra data mat bhejo
            # (Optional: Browser khud connection close kar deta hai usually)
            
            try:
                await resp.write(chunk)
            except Exception:
                break # Agar user ne video band kar di to loop roko
            
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)

async def health_check(request):
    return web.Response(text="Bot is running! 24/7 Service.")

# --- BOT COMMANDS ---

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File ya Video bhejo, main uska **Permanent Direct Link** bana dunga.\n"
        "Ye link Lifetime kaam karega aur free hai.\n\n"
        "✅ **Video Playback Fixed!**"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Processing...**")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        stream_link = f"{base_url}/stream/{msg_id}"
        
        fname = message.video.file_name if message.video else message.document.file_name if message.document else "file"
        
        await status_msg.edit_text(
            f"✅ **Link Generated!**\n\n🔗 {stream_link}",
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- MAIN EXECUTION ---
async def start_services():
    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', handle_stream)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Web Server running on Port {PORT}")

    logger.info("🤖 Bot starting...")
    await app.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
