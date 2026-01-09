import os
import asyncio
import logging
import signal
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiohttp import web
import motor.motor_asyncio

# ============ CONFIGURATION ============
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))
APP_URL = os.environ.get("APP_URL", "")
MONGO_URI = os.environ.get("MONGO_URI", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]
AUTO_DELETE_TIME = 5

# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ DATABASE ============
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client["filebot"]
users_col = db["users"]
files_col = db["files"]
banned_col = db["banned"]
thumbs_col = db["thumbnails"]

# ============ BOT CLIENT ============
bot = Client(
    "FileStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=8,
    sleep_threshold=30
)

# Batch sessions store
batch_sessions = {}

# Keep alive flag
is_running = True

# ============ DATABASE FUNCTIONS ============
async def add_user(user_id: int, username: str = None):
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "username": username, "joined": datetime.now()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Add user error: {e}")

async def is_banned(user_id: int) -> bool:
    try:
        user = await banned_col.find_one({"user_id": user_id})
        return user is not None
    except:
        return False

async def ban_user(user_id: int):
    await banned_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "banned_at": datetime.now()}},
        upsert=True
    )

async def unban_user(user_id: int):
    await banned_col.delete_one({"user_id": user_id})

async def save_thumbnail(user_id: int, file_id: str):
    await thumbs_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "file_id": file_id}},
        upsert=True
    )

async def get_thumbnail(user_id: int):
    thumb = await thumbs_col.find_one({"user_id": user_id})
    return thumb.get("file_id") if thumb else None

async def delete_thumbnail(user_id: int):
    await thumbs_col.delete_one({"user_id": user_id})

async def get_stats():
    try:
        total_users = await users_col.count_documents({})
        total_files = await files_col.count_documents({})
        banned_users = await banned_col.count_documents({})
        return total_users, total_files, banned_users
    except:
        return 0, 0, 0

async def save_file(file_id: str, file_name: str, file_size: int, user_id: int):
    await files_col.update_one(
        {"file_id": file_id},
        {"$set": {
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "user_id": user_id,
            "uploaded_at": datetime.now()
        }},
        upsert=True
    )

# ============ AUTO DELETE FUNCTION ============
async def auto_delete(message: Message, delay: int = AUTO_DELETE_TIME):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

# ============ BOT COMMANDS ============
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    if await is_banned(user_id):
        reply = await message.reply("❌ Aap banned hain!")
        asyncio.create_task(auto_delete(reply))
        return
    
    await add_user(user_id, username)
    
    welcome_text = """
🎬 **File Stream Bot**

Mujhe koi bhi file bhejo aur main tumhe:
• 📥 Direct Download Link
• 🎥 Universal Stream Link (VLC/MX Player compatible)

**Commands:**
/start - Bot shuru karo
/batch - Multiple files ka ek link
/done - Batch complete karo
/setthumb - Thumbnail set karo
/delthumb - Thumbnail delete karo
/stats - Bot statistics
"""
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel", url="https://t.me/yourchannel")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/yoursupport")]
    ])
    
    reply = await message.reply(welcome_text, reply_markup=buttons)
    asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message: Message):
    total_users, total_files, banned_users = await get_stats()
    
    stats_text = f"""
📊 **Bot Statistics**

👥 Total Users: {total_users}
📁 Total Files: {total_files}
🚫 Banned Users: {banned_users}
"""
    reply = await message.reply(stats_text)
    asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("ban") & filters.private)
