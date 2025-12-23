import os
import asyncio
import math
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client, errors
from aiohttp import web

# --- CONFIGURATION (Environment Variables se values lega) ---
# Koyeb par yeh variables set karne honge
API_ID = int(os.environ.get("API_ID", "12345")) # Apna API ID yahan default mein na dalein, Env Var use karein
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100123456789")) # Bin Channel ID (Must start with -100)
PORT = int(os.environ.get("PORT", "8080"))
HOST_URL = os.environ.get("HOST_URL", "https://your-app-name.koyeb.app") # Deploy hone ke baad wala URL

# Logging setup taki errors dikh sakein
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- PYROGRAM CLIENT SETUP (Streaming ke liye) ---
# Pyrogram ka use hum sirf file stream karne aur channel se link lene ke liye karenge
# Hum 'no_updates=True' use karenge taki yeh bot commands ke liye clash na kare
pyro_client = Client(
    "stream_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    no_updates=True 
)

# --- HELPER FUNCTIONS ---

def get_readable_size(size):
    # File size ko MB/GB mein convert karne ke liye
    if size == 0:
        return "0B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 2)
    return f"{s} {units[i]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /start command ka response
    await update.message.reply_text(
        "👋 **Salam! Main File Stream Bot hun.**\n\n"
        "Mujhe koi bhi file ya video bhejo, main uska **Permanent Direct Link** bana dunga.\n"
        "Link se aap video online play bhi kar sakte hain (Stream) aur download bhi!",
        parse_mode="Markdown"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Jab user file bhejta hai
    msg = update.message
    # Check karein file hai ya nahi
    if not (msg.document or msg.video or msg.audio):
        return

    # User ko batayein ki process ho raha hai
    status_msg = await msg.reply_text("🔄 **Processing...**\nFile channel pe upload ho rahi hai...")

    try:
        # File ka naam aur ID nikalein
        file_name = msg.document.file_name if msg.document else (msg.video.file_name if msg.video else "file")
        file_size = msg.document.file_size if msg.document else (msg.video.file_size if msg.video else msg.audio.file_size)
        
        # NOTE: File ko hum 'forward' kar rahe hain private channel mein.
        # Yeh sabse fast method hai, file re-upload nahi hoti, bas forward hoti hai.
        # forward_messages method python-telegram-bot ka use kar rahe hain.
        forwarded_msg = await msg.forward(chat_id=CHANNEL_ID)
        
        # Message ID jo channel mein mila
        msg_id = forwarded_msg.message_id
        
        # Links generate karein
        # Link format: https://domain.com/stream/message_id
        stream_link = f"{HOST_URL}/stream/{msg_id}"
        download_link = f"{HOST_URL}/download/{msg_id}"

        # User ko final message bhejein
        text = (
            "✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"📦 **Size:** `{get_readable_size(file_size)}`\n\n"
            f"🎬 **Stream:** [Click Here]({stream_link})\n"
            f"⬇️ **Download:** [Click Here]({download_link})\n\n"
            "⏰ **Validity:** Lifetime ♾️"
        )
        
        keyboard = [[InlineKeyboardButton("🎬 Watch / Download", url=stream_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aaya: {str(e)}")

# --- AIOHTTP SERVER HANDLERS (Streaming Logic) ---

async def stream_handler(request):
    # Yeh function browser requests handle karega
    try:
        # URL se message_id nikalo (e.g., /stream/123 -> 123)
        message_id = int(request.match_info['message_id'])
        
        # Pyrogram se message fetch karein channel se
        try:
            message = await pyro_client.get_messages(CHANNEL_ID, message_id)
            if message.empty:
                return web.Response(status=404, text="File not found in channel.")
            media = message.video or message.document or message.audio
            if not media:
                return web.Response(status=404, text="Not a media file.")
        except Exception as e:
            return web.Response(status=400, text=f"File fetch error: {e}")

        # File properties
        file_size = media.file_size
        mime_type = media.mime_type or "application/octet-stream"
        file_name = media.file_name or "video.mp4"

        # Range Header Handle karna (Video seek/forward ke liye zaroori)
        range_header = request.headers.get("Range")
        
        if range_header:
            # Browser ne specific hissa manga hai (seeking)
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
            
            content_length = (until_bytes - from_bytes) + 1
            
            # Pyrogram ka 'stream_media' use karke specific chunk download/stream karein
            # Offset = kahan se shuru karna hai
            body = pyro_client.stream_media(message, offset=from_bytes, limit=content_length)
            
            return web.Response(
                body=body,
                status=206, # 206 means Partial Content (streaming works)
                headers={
                    "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                    "Content-Length": str(content_length),
                    "Content-Type": mime_type,
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'inline; filename="{file_name}"'
                }
            )
        else:
            # Agar full file maangi gayi hai (download)
            body = pyro_client.stream_media(message)
            return web.Response(
                body=body,
                status=200,
                headers={
                    "Content-Length": str(file_size),
                    "Content-Type": mime_type,
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'attachment; filename="{file_name}"'
                }
            )

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Internal Server Error")

async def health_check(request):
    return web.Response(text="Bot is Alive!", status=200)

# --- MAIN EXECUTION ---

async def main():
    # 1. Pyrogram Client Start karein
    await pyro_client.start()
    print("✅ Pyrogram Client Started (Backend)")

    # 2. Python-Telegram-Bot Application Setup
    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))
    
    # PTB ko initialize aur start karein (Polling mode mein)
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.updater.start_polling()
    print("✅ Bot Started Polling (Frontend)")

    # 3. Web Server Setup (aiohttp)
    server_app = web.Application()
    server_app.router.add_get("/", health_check) # Health check endpoint
    server_app.router.add_get("/stream/{message_id}", stream_handler)
    server_app.router.add_get("/download/{message_id}", stream_handler) # Download route bhi same logic use karega

    runner = web.AppRunner(server_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Web Server Running on Port {PORT}")

    # Process ko alive rakhne ke liye infinite loop
    # Hum yahan 'Event' ka wait karenge taaki script band na ho
    stop_event = asyncio.Event()
    await stop_event.wait()

    # Cleanup (Jab bot stop ho)
    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()
    await pyro_client.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
