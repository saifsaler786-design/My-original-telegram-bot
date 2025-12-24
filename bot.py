import os
import time
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters, enums

# --- CONFIGURATION (Environment Variables se values lega) ---
# Koyeb par yeh variables set karne honge
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0")) # Private Channel ID (e.g., -100xxxx)

# Server Port (Koyeb auto-assign karta hai, default 8080)
PORT = int(os.environ.get("PORT", "8080"))

# Logging setup (Errors dekhne ke liye)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT SETUP ---
app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- WEB SERVER ROUTES ---
async def handle_stream(request):
    """
    Yeh function tab chalega jab koi link open karega.
    Yeh Telegram se file stream karke user ke browser mein bhejta hai.
    """
    try:
        # URL se message id nikalo (e.g., /stream/123 -> 123)
        message_id = int(request.match_info['message_id'])
        
        # Channel se message fetch karo
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        # File ki details nikalo
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
            
        # --- RANGE REQUEST LOGIC (Forward/Backward Support) ---
        offset = 0
        limit = file_size
        range_header = request.headers.get("Range")
        status_code = 200

        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Accept-Ranges': 'bytes'
        }

        if range_header:
            try:
                # Range header format: bytes=100-
                from_bytes, until_bytes = range_header.replace('bytes=', '').split('-')
                offset = int(from_bytes)
                # Agar user ne specific end byte nahi diya to end tak play karo
                limit = int(until_bytes) - offset + 1 if until_bytes else file_size - offset
                
                status_code = 206  # Partial Content
                headers['Content-Range'] = f'bytes {offset}-{offset + limit - 1}/{file_size}'
            except Exception:
                pass # Agar range calculation fail ho to normal play karo
        
        headers['Content-Length'] = str(limit)

        # Response stream shuru karo
        resp = web.StreamResponse(status=status_code, headers=headers)
        await resp.prepare(request)

        # Telegram se download karke direct user ko stream karo (Chunk by Chunk)
        # limit aur offset add kiya taake video beech se play ho sake
        async for chunk in app.stream_media(msg, limit=limit, offset=offset):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)

async def health_check(request):
    return web.Response(text="Bot is running! 24/7 Service.")

# --- BOT COMMANDS ---

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File ya Video bhejo, main uska **Permanent Direct Link** bana dunga.\n"
        "Ye link Lifetime kaam karega aur free hai.\n\n"
        "🚀 **Powered by:** Koyeb & Pyrogram"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    """
    Jab user file bhejta hai:
    1. File ko Database Channel mein copy karo.
    2. Wahan se Message ID lo.
    3. Link generate karo.
    """
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        # File ko private channel mein copy karo (Forward nahi, Copy taake user ID hide rahe)
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        # Server ka URL (Koyeb automatically URL assign karta hai, hum environment se bhi le sakte hain)
        # Local testing ke liye localhost, Production ke liye Koyeb URL
        # NOTE: Koyeb deploy hone ke baad jo URL milega wo yahan hardcode karna behtar hai
        # Filhal hum dynamic host use karne ki koshish karte hain, lekin best hai ke APP_URL env var set karein
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        
        # File size formatting
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
            f"⬇️ **Download Link:**\n{stream_link}\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
        )
        
        await status_msg.edit_text(response_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")

# --- MAIN EXECUTION ---
async def start_services():
    # Web App Setup
    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', handle_stream)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Web Server running on Port {PORT}")

    # Bot Start
    logger.info("🤖 Bot starting...")
    await app.start()
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