async def ban_command(client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        reply = await message.reply("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply("Usage: /ban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        target_id = int(message.command[1])
        await ban_user(target_id)
        reply = await message.reply(f"✅ User {target_id} banned!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("unban") & filters.private)
async def unban_command(client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        reply = await message.reply("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply("Usage: /unban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        target_id = int(message.command[1])
        await unban_user(target_id)
        reply = await message.reply(f"✅ User {target_id} unbanned!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("setthumb") & filters.private)
async def set_thumbnail(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        reply = await message.reply("❌ Kisi photo pe reply karo!")
        asyncio.create_task(auto_delete(reply))
        return
    
    file_id = message.reply_to_message.photo.file_id
    await save_thumbnail(message.from_user.id, file_id)
    reply = await message.reply("✅ Thumbnail save ho gaya!")
    asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("delthumb") & filters.private)
async def del_thumbnail(client, message: Message):
    await delete_thumbnail(message.from_user.id)
    reply = await message.reply("✅ Thumbnail delete ho gaya!")
    asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("batch") & filters.private)
async def batch_start(client, message: Message):
    user_id = message.from_user.id
    
    if await is_banned(user_id):
        reply = await message.reply("❌ Aap banned hain!")
        asyncio.create_task(auto_delete(reply))
        return
    
    batch_sessions[user_id] = []
    reply = await message.reply("📦 Batch mode ON! Ab files bhejo aur phir /done likho.")
    asyncio.create_task(auto_delete(reply))

@bot.on_message(filters.command("done") & filters.private)
async def batch_done(client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in batch_sessions or not batch_sessions[user_id]:
        reply = await message.reply("❌ Koi batch nahi hai! Pehle /batch use karo.")
        asyncio.create_task(auto_delete(reply))
        return
    
    files = batch_sessions[user_id]
    batch_id = f"batch_{user_id}_{int(datetime.now().timestamp())}"
    
    await db["batches"].insert_one({
        "batch_id": batch_id,
        "files": files,
        "user_id": user_id,
        "created_at": datetime.now()
    })
    
    batch_link = f"{APP_URL}/batch/{batch_id}"
    
    reply = await message.reply(
        f"✅ **Batch Ready!**\n\n"
        f"📁 Files: {len(files)}\n"
        f"🔗 Link: `{batch_link}`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Open Batch", url=batch_link)]
        ])
    )
    asyncio.create_task(auto_delete(reply))
    
    del batch_sessions[user_id]

# ============ FILE HANDLER ============
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_file(client, message: Message):
    user_id = message.from_user.id
    
    if await is_banned(user_id):
        reply = await message.reply("❌ Aap banned hain!")
        asyncio.create_task(auto_delete(reply))
        return
    
    await add_user(user_id, message.from_user.username)
    
    forwarded = await message.forward(CHANNEL_ID)
    message_id = forwarded.id
    
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "file"
        file_size = message.document.file_size
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        file_size = message.video.file_size
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        file_size = message.audio.file_size
    elif message.photo:
        file_id = message.photo.file_id
        file_name = "photo.jpg"
        file_size = message.photo.file_size
    else:
        return
    
    await save_file(file_id, file_name, file_size, user_id)
    
    if user_id in batch_sessions:
        batch_sessions[user_id].append({
            "message_id": message_id,
            "file_name": file_name,
            "file_size": file_size
        })
        reply = await message.reply(f"✅ Added to batch: {file_name}")
        asyncio.create_task(auto_delete(reply))
        return
    
    stream_link = f"{APP_URL}/stream/{message_id}/{file_name}"
    download_link = f"{APP_URL}/download/{message_id}/{file_name}"
    
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
    
    reply_text = f"""
✅ **File Uploaded Successfully!**

📁 **Name:** `{file_name}`
📦 **Size:** {format_size(file_size)}

🎥 **Stream Link (VLC/MX Player):**
`{stream_link}`

📥 **Download Link:**
`{download_link}`
"""
    
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 Stream", url=stream_link),
            InlineKeyboardButton("📥 Download", url=download_link)
        ],
        [InlineKeyboardButton("📱 Open in VLC", url=f"vlc://{stream_link}")]
    ])
    
    reply = await message.reply(reply_text, reply_markup=buttons)
    asyncio.create_task(auto_delete(reply))

# ============ WEB SERVER ============
async def health_check(request):
    """Health check endpoint for Koyeb"""
    return web.Response(text="OK", status=200)

async def home(request):
    return web.Response(
        text="<h1>🤖 File Stream Bot is Running!</h1><p>Status: Healthy</p>",
        content_type="text/html"
    )

async def handle_stream(request):
    message_id = int(request.match_info["message_id"])
    file_name = request.match_info["file_name"]
    
    try:
        message = await bot.get_messages(CHANNEL_ID, message_id)
        
        if not message:
            return web.Response(status=404, text="File not found")
        
        if message.document:
            file = message.document
            mime_type = message.document.mime_type or "application/octet-stream"
        elif message.video:
            file = message.video
            mime_type = message.video.mime_type or "video/mp4"
        elif message.audio:
            file = message.audio
            mime_type = message.audio.mime_type or "audio/mpeg"
        elif message.photo:
            file = message.photo
            mime_type = "image/jpeg"
        else:
            return web.Response(status=404, text="No file found")
        
        file_size = file.file_size
        
        range_header = request.headers.get("Range")
        start = 0
        end = file_size - 1
        
        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
        
        response = web.StreamResponse(
            status=206 if range_header else 200,
            headers={
                "Content-Type": mime_type,
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Disposition": f"inline; filename=\"{file_name}\"",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range",
                "Cache-Control": "no-cache",
            }
        )
        
        await response.prepare(request)
        
        current_pos = 0
        async for chunk in bot.stream_media(message, offset=start):
            if current_pos + len(chunk) > (end - start + 1):
                chunk = chunk[:end - start + 1 - current_pos]
            await response.write(chunk)
            current_pos += len(chunk)
            if current_pos >= (end - start + 1):
                break
        
        return response
        
    except Exception as e:
        logger.error(f"Stream error: {e}")
        return web.Response(status=500, text=str(e))

