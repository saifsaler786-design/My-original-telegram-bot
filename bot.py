import os
import logging
import asyncio
import mimetypes
import time
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100")) 
PORT = int(os.environ.get("PORT", "8080"))

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT SETUP ---
bot = Client(
    "FreeStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
    sleep_threshold=10,
    max_concurrent_transmissions=10
)

# --- HTML PLAYER TEMPLATE (FIXED BRACKETS) ---
# NOTE: CSS aur JS ke liye {{ }} use kiya hai taake Python error na de
PLAYER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watch Video</title>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        body {{ margin: 0; background: #0f0f0f; display: flex; justify-content: center; align-items: center; height: 100vh; color: white; font-family: sans-serif; }}
        .container {{ width: 95%; max-width: 800px; }}
        .btn {{ display: block; text-align: center; margin-top: 20px; padding: 10px; background: #2a2a2a; color: #fff; text-decoration: none; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <video controls crossorigin playsinline poster="">
            <source src="{stream_url}" type="{mime_type}">
        </video>
        <a href="{download_url}" class="btn">⬇️ Download File</a>
    </div>
    <script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>
    <script>
        const player = new Plyr('video', {{
            controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'fullscreen', 'settings'],
            speed: {{ selected: 1, options: [0.5, 1, 1.5, 2] }}
        }});
    </script>
</body>
</html>
"""

# --- HELPER: Size Readable ---
def get_readable_size(size):
    if not size: return ""
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

# --- WEB SERVER: STREAM HANDLER ---
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        is_download = request.query.get('download') is not None
        
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="404: File Not Found")

        media = msg.video or msg.document or msg.audio
        file_size = media.file_size
        file_name = media.file_name if media.file_name else "video.mp4"
        
        # Mime Type Fix
        mime_type = mimetypes.guess_type(file_name)[0]
        if not mime_type: mime_type = "video/mp4"

        # Range Handling
        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1

        if range_header:
            try:
                from_bytes, until_bytes = range_header.replace('bytes=', '').split('-')
                from_bytes = int(from_bytes)
                until_bytes = int(until_bytes) if until_bytes else file_size - 1
            except: pass

        length = until_bytes - from_bytes + 1
        
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': f'{"attachment" if is_download else "inline"}; filename="{file_name}"',
            'Accept-Ranges': 'bytes',
        }

        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)

        # 1MB Chunks
        chunk_size = 1024 * 1024 
        
        try:
            async for chunk in bot.stream_media(msg, offset=from_bytes, limit=length):
                await resp.write(chunk)
        except Exception:
            pass 
            
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")

# --- WEB SERVER: PLAYER HANDLER ---
async def player_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        
        media = msg.video or msg.document or msg.audio
        file_name = media.file_name if media.file_name else "video.mp4"
        mime_type = mimetypes.guess_type(file_name)[0] or "video/mp4"
        
        base_url = str(request.url).split("/play/")[0]
        # Ensure HTTP/HTTPS
        if "localhost" not in base_url and not base_url.startswith("http"):
             base_url = "https://" + base_url

        stream_url = f"{base_url}/watch/{message_id}"
        download_url = f"{base_url}/watch/{message_id}?download=true"
        
        # HTML Render
        return web.Response(
            text=PLAYER_TEMPLATE.format(stream_url=stream_url, mime_type=mime_type, download_url=download_url),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(e)
        return web.Response(text=f"Error: {e}")

# --- BOT COMMANDS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("👋 **Bot Ready!**\nFile bhejo, main Player Link dunga.")

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**")
    try:
        copied_msg = await message.copy(CHANNEL_ID)
        
        base_url = os.environ.get("BASE_URL", "http://localhost:8080")
        if base_url.endswith("/"): base_url = base_url[:-1]

        play_link = f"{base_url}/play/{copied_msg.id}"
        download_link = f"{base_url}/watch/{copied_msg.id}?download=true"

        media = message.video or message.document or message.audio
        file_name = media.file_name if media.file_name else "Unknown"
        file_size = get_readable_size(media.file_size)

        await status_msg.edit_text(
            f"✅ **File Ready!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** `{file_size}`\n\n"
            f"▶️ **Play Online:**\n{play_link}\n\n"
            f"⬇️ **Direct Download:**\n{download_link}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Play Video", url=play_link)],
                [InlineKeyboardButton("⬇️ Download", url=download_link)]
            ])
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")

# --- MAIN RUNNER ---
async def start_services():
    app = web.Application()
    app.router.add_get('/watch/{message_id}', stream_handler)
    app.router.add_get('/play/{message_id}', player_handler) 
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print("Bot Started!")
    await bot.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
