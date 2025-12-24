import os
import logging
import asyncio
from aiohttp import web
from pyrogram import Client, filters

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", "8080"))
# Koyeb URL (e.g., https://your-app.koyeb.app) - Bina slash ke
APP_URL = os.environ.get("APP_URL", "http://localhost:8080")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("stream_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- STREAMING LOGIC WITH SEEK SUPPORT ---
async def handle_stream(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File Not Found", status=404)

        file = msg.document or msg.video or msg.audio
        file_size = file.file_size
        mime_type = file.mime_type or "application/octet-stream"
        file_name = getattr(file, "file_name", "video.mp4")

        # Range Header Handling (For Seeking)
        range_header = request.headers.get('Range')
        start = 0
        end = file_size - 1

        if range_header:
            # bytes=start-end
            try:
                ranges = range_header.replace('bytes=', '').split('-')
                start = int(ranges[0])
                if ranges[1]:
                    end = int(ranges[1])
            except (ValueError, IndexError):
                return web.Response(status=416) # Range Not Satisfiable

            if start >= file_size:
                return web.Response(status=416)

            headers = {
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Content-Type': mime_type,
                'Content-Length': str(end - start + 1),
                'Accept-Ranges': 'bytes',
                'Content-Disposition': f'inline; filename="{file_name}"',
            }
            status = 206 # Partial Content
        else:
            headers = {
                'Content-Type': mime_type,
                'Content-Length': str(file_size),
                'Accept-Ranges': 'bytes',
                'Content-Disposition': f'inline; filename="{file_name}"',
            }
            status = 200

        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)

        # Telegram se specific offset se stream karna
        async for chunk in app.stream_media(msg, offset=start):
            await resp.write(chunk)
            # Agar client disconnect ho jaye to stream rok do
            if not resp.prepared:
                break
        
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Server Error or Link Expired", status=500)

async def health_check(request):
    return web.Response(text="Bot is running perfectly!")

# --- BOT COMMANDS ---
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        f"👋 **Salam {message.from_user.first_name}!**\n\n"
        "Mujhe koi video bhejein, main aapko **Seekable Link** bana kar dunga."
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Generating Link...**")
    try:
        log_msg = await message.copy(CHANNEL_ID)
        stream_link = f"{APP_URL}/stream/{log_msg.id}"
        
        file = message.document or message.video or message.audio
        f_size = round(file.file_size / (1024 * 1024), 2)
        
        await status_msg.edit_text(
            "✅ **Link Ready!**\n\n"
            f"🎬 **Stream & Download:**\n{stream_link}\n\n"
            f"📦 **Size:** `{f_size} MB`\n"
            "⚠️ *Ab aap video ko aage-piche (seek) kar sakte hain!*",
            disable_web_page_preview=True
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- MAIN RUNNER ---
async def start_services():
    # Web Server Setup
    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', handle_stream)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    # Bot Start
    await app.start()
    logger.info(f"✅ Bot and Server started on port {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        pass
        
