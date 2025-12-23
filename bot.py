import os
import time
import asyncio
import logging
from pyrogram import Client, filters, enums
from aiohttp import web

# --- CONFIGURATION (Environment Variables) ---
# Ye values hum Koyeb ki settings mein daalenge
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID")) # Private Channel ID (starts with -100)
PORT = int(os.environ.get("PORT", 8080))

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT CLIENT ---
# Pyrogram client initialize kar rahe hain
app = Client(
    "my_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- WEB SERVER ROUTES ---
# Ye part direct download/stream link ke liye hai

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    # Sirf check karne ke liye ki bot online hai
    return web.json_response({"status": "running", "uptime": "lifetime"})

@routes.get("/file/{message_id}", allow_head=True)
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        return await media_streamer(request, message_id)
    except Exception as e:
        return web.Response(status=500, text=str(e))

async def media_streamer(request, message_id):
    # Channel se file dhundhna
    try:
        msg = await app.get_messages(CHANNEL_ID, message_id)
        file = getattr(msg, msg.media.value)
        filename = file.file_name or "Unknown_File"
        file_size = file.file_size
        mime_type = file.mime_type or "application/octet-stream"
    except:
        return web.Response(status=404, text="File Not Found")

    # Header set karna taaki browser samajh sake ye download hai ya stream
    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Length": str(file_size)
    }

    # Range header handle karna (video seek/forward karne ke liye zaroori hai)
    range_header = request.headers.get("Range")
    
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
        
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        headers["Content-Length"] = str(until_bytes - from_bytes + 1)
        status_code = 206
    else:
        from_bytes = 0
        until_bytes = file_size - 1
        status_code = 200

    # Generator function jo file ko chunks mein client ko bhejega
    async def file_generator():
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=until_bytes - from_bytes + 1):
            yield chunk

    return web.Response(
        status=status_code,
        headers=headers,
        body=file_generator()
    )

# --- BOT COMMANDS & HANDLERS ---

@app.on_message(filters.command("start"))
async def start(client, message):
    # Jab koi /start dabaye
    await message.reply_text(
        "👋 **Hello!**\n\n"
        "Main ek Permanent File Store Bot hoon.\n"
        "Mujhe koi bhi File ya Video bhejein, main uska **Lifetime Direct Link** bana dunga.\n\n"
        "🚀 *Powered by Koyeb (Free)*"
    )

@app.on_message(filters.document | filters.video | filters.audio)
async def file_handler(client, message):
    # Jab user file bheje
    status_msg = await message.reply_text("🔄 **Processing...**\nFile channel mein upload ho rahi hai...")

    try:
        # 1. File ko Database Channel mein copy karein (Upload se fast hota hai)
        # Copy_message method file ko dobara upload nahi karta, bas forward jaisa copy karta hai
        db_msg = await message.copy(chat_id=CHANNEL_ID)
        
        # 2. Links generate karein
        # Koyeb app ka URL environment variable se ya auto-detect (yahan hum assumption le rahe hain)
        # Note: Koyeb deploy hone ke baad aapko jo URL milega, wo yahan use hoga.
        # Lekin dynamic rakhne ke liye hum manual domain use kar sakte hain ya user ko setup mein batana hoga.
        
        # NOTE: Is code mein 'WEB_URL' environment variable zaroori hai
        online_url = os.environ.get("WEB_URL", "http://localhost:8080")
        stream_link = f"{online_url}/file/{db_msg.id}"
        
        # File details nikalna
        media = getattr(message, message.media.value)
        filename = media.file_name or "Unknown"
        size_mb = round(media.file_size / (1024 * 1024), 2)

        # 3. User ko reply karein
        await status_msg.edit_text(
            f"✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{filename}`\n"
            f"📦 **Size:** `{size_mb} MB`\n\n"
            f"🎬 **Stream:** [Click Here]({stream_link})\n"
            f"⬇️ **Download:** [Click Here]({stream_link})\n\n"
            f"⏰ **Validity:** Lifetime ♾️",
            disable_web_page_preview=True
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")

# --- MAIN RUNNER ---

async def start_services():
    # Web server aur Bot dono ko ek saath start karna
    runner = web.AppRunner(web.Application(client_max_size=30000000))
    # Routes add karna
    runner.app.add_routes(routes)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    print(f"🌍 Web Server Started on Port {PORT}")
    print("🤖 Bot Starting...")
    
    await app.start()
    # Bot ko rokne se bachane ke liye idle rakhna
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
