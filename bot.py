import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", "8080"))

# ✅ FIX 1: Chunk size for memory optimization (1GB+ files ke liye)
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks (better for long videos)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def get_file_info(msg):
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
    
    return file_name, file_size, mime_type

# ✅ FIX 2: Professional Seek Support with offset parameter
async def handle_stream(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        file_name, file_size, mime_type = get_file_info(msg)

        # Range header parsing for seek support
        range_header = request.headers.get('Range')
        start = 0
        end = file_size - 1

        if range_header:
            range_str = range_header.replace('bytes=', '')
            parts = range_str.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1

        content_length = end - start + 1

        # ✅ FIX: Calculate offset for Pyrogram stream_media
        offset = start // CHUNK_SIZE
        skip_bytes = start % CHUNK_SIZE

        headers = {
    'Content-Type': mime_type,
    'Content-Disposition': f'inline; filename="{file_name}"',
    'Content-Length': str(content_length),
    'Accept-Ranges': 'bytes',
    'Content-Range': f'bytes {start}-{end}/{file_size}',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive'
}


        status = 206 if range_header else 200
        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)

        bytes_sent = 0
        first_chunk = True

        # ✅ FIX 3: Use offset parameter - Memory efficient streaming
        async for chunk in app.stream_media(msg, offset=offset):
            # Skip bytes from first chunk if needed
            if first_chunk and skip_bytes > 0:
                chunk = chunk[skip_bytes:]
                first_chunk = False

            # Don't send more than requested
            remaining = content_length - bytes_sent
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if chunk:
                await resp.write(chunk)
                bytes_sent += len(chunk)

            if bytes_sent >= content_length:
                break

        await resp.write_eof()
        return resp

    except asyncio.CancelledError:
        logger.info("Stream cancelled by client")
        raise
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)

async def handle_download(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        file_name, file_size, mime_type = get_file_info(msg)

        # ✅ FIX: Range support for download resume
        range_header = request.headers.get('Range')
        start = 0
        end = file_size - 1

        if range_header:
            range_str = range_header.replace('bytes=', '')
            parts = range_str.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1

        content_length = end - start + 1
        offset = max(0, start // CHUNK_SIZE)
        skip_bytes = start % CHUNK_SIZE

        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'attachment; filename="{file_name}"',
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
        }

        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'

        status = 206 if range_header else 200
        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)

        bytes_sent = 0
        first_chunk = True

        async for chunk in app.stream_media(msg, offset=offset):
            if first_chunk:
    if skip_bytes > 0:
        chunk = chunk[skip_bytes:]
    first_chunk = False


            remaining = content_length - bytes_sent
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if chunk:
                await resp.write(chunk)
                bytes_sent += len(chunk)

            if bytes_sent >= content_length:
                break

        await resp.write_eof()
        return resp

    except asyncio.CancelledError:
        logger.info("Download cancelled by client")
        raise
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)

async def health_check(request):
    return web.Response(text="Bot is running! 24/7 Service.")

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File ya Video bhejo, main uska **Permanent Direct Link** bana dunga.\n"
        "Ye link Lifetime kaam karega aur free hai.\n\n"
        "🎬 **Stream:** Video browser mein play hogi (seekable)\n"
        "⬇️ **Download:** File seedha download hogi\n\n"
        "🚀 **Created By:** SAIFSALER"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        download_link = f"{base_url}/download/{msg_id}"
        
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
            f"⬇️ **Download Link:**\n{download_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
        )
        
        await status_msg.edit_text(response_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")

# ✅ FIX 4: Graceful Shutdown with proper cleanup
async def start_services():
    # Start bot first
    await app.start()
    logger.info("🤖 Bot started successfully!")

    # Setup web server
    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', handle_stream)
    web_app.router.add_get('/download/{message_id}', handle_download)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Web Server running on Port {PORT}")

    # ✅ FIX: Keep running with proper idle
    try:
        from pyrogram import idle
        await idle()
    except ImportError:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_services())
    
