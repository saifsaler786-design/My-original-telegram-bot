import os
import time
import asyncio
import logging
import re  # Yeh naya import hai, video forward/back ke liye zaroori hai
from aiohttp import web
from pyrogram import Client, filters, enums

# --- CONFIGURATION (Environment Variables se values lega) ---
API_ID = int(os.environ.get("API_ID", "0")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0")) 
PORT = int(os.environ.get("PORT", "8080"))

# Logging setup
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
    Yeh function ab Range Header support karta hai.
    Video ko Forward/Backward karne ke liye yeh zaroori hai.
    """
    try:
        # URL se message id nikalo
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

        # --- IS HISSE MAI CHANGES KIYE HAIN (Video Seeking Logic) ---
        
        # Browser se check karo ke usne kaunsa hissa maanga hai (Range Header)
        range_header = request.headers.get("Range")
        
        from_bytes = 0
        until_bytes = file_size - 1
        status_code = 200
        content_length = file_size

        if range_header:
            try:
                # Browser keh raha hai: "Mujhe bytes=1000-" chahiye
                ranges = re.findall(r"bytes=(\d+)-(\d*)", range_header)
                if ranges:
                    from_bytes = int(ranges[0][0])
                    if ranges[0][1]:
                        until_bytes = int(ranges[0][1])
                    else:
                        until_bytes = file_size - 1
                    
                    # Agar range galat hai
                    if from_bytes >= file_size:
                         return web.Response(status=416, headers={'Content-Range': f'bytes */{file_size}'})

                    content_length = until_bytes - from_bytes + 1
                    status_code = 206 # 206 ka matlab hai Partial Content (Video Seek hogi)
            except Exception as e:
                logger.error(f"Range Error: {e}")

        # Headers set karo
        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Accept-Ranges': 'bytes',  # Browser ko batao ke hum seek support karte hain
            'Content-Length': str(content_length),
        }

        if status_code == 206:
            headers['Content-Range'] = f'bytes {from_bytes}-{until_bytes}/{file_size}'

        # Response shuru karo
        resp = web.StreamResponse(status=status_code, headers=headers)
        await resp.prepare(request)

        # Telegram se wahi hissa maango jo browser ne maanga hai (offset use karke)
        req_limit = content_length 
        
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=req_limit):
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
        "✅ **Ab Video Forward/Backward bhi kaam karega!**\n"
        "🚀 **Powered by:** Koyeb & Pyrogram"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        # File copy karo channel mein
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        # Link banao
        # APP_URL environment variable Koyeb settings me zaroor daalna
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        
        # File size display logic
        file_size_mb = 0
        fname = "file"
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
