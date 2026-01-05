import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters, idle

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", "8080"))

# Chunk Size (1MB)
CHUNK_SIZE = 1024 * 1024 

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

# ✅ UPDATED HTML PLAYER (No Download Button)
async def stream_player_page(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        file_name, _, _ = get_file_info(msg)
        
        # Sirf Stream URL generate hoga
        stream_url = f"/stream-data/{message_id}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{file_name}</title>
            <style>
                body {{ margin: 0; background-color: #121212; color: white; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
                
                .player-container {{ width: 95%; max-width: 900px; position: relative; }}
                video {{ width: 100%; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); background: #000; }}
                
                h2 {{ margin: 10px 0; font-size: 1.2rem; word-break: break-all; color: #e0e0e0; text-align: center; }}
                
                .controls-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; margin-top: 15px; width: 100%; }}
                
                .btn {{ 
                    padding: 12px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; transition: 0.2s; color: white;
                    display: flex; align-items: center; justify-content: center; gap: 5px;
                }}
                
                .btn-seek {{ background-color: #2b3a42; }}
                .btn-seek:hover {{ background-color: #3d525e; }}
                
                .btn-speed {{ background-color: #2b3a42; }}
                .btn-speed:hover {{ background-color: #3d525e; }}
                
                .info {{ margin-top: 20px; font-size: 0.8rem; color: #666; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="player-container">
                <h2>📺 {file_name}</h2>
                
                <video id="player" controls autoplay playsinline preload="metadata">
                    <source src="{stream_url}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>

                <div class="controls-grid">
                    <button class="btn btn-seek" onclick="seek(-10)">⏪ -10s</button>
                    <button class="btn btn-seek" onclick="seek(10)">+10s ⏩</button>
                    
                    <button class="btn btn-speed" onclick="setSpeed(1.0)">1x</button>
                    <button class="btn btn-speed" onclick="setSpeed(1.5)">1.5x</button>
                    <button class="btn btn-speed" onclick="setSpeed(2.0)">2x</button>
                </div>
                <!-- Download button removed -->
            </div>

            <div class="info">Space: Play/Pause | F: Fullscreen | Arrows: Seek</div>

            <script>
                const video = document.getElementById('player');
                
                function seek(seconds) {{
                    video.currentTime += seconds;
                }}
                
                function setSpeed(rate) {{
                    video.playbackRate = rate;
                }}

                document.addEventListener('keydown', function(e) {{
                    if(['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].indexOf(e.code) > -1) {{
                        e.preventDefault();
                    }}

                    switch(e.code) {{
                        case 'ArrowLeft': seek(-10); break;
                        case 'ArrowRight': seek(10); break;
                        case 'Space': 
                            if (video.paused) video.play(); 
                            else video.pause(); 
                            break;
                        case 'KeyF':
                            if (document.fullscreenElement) document.exitFullscreen();
                            else video.requestFullscreen();
                            break;
                    }}
                }});
            </script>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')
    except Exception as e:
        logger.error(f"Page Error: {e}")
        return web.Response(text="Server Error", status=500)

# Backend Stream Handler (Invisible to user)
async def media_stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found.", status=404)

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
        logger.info("Stream cancelled")
        raise
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Server Error", status=500)

# Download Handler (Iska link Bot Chat mein milega, Player mein nahi)
async def handle_download(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found.", status=404)

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
        raise
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return web.Response(text="Server Error", status=500)

async def health_check(request):
    return web.Response(text="Bot is running! 24/7 Service.")

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File bhejo, main uska Link bana dunga.\n\n"
        "🎬 **Stream:** Advanced Player (No Download Button)\n"
        "⬇️ **Download:** Direct Download Link\n\n"
        "🚀 **Created By:** SAIFSALER"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Processing...**")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        download_link = f"{base_url}/download/{msg_id}"
        
        fname = "File"
        if message.document: fname = message.document.file_name
        elif message.video: fname = message.video.file_name or "video.mp4"
        elif message.audio: fname = message.audio.file_name or "audio.mp3"
            
        response_text = (
            "✅ **Link Generated!**\n\n"
            f"📄 **File:** `{fname}`\n\n"
            f"🎬 **Watch Online:**\n{stream_link}\n\n"
            f"⬇️ **Download File:**\n{download_link}\n\n"
            "⚠️ *Link Lifetime valid hai.*"
        )
        
        await status_msg.edit_text(response_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)}")

async def start_services():
    await app.start()
    logger.info("🤖 Bot started!")

    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', stream_player_page)
    web_app.router.add_get('/stream-data/{message_id}', media_stream_handler)
    web_app.router.add_get('/download/{message_id}', handle_download)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Server running on Port {PORT}")

    await idle()
    await runner.cleanup()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_services())
