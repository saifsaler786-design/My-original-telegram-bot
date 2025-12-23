import os
import asyncio
import math
import logging
import mimetypes
import time
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client
from aiohttp import web

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) 
PORT = int(os.environ.get("PORT", "8000")) 
HOST_URL = os.environ.get("HOST_URL", "https://your-app.koyeb.app")

# Logging Setup (Debug Mode)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT ---
# workers=4 rakha hai taaki parallel download ho sake
pyro_client = Client(
    "stream_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True,
    max_concurrent_transmissions=4, 
    ipv6=False
)

ptb_app = Application.builder().token(BOT_TOKEN).build()

# --- CUSTOM STREAM CLASS (The Magic Fix) ---
class ByteStreamer:
    def __init__(self, client, message):
        self.client = client
        self.message = message
        self.media = message.video or message.document or message.audio
        self.file_size = self.media.file_size

    async def yield_chunks(self, offset, length):
        # Yeh function Pyrogram se data maangta hai aur Aiohttp ko deta hai
        chunk_size = 1024 * 1024 # 1 MB Chunks
        current_offset = offset
        bytes_remaining = length
        
        while bytes_remaining > 0:
            fetch_size = min(chunk_size, bytes_remaining)
            
            try:
                # Pyrogram se specific hissa download karo (In-Memory)
                # Hum generator use kar rahe hain
                async for chunk in self.client.stream_media(
                    self.message,
                    offset=current_offset,
                    limit=fetch_size
                ):
                    yield chunk
                    current_offset += len(chunk)
                    bytes_remaining -= len(chunk)
                    
                    # Thoda saans lene do server ko
                    await asyncio.sleep(0)
                    
            except Exception as e:
                logger.error(f"Error yielding chunk: {e}")
                break

# --- HELPER FUNCTIONS ---
async def get_file_properties(message):
    media = message.video or message.document or message.audio
    if not media: return None
    file_name = getattr(media, "file_name", "video.mp4")
    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", mimetypes.guess_type(file_name)[0] or "application/octet-stream")
    return media, file_name, file_size, mime_type

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ **Bot Online!** File bhejo.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not (msg.document or msg.video or msg.audio): return
    status = await msg.reply_text("🔄 **Processing...**")
    try:
        f_msg = await msg.forward(chat_id=CHANNEL_ID)
        mid = f_msg.message_id
        link = f"{HOST_URL}/watch/{mid}"
        dl_link = f"{HOST_URL}/download/{mid}"
        fname = msg.document.file_name if msg.document else (msg.video.file_name if msg.video else "file")
        
        text = f"📄 `{fname}`\n\n🎬 [Stream]({link})\n⬇️ [Download]({dl_link})"
        kb = [[InlineKeyboardButton("🎬 Play Video", url=link)]]
        await status.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await status.edit_text(f"Error: {e}")

# --- WEB HANDLERS ---
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        logger.info(f"Request for Message ID: {message_id}")
        
        # Message Fetch
        msg = await pyro_client.get_messages(CHANNEL_ID, message_id)
        media, file_name, file_size, mime_type = await get_file_properties(msg)
        
        # Range Header Check (Browser Playback Logic)
        range_header = request.headers.get("Range")
        offset = 0
        length = file_size

        if range_header:
            # Parse Range: bytes=100-200
            matches = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if matches:
                offset = int(matches.group(1))
                if matches.group(2):
                    end_byte = int(matches.group(2))
                else:
                    end_byte = file_size - 1
                length = end_byte - offset + 1

        # Headers setup
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Access-Control-Allow-Origin': '*' # CORS fix
        }

        if range_header:
            headers['Content-Range'] = f'bytes {offset}-{offset + length - 1}/{file_size}'
            status_code = 206
        else:
            status_code = 200

        # Response start
        response = web.StreamResponse(status=status_code, headers=headers)
        await response.prepare(request)

        # Streaming Start
        logger.info(f"Starting Stream: Offset={offset}, Length={length}")
        streamer = ByteStreamer(pyro_client, msg)
        
        try:
            async for chunk in streamer.yield_chunks(offset, length):
                await response.write(chunk)
        except Exception as e:
            logger.error(f"Stream Broken: {e}")
            
        return response

    except Exception as e:
        logger.error(f"Handler Error: {e}")
        return web.Response(status=500, text="Server Error")

async def health_check(request):
    return web.Response(text="Running", status=200)

# --- BACKGROUND & MAIN ---
async def on_startup(app):
    asyncio.create_task(run_bots())

async def run_bots():
    print("🔵 Connecting to Telegram...")
    await pyro_client.start()
    print("✅ Pyrogram Connected!")
    
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling()
    print("✅ Bot Started Polling!")

if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/watch/{message_id}", stream_handler)
    app.router.add_get("/download/{message_id}", stream_handler)
    app.on_startup.append(on_startup)
    
    print(f"🚀 Server running on Port {PORT}")
    web.run_app(app, port=PORT)
