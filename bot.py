import os
import time
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters, enums

# --- CONFIGURATION (Environment Variables se values lega) ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))

PORT = int(os.environ.get("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- WEB SERVER ROUTES ---
async def handle_stream(request):
    """
    Yeh function Range Requests support karta hai - Forward/Backward kaam karega!
    """
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

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

        # --- RANGE REQUEST HANDLING (Video Seeking ke liye) ---
        range_header = request.headers.get('Range', None)
        
        start = 0
        end = file_size - 1
        
        if range_header:
            # Parse Range header (e.g., "bytes=1000-2000")
            range_str = range_header.replace('bytes=', '')
            range_parts = range_str.split('-')
            
            start = int(range_parts[0]) if range_parts[0] else 0
            end = int(range_parts[1]) if range_parts[1] else file_size - 1
            
            # Validate range
            if start >= file_size:
                return web.Response(status=416, text="Range Not Satisfiable")
            if end >= file_size:
                end = file_size - 1

        content_length = end - start + 1
        
        # Headers for Range Response
        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{file_size}'
        }

        # 206 Partial Content for Range, 200 for Full
        status_code = 206 if range_header else 200
        
        resp = web.StreamResponse(status=status_code, headers=headers)
        await resp.prepare(request)

        # Stream with offset support
        current_pos = 0
        async for chunk in app.stream_media(msg):
            chunk_start = current_pos
            chunk_end = current_pos + len(chunk) - 1
            
            # Skip chunks before start
            if chunk_end < start:
                current_pos += len(chunk)
                continue
            
            # Stop if past end
            if chunk_start > end:
                break
            
            # Calculate which part of chunk to send
            send_start = max(0, start - chunk_start)
            send_end = min(len(chunk), end - chunk_start + 1)
            
            await resp.write(chunk[send_start:send_end])
            current_pos += len(chunk)
            
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
        "🚀 **Powered by:** Koyeb & Pyrogram"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        stream_link = f"{base_url}/stream/{msg_id}"
        
        file_size_mb = 0
        if message.document:
            file_size_mb = round(message.document.file_size / (1024 * 1024), 2)
            fname = message.document.file_name
        elif message.video:
            file_size_mb = round(message.video.file_size / (1024 * 1024), 2)
            fname = message.video.file_name or "video.mp4"
        elif message.audio:
            file_size_mb = round(message.audio.file_size / (1024 * 1024), 2)
            fname = message.audio.file_name or "audio.mp3"
            
        response_text = (
            "✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{fname}`\n"
            f"📦 **Size:** `{file_size_mb} MB`\n\n"
            f"🎬 **Stream Link:**\n{stream_link}\n\n"
            f"⬇️ **Download Link:**\n{stream_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
        )
        
        await status_msg.edit_text(response_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")

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
    
