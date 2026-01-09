import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", "8080"))
MONGO_URI = os.environ.get("MONGO_URI", "")  # MongoDB URI
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]  # Admin user IDs
AUTO_DELETE_TIME = 5  # Seconds

CHUNK_SIZE = 1024 * 1024  # 1MB chunks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGO_URI) if MONGO_URI else None
db = mongo_client["file_bot"] if mongo_client else None
users_col = db["users"] if db else None
files_col = db["files"] if db else None
banned_col = db["banned"] if db else None
thumbnails_col = db["thumbnails"] if db else None

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============== DATABASE FUNCTIONS ==============

async def add_user(user_id, name):
    if users_col:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "name": name, "joined": datetime.now()}},
            upsert=True
        )

async def get_total_users():
    if users_col:
        return await users_col.count_documents({})
    return 0

async def add_file_stat():
    if files_col:
        await files_col.insert_one({"uploaded_at": datetime.now()})

async def get_total_files():
    if files_col:
        return await files_col.count_documents({})
    return 0

async def is_banned(user_id):
    if banned_col:
        user = await banned_col.find_one({"user_id": user_id})
        return user is not None
    return False

async def ban_user(user_id):
    if banned_col:
        await banned_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "banned_at": datetime.now()}},
            upsert=True
        )

async def unban_user(user_id):
    if banned_col:
        await banned_col.delete_one({"user_id": user_id})

async def save_thumbnail(user_id, file_id):
    if thumbnails_col:
        await thumbnails_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "file_id": file_id}},
            upsert=True
        )

async def get_thumbnail(user_id):
    if thumbnails_col:
        doc = await thumbnails_col.find_one({"user_id": user_id})
        return doc.get("file_id") if doc else None
    return None

async def delete_thumbnail(user_id):
    if thumbnails_col:
        await thumbnails_col.delete_one({"user_id": user_id})


# ============== HELPER FUNCTIONS ==============

def get_file_info(msg):
    file_name = "file"
    file_size = 0
    mime_type = "application/octet-stream"

    if msg.document:
        file_name = msg.document.file_name or "document"
        file_size = msg.document.file_size
        mime_type = msg.document.mime_type or "application/octet-stream"
    elif msg.video:
        file_name = msg.video.file_name or "video.mp4"
        file_size = msg.video.file_size
        mime_type = msg.video.mime_type or "video/mp4"
    elif msg.audio:
        file_name = msg.audio.file_name or "audio.mp3"
        file_size = msg.audio.file_size
        mime_type = msg.audio.mime_type or "audio/mpeg"

    return file_name, file_size, mime_type


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def auto_delete(message, delay=AUTO_DELETE_TIME):
    """Auto delete message after delay"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Auto delete error: {e}")


# ============== STREAM HANDLERS ==============

async def handle_stream(request):
    """Universal Stream - Works with VLC, MX Player, Browser"""
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)

        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

        file_name, file_size, mime_type = get_file_info(msg)

        # Range header parsing for seek support
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

        # ✅ Universal Headers - VLC/MX Player Compatible
        headers = {
            'Content-Type': mime_type,
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range',
            'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
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
        logger.info("Stream cancelled by client")
        raise
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)


async def handle_download(request):
    """Download Handler with Resume Support"""
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)

        if not msg or not msg.media:
            return web.Response(text="File not found or deleted.", status=404)

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
            'Access-Control-Allow-Origin': '*',
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
        logger.info("Download cancelled by client")
        raise
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return web.Response(text="Link Expired or Server Error", status=500)


# ✅ Batch Stream Handler
async def handle_batch(request):
    """Batch Stream - Multiple files in one page"""
    try:
        batch_ids = request.match_info['batch_ids']
        message_ids = [int(x) for x in batch_ids.split("-")]
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Batch Files</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; background: #1a1a2e; color: #fff; padding: 20px; }
                .file-card { background: #16213e; padding: 15px; margin: 10px 0; border-radius: 10px; }
                .file-name { font-size: 18px; margin-bottom: 10px; }
                .btn { display: inline-block; padding: 10px 20px; margin: 5px; border-radius: 5px; text-decoration: none; }
                .stream-btn { background: #e94560; color: #fff; }
                .download-btn { background: #0f3460; color: #fff; }
                video { width: 100%; max-width: 640px; margin-top: 10px; }
            </style>
        </head>
        <body>
            <h1>📦 Batch Files</h1>
        """
        
        for msg_id in message_ids:
            try:
                msg = await app.get_messages(CHANNEL_ID, msg_id)
                if msg and msg.media:
                    file_name, file_size, mime_type = get_file_info(msg)
                    size_mb = round(file_size / (1024 * 1024), 2)
                    
                    html_content += f"""
                    <div class="file-card">
                        <div class="file-name">📄 {file_name} ({size_mb} MB)</div>
                        <a href="{base_url}/stream/{msg_id}" class="btn stream-btn">🎬 Stream</a>
                        <a href="{base_url}/download/{msg_id}" class="btn download-btn">⬇️ Download</a>
                    """
                    
                    if mime_type.startswith("video"):
                        html_content += f"""
                        <video controls>
                            <source src="{base_url}/stream/{msg_id}" type="{mime_type}">
                        </video>
                        """
                    
                    html_content += "</div>"
            except:
                pass
        
        html_content += "</body></html>"
        
        return web.Response(text=html_content, content_type='text/html')
        
    except Exception as e:
        logger.error(f"Batch Error: {e}")
        return web.Response(text="Error loading batch", status=500)


