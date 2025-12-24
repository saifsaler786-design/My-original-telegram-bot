import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ============ CONFIG ============
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = (os.getenv("BASE_URL") or "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))

if not all([API_ID, API_HASH, BOT_TOKEN, BASE_URL]):
    raise RuntimeError("Missing env vars: API_ID, API_HASH, BOT_TOKEN, BASE_URL")

# ============ BOT SETUP ============
app = Client("MyBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
file_cache = {}

# ============ HANDLERS ============
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    text = (
        f"👋 Salam **{message.from_user.first_name}**!\n\n"
        "Mujhe koi bhi File ya Video bhejo, main uska **Permanent Direct Link** bana dunga.\n"
        "Ye link Lifetime kaam karega aur free hai.\n\n"
        "🚀 **Powered by:** Koyeb & Pyrogram"
    )
    await message.reply_text(text)

@app.on_message(filters.private & (filters.video | filters.document | filters.audio | filters.photo))
async def file_handler(client: Client, message: Message):
    media = message.video or message.document or message.audio or message.photo
    
    if message.photo:
        file_id = message.photo.file_id
        file_name = f"photo_{message.id}.jpg"
        file_size = message.photo.file_size
    else:
        file_id = media.file_id
        file_name = getattr(media, "file_name", f"file_{message.id}")
        file_size = media.file_size

    # Cache file info
    msg_id = message.id
    file_cache[msg_id] = {
        "file_id": file_id,
        "file_name": file_name,
        "chat_id": message.chat.id
    }

    size_mb = round(file_size / (1024 * 1024), 2)
    stream_link = f"{BASE_URL}/stream/{message.chat.id}/{msg_id}"
    download_link = f"{BASE_URL}/download/{message.chat.id}/{msg_id}"

    text = (
        "✅ **File Upload Complete!**\n\n"
        f"📄 **File:** `{file_name}`\n"
        f"📦 **Size:** {size_mb} MB\n\n"
        f"🎬 **Stream Link:**\n{stream_link}\n\n"
        f"⬇️ **Download Link:**\n{download_link}\n\n"
        "⏰ **Validity:** Lifetime ∞\n"
        "⚠️ *Note: Link tab tak chalega jab tak bot ON hai.*"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Stream", url=stream_link)],
        [InlineKeyboardButton("⬇️ Download", url=download_link)]
    ])

    await message.reply_text(text, reply_markup=buttons)

# ============ WEB SERVER ============
routes = web.RouteTableDef()

@routes.get("/")
async def home(request):
    return web.Response(text="Bot is running!", content_type="text/html")

@routes.get("/stream/{chat_id}/{msg_id}")
async def stream_file(request):
    chat_id = int(request.match_info["chat_id"])
    msg_id = int(request.match_info["msg_id"])
    
    try:
        message = await app.get_messages(chat_id, msg_id)
        media = message.video or message.document or message.audio or message.photo
        
        if message.photo:
            file_name = f"photo_{msg_id}.jpg"
        else:
            file_name = getattr(media, "file_name", f"file_{msg_id}")

        file_data = await app.download_media(message, in_memory=True)
        
        return web.Response(
            body=bytes(file_data.getbuffer()),
            headers={
                "Content-Disposition": f"inline; filename=\"{file_name}\"",
                "Content-Type": "application/octet-stream"
            }
        )
    except Exception as e:
        return web.Response(text=f"Error: {str(e)}", status=404)

@routes.get("/download/{chat_id}/{msg_id}")
async def download_file(request):
    chat_id = int(request.match_info["chat_id"])
    msg_id = int(request.match_info["msg_id"])
    
    try:
        message = await app.get_messages(chat_id, msg_id)
        media = message.video or message.document or message.audio or message.photo
        
        if message.photo:
            file_name = f"photo_{msg_id}.jpg"
        else:
            file_name = getattr(media, "file_name", f"file_{msg_id}")

        file_data = await app.download_media(message, in_memory=True)
        
        return web.Response(
            body=bytes(file_data.getbuffer()),
            headers={
                "Content-Disposition": f"attachment; filename=\"{file_name}\"",
                "Content-Type": "application/octet-stream"
            }
        )
    except Exception as e:
        return web.Response(text=f"Error: {str(e)}", status=404)

# ============ MAIN ============
async def main():
    web_app = web.Application()
    web_app.add_routes(routes)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    await app.start()
    print(f"Bot started! Web server on port {PORT}")
    await site.start()
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
    
