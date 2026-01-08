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

# Chunk size optimization
CHUNK_SIZE = 1024 * 1024  # 1MB

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

# ✅ NEW: HTML Player Template with Custom Buttons
# Ye function HTML page generate karega jisme +10s aur -10s ke buttons hain
async def stream_player_page(request):
    try:
        message_id = request.match_info['message_id']
        # Hum actual video stream karne ke liye '/stream-data/' route use karenge
        stream_url = f"/stream-data/{message_id}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Video Player</title>
            <style>
                body {{ margin: 0; background-color: #000; color: white; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; font-family: sans-serif; }}
                video {{ width: 100%; max-width: 800px; max-height: 80vh; background: #000; }}
                .controls {{ margin-top: 15px; display: flex; gap: 20px; }}
                .btn {{ 
                    padding: 10px 20px; 
                    font-size: 18px; 
                    background-color: #2481cc; 
                    color: white; 
                    border: none; 
                    border-radius: 5px; 
                    cursor: pointer; 
                    user-select: none;
                }}
                .btn:active {{ background-color: #1a5c91; transform: scale(0.95); }}
                .info {{ margin-top: 10px; color: #aaa; font-size: 14px; }}
            </style>
        </head>
        <body>
            <video id="player" controls autoplay playsinline>
                <source src="{stream_url}" type="video/mp4">
                Your browser does not support the video tag.
            </video>

            <div class="controls">
                <button class="btn" onclick="seek(-10)">⏪ -10s</button>
                <button class="btn" onclick="seek(10)">+10s ⏩</button>
            </div>
            <div class="info">Custom Player by SAIFSALER</div>

            <script>
                const video = document.getElementById('player');
                
                function seek(seconds) {{
                    video.currentTime += seconds;
                }}

                // Keyboard support (Left/Right arrows)
                document.addEventListener('keydown', function(e) {{
                    if (e.code === 'ArrowRight') seek(10);
                    if (e.code === 'ArrowLeft') seek(-10);
                }});
            </script>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')
    except Exception as e:
        logger.error(f"Page Error: {e}")
        return web.Response(text="Server Error", status=500)

# ✅ RENAMED: Ye purana 'handle_stream' hai, ab ye background mein data supply karega
async def media_stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        file_name, file_size, mime_type = get_file_info(msg)

        range_header = request.headers.get('Range')
        start = 0
        end = file_size - 1

        if range_header:
            range_str = range_header.replace('bytes=', '')
            parts = range_str.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1

        content_length = end - start + 1
        offset = start // CHUNK_SIZE
        skip_bytes = start % CHUNK_SIZE

        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{file_size}'
        }

        status = 206 if range_header else 200
        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)

        bytes_sent = 0
        first_chunk = True

        async for chunk in app.stream_media(msg, offset=offset):
            if first_chunk and skip_bytes > 0:
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

        range_header = request.headers.get('Range')
        start = 0
        end = file_size - 1

        if range_header:
            range_str = range_header.replace('bytes=', '')
            parts = range_str.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1

        content_length = end - start + 1
        offset = start // CHUNK_SIZE
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
            if first_chunk and skip_bytes > 0:
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
        "🎬 **Stream:** Video browser mein play hogi (With Fast Forward Buttons)\n"
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
        
        # URL wohi rahega, lekin ab ye HTML page kholega
        stream_link = f"{base_url}/stream/{msg_id}"
        download_link = f"{base_url}/download/{msg_id}"
        
        file_size_mb = 0
        fname = "Unknown"
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
            f"🎬 **Stream Link (Player):**\n{stream_link}\n\n"
            f"⬇️ **Download Link:**\n{download_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
        )
        
        await status_msg.edit_text(response_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")

async def start_services():
    await app.start()
    logger.info("🤖 Bot started successfully!")

    web_app = web.Application()
    
    # ✅ ROUTES UPDATE:
    # 1. /stream/ID -> Ab HTML Player dikhayega
    web_app.router.add_get('/stream/{message_id}', stream_player_page)
    
    # 2. /stream-data/ID -> Ye video ka raw data supply karega (Hidden route)
    web_app.router.add_get('/stream-data/{message_id}', media_stream_handler)
    
    # 3. Download waise hi rahega
    web_app.router.add_get('/download/{message_id}', handle_download)
    
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Web Server running on Port {PORT}")

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