async def handle_options(request):
    """CORS Preflight Handler"""
    return web.Response(headers={
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Range',
    })


async def health_check(request):
    return web.Response(text="Bot is running! 24/7 Service.")


# ============== BOT COMMANDS ==============

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    
    # Check if banned
    if await is_banned(user_id):
        await message.reply_text("❌ Aap is bot se banned hain!")
        return
    
    # Add user to database
    await add_user(user_id, message.from_user.first_name)
    
    reply = await message.reply_text(
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File ya Video bhejo, main uska **Permanent Direct Link** bana dunga.\n\n"
        "🎬 **Stream:** VLC/MX Player mein bhi chalega\n"
        "⬇️ **Download:** Resume support ke saath\n"
        "📦 **Batch:** Multiple files ki ek link\n\n"
        "📋 **Commands:**\n"
        "/batch - Multiple files ki ek link banao\n"
        "/setthumb - Thumbnail set karo\n"
        "/delthumb - Thumbnail delete karo\n"
        "/stats - Bot statistics\n\n"
        "🚀 **Created By:** SAIFSALER"
    )
    
    # Auto delete after 5 seconds
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message):
    if await is_banned(message.from_user.id):
        return
    
    total_users = await get_total_users()
    total_files = await get_total_files()
    
    reply = await message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"📁 Total Files: `{total_files}`\n"
        f"🤖 Status: Online ✅"
    )
    
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("ban") & filters.private)
async def ban_command(client, message):
    if not is_admin(message.from_user.id):
        reply = await message.reply_text("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply_text("Usage: /ban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        user_id = int(message.command[1])
        await ban_user(user_id)
        reply = await message.reply_text(f"✅ User `{user_id}` banned successfully!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply_text("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("unban") & filters.private)
async def unban_command(client, message):
    if not is_admin(message.from_user.id):
        reply = await message.reply_text("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply_text("Usage: /unban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        user_id = int(message.command[1])
        await unban_user(user_id)
        reply = await message.reply_text(f"✅ User `{user_id}` unbanned successfully!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply_text("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("setthumb") & filters.private)
async def set_thumbnail(client, message):
    if await is_banned(message.from_user.id):
        return
    
    if not message.reply_to_message or not message.reply_to_message.photo:
        reply = await message.reply_text("❌ Kisi photo pe reply karke /setthumb likho!")
        asyncio.create_task(auto_delete(reply))
        return
    
    photo = message.reply_to_message.photo.file_id
    await save_thumbnail(message.from_user.id, photo)
    
    reply = await message.reply_text("✅ Thumbnail saved successfully!")
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("delthumb") & filters.private)
async def del_thumbnail(client, message):
    if await is_banned(message.from_user.id):
        return
    
    await delete_thumbnail(message.from_user.id)
    reply = await message.reply_text("✅ Thumbnail deleted!")
    asyncio.create_task(auto_delete(reply))


# ✅ Batch Command
batch_sessions = {}

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    if await is_banned(message.from_user.id):
        return
    
    user_id = message.from_user.id
    batch_sessions[user_id] = []
    
    reply = await message.reply_text(
        "📦 **Batch Mode Started!**\n\n"
        "Ab mujhe saari files bhejo jo batch mein chahiye.\n"
        "Jab done ho jao to /done likho.\n"
        "Cancel karne ke liye /cancel likho."
    )
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("done") & filters.private)
async def batch_done(client, message):
    user_id = message.from_user.id
    
    if user_id not in batch_sessions or not batch_sessions[user_id]:
        reply = await message.reply_text("❌ Koi batch start nahi hai ya files nahi hain!")
        asyncio.create_task(auto_delete(reply))
        return
    
    message_ids = batch_sessions[user_id]
    batch_id = "-".join([str(x) for x in message_ids])
    base_url = os.environ.get("APP_URL", "http://localhost:8080")
    batch_link = f"{base_url}/batch/{batch_id}"
    
    reply = await message.reply_text(
        f"✅ **Batch Link Ready!**\n\n"
        f"📦 Total Files: `{len(message_ids)}`\n\n"
        f"🔗 **Batch Link:**\n{batch_link}\n\n"
        "⏰ **Validity:** Lifetime ♾️"
    )
    
    del batch_sessions[user_id]
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("cancel") & filters.private)
async def batch_cancel(client, message):
    user_id = message.from_user.id
    
    if user_id in batch_sessions:
        del batch_sessions[user_id]
    
    reply = await message.reply_text("❌ Batch cancelled!")
    asyncio.create_task(auto_delete(reply))


