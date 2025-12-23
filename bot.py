import os
import logging
import asyncio
import math
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.file_id import FileId
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputFileLocation

# --- CONFIGURATION (Environment Variables) ---
# Environment Variables zaroori hain. 
# Agar local run kar rahe hain to yahan values dalen, warna Koyeb Env Vars use karega.
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) 
BASE_URL = os.environ.get("BASE_URL", "https://your-app.koyeb.app") 
PORT = int(os.environ.get("PORT", "8000")) # Koyeb ke liye 8000 fix hai

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT SETUP ---
bot = Client(
    "stream_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50,
    sleep_threshold=10
)

# --- HELPER FUNCTIONS ---

def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def get_file_info(msg):
    # Message se file ki info nikalna
    if msg.document:
        return msg.document.file_id, msg.document.file_size, msg.document.mime_type, msg.document.file_name
    if msg.video:
        return msg.video.file_id, msg.video.file_size, msg.video.mime_type, msg.video.file_name or "video.mp4"
    if msg.audio:
        return msg.audio.file_id, msg.audio.file_size, msg.audio.mime_type, msg.audio.file_name or "audio.mp3"
    return None, None, None, None

async def get_location(file_id):
    # Pyrogram FileID ko Raw InputFileLocation mein convert karna
    # Streaming ke liye ye zaroori hai
    try:
        file_id_obj = FileId.decode(file_id)
        return file_id_obj.make_to_input_file_location()
    except Exception as e:
        logger.error(f"Error making location: {e}")
        return None

# --- STREAMING GENERATOR (Fix for Error) ---
# Ye function Telegram se tukdon (chunks) mein file layega
async def chunk_generator(client, location, offset, limit):
    chunk_size = 1024 * 1024  # 1 MB Chunk Size
    
    while limit > 0:
        to_read = min(limit, chunk_size)
        try:
            # Direct MTProto Call to get file chunk
            result = await client.invoke(
                GetFile(
                    location=location,
                    offset=offset,
                    limit=to_read
                )
            )
            # Yield bytes to browser
            yield result.bytes
            
            # Update offset
            read_len = len(result.bytes)
            offset += read_len
            limit -= read_len
            
            # Agar file khatam ho gayi
            if read_len < to_read:
                break
                
        except Exception as e:
            logger.error(f"Chunk Error: {e}")
            break

# --- WEB SERVER HANDLERS ---

routes = web.RouteTableDef()

@routes.get("/")
async def root_route_handler(request):
    return web.json_response({"status": "running", "maintainer": "YourName"})

@routes.get("/stream/{message_id}")
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        
        # 1. Get Message from Channel
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        if not msg:
             return web.Response(status=404, text="Message Not Found")
        
        # 2. Extract Info
        file_id, file_size, mime_type, file_name = get_file_info(msg)
        if not file_id:
            return web.Response(status=404, text="Media Not Found in Message")

        # 3. Get InputFileLocation for Streaming
        location = await get_location(file_id)
        if not location:
             return web.Response(status=500, text="Failed to retrieve file location")

        # 4. Handle Range Header (Seeking/Forwarding)
        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1
        
        status_code = 200
        if range_header:
            try:
                from_bytes, until_bytes_str = range_header.replace("bytes=", "").split("-")
                from_bytes = int(from_bytes)
                until_bytes = int(until_bytes_str) if until_bytes_str else file_size - 1
                status_code = 206 # Partial Content
            except ValueError:
                return web.Response(status=416, text="Invalid Range")

        length = until_bytes - from_bytes + 1
        
        # 5. Set Headers
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': f'attachment; filename="{file_name}"',
            'Accept-Ranges': 'bytes',
        }

        # 6. Return Stream Response
        return web.Response(
            status=status_code,
            body=chunk_generator(bot, location, from_bytes, length),
            headers=headers
        )

    except Exception as e:
        logger.error(f"Stream Request Error: {e}")
        return web.Response(status=500, text="Internal Server Error")

# --- BOT COMMAND HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    await message.reply_text(
        "👋 **Hello! Main Free Stream Bot hun.**\n\n"
        "Mujhe koi Video bhejo, main uska **Direct Link** bana dunga.\n"
        "Link se video **Play** bhi hogi aur **Download** bhi!",
        quote=True
    )

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**", quote=True)
    try:
        # File ko Channel mein copy karein
        channel_msg = await message.copy(CHANNEL_ID)
        
        # Link Banayein
        stream_link = f"{BASE_URL}/stream/{channel_msg.id}"
        
        file_id, file_size_bytes, mime, fname = get_file_info(message)
        f_size = humanbytes(file_size_bytes)
        
        text = (
            "✅ **File Ready!**\n\n"
            f"📄 **Name:** `{fname}`\n"
            f"📦 **Size:** `{f_size}`\n\n"
            f"🎬 **Stream:**\n`{stream_link}`\n\n"
            f"⬇️ **Download:**\n`{stream_link}`"
        )
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch Now", url=stream_link)],
            [InlineKeyboardButton("⬇️ Download", url=stream_link)]
        ])

        await status_msg.edit_text(text, reply_markup=buttons)

    except Exception as e:
        logger.error(e)
        await status_msg.edit_text(f"❌ Error: {e}")

# --- MAIN LOOP ---

async def start_services():
    # Start Web Server
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web Server Running on Port {PORT}")

    # Start Bot
    await bot.start()
    logger.info("Bot Started!")
    
    # Keep Running
    from pyrogram import idle
    await idle()
    await bot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
