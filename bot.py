import os
import logging
import asyncio
import math
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.raw import functions, types

# --- CONFIGURATION (Environment Variables) ---
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) 
BASE_URL = os.environ.get("BASE_URL", "https://your-app.koyeb.app") 
PORT = int(os.environ.get("PORT", "8000"))

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
        return "0B"
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def get_file_info(msg):
    if msg.document:
        return msg.document.file_size, msg.document.mime_type, msg.document.file_name
    if msg.video:
        return msg.video.file_size, msg.video.mime_type, msg.video.file_name or "video.mp4"
    if msg.audio:
        return msg.audio.file_size, msg.audio.mime_type, msg.audio.file_name or "audio.mp3"
    return None, None, None

async def get_raw_location(client, channel_id, message_id):
    try:
        peer = await client.resolve_peer(channel_id)
        raw_request = functions.channels.GetMessages(
            channel=peer,
            id=[types.InputMessageID(id=message_id)]
        )
        raw_response = await client.invoke(raw_request)
        
        if not raw_response.messages:
            return None
            
        msg = raw_response.messages[0]
        media = None
        if isinstance(msg.media, types.MessageMediaDocument):
            media = msg.media.document
        elif isinstance(msg.media, types.MessageMediaPhoto):
            return None 
            
        if not media:
            return None

        location = types.InputDocumentFileLocation(
            id=media.id,
            access_hash=media.access_hash,
            file_reference=media.file_reference,
            thumb_size=""
        )
        return location

    except Exception as e:
        logger.error(f"Raw Location Error: {e}")
        return None

# --- STREAMING GENERATOR ---
async def chunk_generator(client, location, offset, limit):
    chunk_size = 1024 * 1024 
    while limit > 0:
        to_read = min(limit, chunk_size)
        try:
            result = await client.invoke(
                functions.upload.GetFile(
                    location=location,
                    offset=offset,
                    limit=to_read
                )
            )
            yield result.bytes
            read_len = len(result.bytes)
            offset += read_len
            limit -= read_len
            if read_len < to_read:
                break
        except Exception as e:
            logger.error(f"Chunk Error: {e}")
            break

# --- WEB SERVER HANDLERS ---

routes = web.RouteTableDef()

@routes.get("/")
async def root_route_handler(request):
    return web.json_response({"status": "running"})

@routes.get("/stream/{message_id}")
async def stream_handler(request):
    try:
        try:
            message_id = int(request.match_info['message_id'])
        except ValueError:
             return web.Response(status=400, text="Invalid Message ID")
        
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        if not msg:
             return web.Response(status=404, text="Message Not Found")
        
        file_size, mime_type, file_name = get_file_info(msg)
        if not file_size:
            return web.Response(status=404, text="Media Not Found")

        location = await get_raw_location(bot, CHANNEL_ID, message_id)
        if not location:
             return web.Response(status=500, text="Failed to retrieve file location")

        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1
        status_code = 200
        
        if range_header:
            try:
                from_bytes, until_bytes_str = range_header.replace("bytes=", "").split("-")
                from_bytes = int(from_bytes)
                until_bytes = int(until_bytes_str) if until_bytes_str else file_size - 1
                status_code = 206
            except ValueError:
                return web.Response(status=416, text="Invalid Range")

        length = until_bytes - from_bytes + 1
        
        # --- IMPORTANT CHANGE HERE ---
        # "inline" ka matlab hai browser mein play karo
        # "attachment" ka matlab hai download karo
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': f'inline; filename="{file_name}"', 
            'Accept-Ranges': 'bytes',
        }

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
        "👋 **Hello!**\nFile bhejo, main Stream Link dunga.",
        quote=True
    )

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**", quote=True)
    try:
        channel_msg = await message.copy(CHANNEL_ID)
        stream_link = f"{BASE_URL}/stream/{channel_msg.id}"
        f_size_bytes, mime, fname = get_file_info(message)
        f_size = humanbytes(f_size_bytes)
        
        text = (
            "✅ **File Ready!**\n\n"
            f"📄 `{fname}`\n"
            f"📦 `{f_size}`\n\n"
            f"🎬 **Stream / Download Link:**\n`{stream_link}`"
        )
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Play Video", url=stream_link)],
            [InlineKeyboardButton("⬇️ Download", url=stream_link)]
        ])

        await status_msg.edit_text(text, reply_markup=buttons)

    except Exception as e:
        logger.error(e)
        await status_msg.edit_text(f"❌ Error: {e}")

# --- MAIN LOOP ---

async def start_services():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    await bot.start()
    from pyrogram import idle
    await idle()
    await bot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