# ============== FILE HANDLER ==============

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    user_id = message.from_user.id
    
    if await is_banned(user_id):
        return
    
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        # Add to batch if batch mode is active
        if user_id in batch_sessions:
            batch_sessions[user_id].append(msg_id)
            await status_msg.edit_text(
                f"✅ File #{len(batch_sessions[user_id])} batch mein add ho gayi!\n"
                "Aur files bhejo ya /done likho."
            )
            asyncio.create_task(auto_delete(status_msg))
            return
        
        # Add file stat
        await add_file_stat()
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        download_link = f"{base_url}/download/{msg_id}"

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
            f"🎬 **Stream Link (VLC/MX Player):**\n`{stream_link}`\n\n"
            f"⬇️ **Download Link:**\n`{download_link}`\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "📱 **VLC/MX Player:** Stream link copy karke Open Network Stream mein paste karo"
        )

        await status_msg.edit_text(response_text, disable_web_page_preview=True)
        
        # Auto delete after 5 seconds
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client, message):
    if await is_banned(message.from_user.id):
        return
    
    total_users = await get_total_users()
    total_files = await get_total_files()
    
    reply = await message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"📁 Total Files: `{total_files}`\n"
        f"🤖 Status: Online ✅"
    )
    
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("ban") & filters.private)
async def ban_command(client, message):
    if not is_admin(message.from_user.id):
        reply = await message.reply_text("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply_text("Usage: /ban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        user_id = int(message.command[1])
        await ban_user(user_id)
        reply = await message.reply_text(f"✅ User `{user_id}` banned successfully!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply_text("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("unban") & filters.private)
async def unban_command(client, message):
    if not is_admin(message.from_user.id):
        reply = await message.reply_text("❌ Sirf admin ye command use kar sakta hai!")
        asyncio.create_task(auto_delete(reply))
        return
    
    if len(message.command) < 2:
        reply = await message.reply_text("Usage: /unban user_id")
        asyncio.create_task(auto_delete(reply))
        return
    
    try:
        user_id = int(message.command[1])
        await unban_user(user_id)
        reply = await message.reply_text(f"✅ User `{user_id}` unbanned successfully!")
        asyncio.create_task(auto_delete(reply))
    except:
        reply = await message.reply_text("❌ Invalid user ID!")
        asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("setthumb") & filters.private)
