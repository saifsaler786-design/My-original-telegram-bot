import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BASE_URL = os.environ.get("BASE_URL", "")
PORT = int(os.environ.get("PORT", 8080))

# Chunk size for streaming (1MB)
CHUNK_SIZE = 1024 * 1024

# Initialize Pyrogram client
app = Client("stream_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store file info
file_data = {}

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    await message.reply_text(
        "🚀 **Powered by: Koyeb & Pyrogram**\n\n"
        "📁 Send me any file and I'll generate streaming & download links!"
    )

@app.on_message(filters.media)
async def handle_media(client: Client, message: Message):
    try:
        media = message.document or message.video or message.audio or message.photo
        if not media:
            return

        if hasattr(media, 'file_id'):
            file_id = media.file_id
            file_name = getattr(media, 'file_name', 'file')
            file_size = getattr(media, 'file_size', 0)
        else:
            file_id = media[-1].file_id if isinstance(media, list) else media.file_id
            file_name = "photo.jpg"
            file_size = 0

        # Store file data
        msg_id = message.id
        file_data[msg_id] = {
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "chat_id": message.chat.id
        }

        size_mb = file_size / (1024 * 1024) if file_size else 0

        await message.reply_text(
            f"✅ **File Upload Complete!**\n\n"
            f"📄 **File:** {file_name}\n"
            f"📦 **Size:** {size_mb:.2f} MB\n\n"
            f"🎬 **Stream Link:**\n{BASE_URL}/stream/{msg_id}\n\n"
            f"⬇️ **Download Link:**\n{BASE_URL}/download/{msg_id}\n\n"
            f"⏰ **Validity:** Lifetime ∞\n"
            f"⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
        )
    except Exception as e:
        logger.error(f"Error handling media: {e}")
        await message.reply_text("❌ Error processing file.")

async def handle_stream(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        if msg_id not in file_data:
            return web.Response(text="File not found", status=404)

        data = file_data[msg_id]
        file_size = data['file_size']
        file_name = data['file_name']

        # Parse Range header for seeking
        range_header = request.headers.get('Range', '')
        start = 0
        end = file_size - 1 if file_size > 0 else 0

        if range_header.startswith('bytes='):
            range_spec = range_header[6:]
            if '-' in range_spec:
                parts = range_spec.split('-')
                if parts[0]:
                    start = int(parts[0])
                if parts[1]:
                    end = int(parts[1])

        # Calculate offset and limit for Pyrogram
        offset = start // CHUNK_SIZE
        skip_bytes = start % CHUNK_SIZE
        content_length = end - start + 1

        headers = {
            'Content-Type': 'video/mp4',
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'inline; filename="{file_name}"',
        }

        if file_size > 0:
            headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
            headers['Content-Length'] = str(content_length)

        status = 206 if range_header else 200

        response = web.StreamResponse(status=status, headers=headers)
        await response.prepare(request)

        bytes_sent = 0
        first_chunk = True

        async for chunk in app.stream_media(data['file_id'], offset=offset):
            if first_chunk and skip_bytes > 0:
                chunk = chunk[skip_bytes:]
                first_chunk = False

            if bytes_sent + len(chunk) > content_length:
                chunk = chunk[:content_length - bytes_sent]

            if chunk:
                await response.write(chunk)
                bytes_sent += len(chunk)

            if bytes_sent >= content_length:
                break

        await response.write_eof()
        return response

    except Exception as e:
        logger.error(f"Stream error: {e}")
        return web.Response(text="Streaming error", status=500)

async def handle_download(request):
    try:
        msg_id = int(request.match_info['msg_id'])
        if msg_id not in file_data:
            return web.Response(text="File not found", status=404)

        data = file_data[msg_id]
        file_name = data['file_name']
        file_size = data['file_size']

        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{file_name}"',
        }
        if file_size > 0:
            headers['Content-Length'] = str(file_size)

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        async for chunk in app.stream_media(data['file_id']):
            await response.write(chunk)

        await response.write_eof()
        return response

    except Exception as e:
        logger.error(f"Download error: {e}")
        return web.Response(text="Download error", status=500)

async def main():
    # Start Pyrogram client
    await app.start()
    logger.info("Bot started successfully!")

    # Setup web server
    web_app = web.Application()
    web_app.router.add_get('/stream/{msg_i
    
