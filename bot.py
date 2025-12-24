import os
import logging
import asyncio
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

# --- BOT CLIENT ---
bot = Client(
    "FreeStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50,
    sleep_threshold=10
)

# --- HELPER: Size Readable Banana ---
def get_readable_size(size):
    if not size: return ""
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

# --- WEB SERVER (Stream & Download) ---
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        # Check karein user Download chahta hai ya Stream
        is_download = request.query.get('download') is not None
        
        # Channel se message lo
        msg = await bot.get_messages(CHANNEL_ID, message_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="404: File Not Found or Deleted")

        # File Details
        media = msg.video or msg.document or msg.audio
        file_id = media.file_id
        file_size = media.file_size
        file_name = media.file_name if media.file_name else "file.mp4"
        mime_type = media.mime_type if media.mime_type else "video/mp4"

        # Range Handling (Video aage/peeche karne ke liye)
        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1

        if range_header:
            from_bytes, until_bytes = range_header.replace('bytes=', '').split('-')
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1

        length = until_bytes - from_bytes + 1
        
        # Headers set karo
        # Agar is_download True hai to 'attachment' (Save file), warna 'inline' (Play file)
        disposition = 'attachment' if is_download else 'inline'
        
        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': f'{disposition}; filename="{file_name}"',
            'Accept-Ranges': 'bytes',
        }

        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)

        # Telegram se Data Stream karna
        async for chunk in bot.stream_media(msg, offset=from_bytes, limit=length):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")

# --- BOT HANDLERS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("👋 **Bot Ready!**\nFile bhejo, main link dunga.")

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("🔄 **Processing...**")
    
    try:
        # 1. Channel mein copy karo
        copied_msg = await message.copy(CHANNEL_ID)
        
        # 2. Links banao
        # Important: Koyeb App URL yahan aayega
        base_url = os.environ.get("BASE_URL", "http://localhost:8080")
        
        # Link Logic
        stream_link = f"{base_url}/watch/{copied_msg.id}"
        download_link = f"{base_url}/watch/{copied_msg.id}?download=true" # ?download=true add kiya

        media = message.video or message.document or message.audio
        file_name = media.file_name if media.file_name else "Unknown"
        file_size = get_readable_size(media.file_size)

        # 3. User ko reply
        await status_msg.edit_text(
            f"✅ **File Saved!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** `{file_size}`\n\n"
            f"🎬 **Stream:** [Click to Watch]({stream_link})\n"
            f"⬇️ **Download:** [Click to Save]({download_link})",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 Stream Online", url=stream_link)],
                [InlineKeyboardButton("⬇️ Fast Download", url=download_link)]
            ])
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")

# --- MAIN RUNNER ---
async def start_services():
    # Web Server
    app = web.Application()
    app.router.add_get('/watch/{message_id}', stream_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    # Bot Start
    print("Bot aur Server start ho gaye hain...")
    await bot.start()
    
    # Keep Running
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