async def handle_download(request):
    message_id = int(request.match_info["message_id"])
    file_name = request.match_info["file_name"]
    
    try:
        message = await bot.get_messages(CHANNEL_ID, message_id)
        
        if not message:
            return web.Response(status=404, text="File not found")
        
        if message.document:
            file = message.document
            mime_type = message.document.mime_type or "application/octet-stream"
        elif message.video:
            file = message.video
            mime_type = message.video.mime_type or "video/mp4"
        elif message.audio:
            file = message.audio
            mime_type = message.audio.mime_type or "audio/mpeg"
        elif message.photo:
            file = message.photo
            mime_type = "image/jpeg"
        else:
            return web.Response(status=404, text="No file found")
        
        file_size = file.file_size
        
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": mime_type,
                "Content-Length": str(file_size),
                "Content-Disposition": f"attachment; filename=\"{file_name}\"",
                "Access-Control-Allow-Origin": "*",
            }
        )
        
        await response.prepare(request)
        
        async for chunk in bot.stream_media(message):
            await response.write(chunk)
        
        return response
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return web.Response(status=500, text=str(e))

async def handle_batch(request):
    batch_id = request.match_info["batch_id"]
    
    batch = await db["batches"].find_one({"batch_id": batch_id})
    
    if not batch:
        return web.Response(status=404, text="Batch not found")
    
    files = batch["files"]
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Batch Files</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
            color: white;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        h1 {{ text-align: center; margin-bottom: 30px; }}
        .file-card {{
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            backdrop-filter: blur(10px);
        }}
        .file-name {{ font-weight: bold; margin-bottom: 10px; word-break: break-all; }}
        .file-size {{ color: #888; font-size: 14px; margin-bottom: 15px; }}
        .buttons {{ display: flex; gap: 10px; flex-wrap: wrap; }}
        .btn {{
            padding: 10px 20px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
            display: inline-block;
        }}
        .btn-stream {{ background: #4CAF50; color: white; }}
        .btn-download {{ background: #2196F3; color: white; }}
        .btn-vlc {{ background: #FF9800; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📦 Batch Files ({len(files)})</h1>
"""
    
    for f in files:
        stream_url = f"{APP_URL}/stream/{f['message_id']}/{f['file_name']}"
        download_url = f"{APP_URL}/download/{f['message_id']}/{f['file_name']}"
        vlc_url = f"vlc://{stream_url}"
        
        size_mb = f['file_size'] / (1024 * 1024)
        
        html += f"""
        <div class="file-card">
            <div class="file-name">📁 {f['file_name']}</div>
            <div class="file-size">📦 {size_mb:.2f} MB</div>
            <div class="buttons">
                <a href="{stream_url}" class="btn btn-stream">🎥 Stream</a>
                <a href="{download_url}" class="btn btn-download">📥 Download</a>
                <a href="{vlc_url}" class="btn btn-vlc">📱 VLC</a>
            </div>
        </div>
"""
    
    html += """
    </div>
</body>
</html>
"""
    
    return web.Response(text=html, content_type="text/html")

async def handle_options(request):
    return web.Response(
        status=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type",
        }
    )

def create_app():
    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/health", health_check)
    app.router.add_get("/stream/{message_id}/{file_name}", handle_stream)
    app.router.add_get("/download/{message_id}/{file_name}", handle_download)
    app.router.add_get("/batch/{batch_id}", handle_batch)
    app.router.add_route("OPTIONS", "/{path:.*}", handle_options)
    return app

async def start_services():
    """Start both web server and bot"""
    global is_running
    
    # Create and start web server first
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server started on port {PORT}")
    
    # Start bot
    await bot.start()
    logger.info("✅ Bot started successfully!")
    
     # Keep running
    while is_running:
        await asyncio.sleep(1)
    
    # Cleanup
    logger.info("Shutting down...")
    await bot.stop()
    await runner.cleanup()

def signal_handler(sig, frame):
    global is_running
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    is_running = False

if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        loop.close()