async def set_thumbnail(client, message):
    if await is_banned(message.from_user.id):
        return
    
    if not message.reply_to_message or not message.reply_to_message.photo:
        reply = await message.reply_text("❌ Kisi photo pe reply karke /setthumb likho!")
        asyncio.create_task(auto_delete(reply))
        return
    
    photo = message.reply_to_message.photo.file_id
    await save_thumbnail(message.from_user.id, photo)
    
    reply = await message.reply_text("✅ Thumbnail saved successfully!")
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("delthumb") & filters.private)
async def del_thumbnail(client, message):
    if await is_banned(message.from_user.id):
        return
    
    await delete_thumbnail(message.from_user.id)
    reply = await message.reply_text("✅ Thumbnail deleted!")
    asyncio.create_task(auto_delete(reply))


# ✅ Batch Command
batch_sessions = {}

@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    if await is_banned(message.from_user.id):
        return
    
    user_id = message.from_user.id
    batch_sessions[user_id] = []
    
    reply = await message.reply_text(
        "📦 **Batch Mode Started!**\n\n"
        "Ab mujhe saari files bhejo jo batch mein chahiye.\n"
        "Jab done ho jao to /done likho.\n"
        "Cancel karne ke liye /cancel likho."
    )
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("done") & filters.private)
async def batch_done(client, message):
    user_id = message.from_user.id
    
    if user_id not in batch_sessions or not batch_sessions[user_id]:
        reply = await message.reply_text("❌ Koi batch start nahi hai ya files nahi hain!")
        asyncio.create_task(auto_delete(reply))
        return
    
    message_ids = batch_sessions[user_id]
    batch_id = "-".join([str(x) for x in message_ids])
    base_url = os.environ.get("APP_URL", "http://localhost:8080")
    batch_link = f"{base_url}/batch/{batch_id}"
    
    reply = await message.reply_text(
        f"✅ **Batch Link Ready!**\n\n"
        f"📦 Total Files: `{len(message_ids)}`\n\n"
        f"🔗 **Batch Link:**\n{batch_link}\n\n"
        "⏰ **Validity:** Lifetime ♾️"
    )
    
    del batch_sessions[user_id]
    asyncio.create_task(auto_delete(reply))


@app.on_message(filters.command("cancel") & filters.private)
async def batch_cancel(client, message):
    user_id = message.from_user.id
    
    if user_id in batch_sessions:
        del batch_sessions[user_id]
    
    reply = await message.reply_text("❌ Batch cancelled!")
    asyncio.create_task(auto_delete(reply))


# ============== FILE HANDLER ==============

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(client, message):
    user_id = message.from_user.id
    
    if await is_banned(user_id):
        return
    
    status_msg = await message.reply_text("⏳ **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        log_msg = await message.copy(CHANNEL_ID)
        msg_id = log_msg.id
        
        # Add to batch if batch mode is active
        if user_id in batch_sessions:
            batch_sessions[user_id].append(msg_id)
            await status_msg.edit_text(
                f"✅ File #{len(batch_sessions[user_id])} batch mein add ho gayi!\n"
                "Aur files bhejo ya /done likho."
            )
            asyncio.create_task(auto_delete(status_msg))
            return
        
        # Add file stat
        await add_file_stat()
        
        base_url = os.environ.get("APP_URL", "http://localhost:8080")
        
        stream_link = f"{base_url}/stream/{msg_id}"
        download_link = f"{base_url}/download/{msg_id}"

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
            f"🎬 **Stream Link (VLC/MX Player):**\n`{stream_link}`\n\n"
            f"⬇️ **Download Link:**\n`{download_link}`\n\n"
            "⏰ **Validity:** Lifetime ♾️\n"
            "📱 **VLC/MX Player:** Stream link copy karke Open Network Stream mein paste karo"
        )

        await status_msg.edit_text(response_text, disable_web_page_preview=True)
        
        # Auto delete after 5 seconds
        asyncio.create_task(auto_delete(status_msg))

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")
        asyncio.create_task(auto_delete(status_msg))


# ============== MAIN ==============

async def start_services():
    await app.start()
    logger.info("🤖 Bot started successfully!")

    web_app = web.Application()
    web_app.router.add_get('/stream/{message_id}', handle_stream)
    web_app.router.add_get('/download/{message_id}', handle_download)
    web_app.router.add_get('/batch/{batch_ids}', handle_batch)
    web_app.router.add_options('/stream/{message_id}', handle_options)
    web_app.router.add_get('/', health_check)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌍 Web Server running on Port {PORT}")

    try:
        from pyrogram import idle
        await idle()
    except ImportError:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_services())
