import asyncio
import logging
import os
import tempfile
from typing import Dict, Any
from datetime import datetime

from config import config
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from pyrogram import Client
from pyrogram.types import Message
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import aiofiles

# ====================
# LOGGING SETUP
# ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====================
# GLOBALS AUR SETUP
# ====================
app = FastAPI(title="Telegram File Hosting Bot", docs_url=None, redoc_url=None)

# File storage (temporary - Koyeb restart hone par data lost ho jayega)
# Agar permanent chahiye to database use karein
file_store: Dict[str, Dict[str, Any]] = {}

# Pyrogram client for Telegram API
pyro_client = Client(
    "my_bot_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True
)

# ====================
# PART 1: WEB SERVER ROUTES (KOYEB KA LINK BANANE KE LIYE)
# ====================
@app.get("/")
async def home():
    """Home page - Bot online hai ya nahi check karne ke liye"""
    return {
        "status": "online",
        "service": "Telegram File Hosting Bot",
        "your_app_url": config.FQDN,
        "instructions": "Send any file to @YourBotName on Telegram to get a permanent link"
    }

@app.get("/file/{file_id}")
async def serve_file(file_id: str, request: Request):
    """
    YAHAN SE KOYEB KA LINK MILTA HAI!
    Example: https://curly-harriet-saifmovies-1cca6f58.koyeb.app/file/abc123
    """
    logger.info(f"File request received: {file_id}")
    
    # Check if file exists in our storage
    if file_id not in file_store:
        return JSONResponse(
            {"error": "File not found or link expired"},
            status_code=404
        )
    
    file_info = file_store[file_id]
    
    try:
        # Pyrogram client start karein
        await pyro_client.start()
        
        # Channel se message get karein
        msg: Message = await pyro_client.get_messages(
            config.CHANNEL_ID, 
            file_info["message_id"]
        )
        
        # Temporary file banayein download ke liye
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp_file:
            temp_path = tmp_file.name
        
        # File ko download karein
        await pyro_client.download_media(msg, temp_path)
        
        # File type determine karein
        if hasattr(msg, 'video') and msg.video:
            media_type = "video/mp4"
            filename = file_info.get("file_name", "video.mp4")
            
            # VIDEO STREAMING SUPPORT (forward/backward ke liye)
            file_size = os.path.getsize(temp_path)
            range_header = request.headers.get("range")
            
            if range_header and media_type.startswith("video/"):
                # Byte range support for video seeking
                start, end = 0, file_size - 1
                range_val = range_header.replace("bytes=", "").split("-")
                
                if range_val[0]:
                    start = int(range_val[0])
                if range_val[1]:
                    end = int(range_val[1])
                
                content_length = end - start + 1
                headers = {
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                    "Content-Type": media_type,
                }
                
                # Partial content response
                async def file_sender():
                    async with aiofiles.open(temp_path, 'rb') as f:
                        await f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(4096, remaining)
                            chunk = await f.read(chunk_size)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk
                
                # Clean up file after sending
                try:
                    os.unlink(temp_path)
                except:
                    pass
                
                return StreamingResponse(
                    file_sender(),
                    status_code=206,
                    headers=headers,
                    media_type=media_type
                )
            
        elif hasattr(msg, 'document') and msg.document:
            media_type = "application/octet-stream"
            filename = msg.document.file_name or "file.bin"
        elif hasattr(msg, 'photo') and msg.photo:
            media_type = "image/jpeg"
            filename = "photo.jpg"
        else:
            media_type = "application/octet-stream"
            filename = "file"
        
        # Regular file response (non-streaming)
        response = FileResponse(
            temp_path,
            media_type=media_type,
            filename=filename,
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=31536000"  # 1 year cache
            }
        )
        
        # Clean up file after response
        @response.on_close
        def cleanup():
            try:
                os.unlink(temp_path)
            except:
                pass
        
        return response
        
    except Exception as e:
        logger.error(f"File serve error: {e}")
        return JSONResponse(
            {"error": "Failed to serve file"},
            status_code=500
        )
    finally:
        # Pyrogram client stop karein
        try:
            await pyro_client.stop()
        except:
            pass

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram se webhook requests yahan aayengi"""
    # Verify secret token
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_token != config.SECRET_KEY:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    
    # Update data lein
    update_data = await request.json()
    
    # Background mein process karein
    asyncio.create_task(process_telegram_update(update_data))
    
    return JSONResponse({"status": "ok"})

# ====================
# PART 2: TELEGRAM BOT HANDLERS
# ====================
async def process_telegram_update(update_data: dict):
    """Telegram updates ko process karta hai"""
    try:
        # Bot application initialize karein
        telegram_app = Application.builder().token(config.BOT_TOKEN).request(
            HTTPXRequest(http_version="1.1")
        ).build()
        
        # Handlers register karein
        telegram_app.add_handler(CommandHandler("start", start_command))
        telegram_app.add_handler(CommandHandler("help", help_command))
        telegram_app.add_handler(MessageHandler(filters.ALL, handle_message))
        
        # Update process karein
        update = Update.de_json(update_data, telegram_app.bot)
        await telegram_app.initialize()
        await telegram_app.process_update(update)
        
    except Exception as e:
        logger.error(f"Update processing error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        "🤖 **File Hosting Bot**\n\n"
        "📤 **Mujhe koi bhi file bhejiye:**\n"
        "• Video\n• Photo\n• Document\n• Audio\n\n"
        "✅ **Main aapko permanent link dunga jo kabhi expire nahi hoga!**\n\n"
        "🌐 **Link kisi bhi browser mein khulega:** Chrome, Firefox, Safari, etc.\n\n"
        "🎬 **Videos ke liye:** Play, Pause, Forward, Backward sab kaam karega!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    help_text = (
        "🆘 **Bot Help Guide**\n\n"
        "1. 📤 **File bhejiye:** Koi bhi video, photo, document, audio\n"
        f"2. ⏳ **Wait karein:** Main file process karunga\n"
        f"3. 🔗 **Link payiye:** Permanent link mil jayega\n\n"
        f"🌐 **Link Example:**\n"
        f"`{config.FQDN}/file/abc123`\n\n"
        f"⚙️ **Features:**\n"
        f"• ✅ Permanent links (Lifetime)\n"
        f"• ✅ All browsers supported\n"
        f"• ✅ Video streaming with controls\n"
        f"• ✅ Fast downloads\n\n"
        f"📝 **Note:** Maximum file size 2GB (Telegram limit)"
    )
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sabhi messages aur files ko handle karta hai"""
    message = update.message
    
    if not message:
        return
    
    # Processing message bhejo
    status_msg = await message.reply_text("⏳ Processing your file...")
    
    try:
        # File type identify karein
        file_obj = None
        file_name = "file"
        file_size_mb = 0
        
        if message.video:
            file_obj = message.video
            file_name = message.video.file_name or "video.mp4"
            file_size_mb = file_obj.file_size / (1024 * 1024)
        elif message.document:
            file_obj = message.document
            file_name = message.document.file_name or "document.bin"
            file_size_mb = file_obj.file_size / (1024 * 1024)
        elif message.photo:
            file_obj = message.photo[-1]  # Highest resolution
            file_name = "photo.jpg"
            file_size_mb = file_obj.file_size / (1024 * 1024)
        elif message.audio:
            file_obj = message.audio
            file_name = message.audio.file_name or "audio.mp3"
            file_size_mb = file_obj.file_size / (1024 * 1024)
        else:
            await status_msg.edit_text("❌ Please send a file (video, photo, document, or audio)")
            return
        
        # File size check
        if file_size_mb > 2000:  # 2GB limit
            await status_msg.edit_text("❌ File size too large. Maximum 2GB allowed.")
            return
        
        # Step 1: File ko download karein
        await status_msg.edit_text("📥 Downloading file...")
        tg_file = await file_obj.get_file()
        
        # Temporary file banayein
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            temp_path = tmp_file.name
        
        await tg_file.download_to_drive(custom_path=temp_path)
        
        # Step 2: Channel mein upload karein
        await status_msg.edit_text("📤 Uploading to secure storage...")
        
        # Pyrogram client start karein
        await pyro_client.start()
        
        # File ko channel mein bhejein
        sent_message: Message = await pyro_client.send_document(
            chat_id=config.CHANNEL_ID,
            document=temp_path,
            caption=f"📄 {file_name}",
            disable_notification=True
        )
        
        # Step 3: Unique file ID generate karein
        import uuid
        import hashlib
        file_unique_id = str(uuid.uuid4())[:12]  # Short unique ID
        
        # File info store karein
        file_store[file_unique_id] = {
            "message_id": sent_message.id,
            "file_name": file_name,
            "file_size": file_size_mb,
            "upload_time": datetime.now().isoformat(),
            "file_unique_id": file_obj.file_unique_id
        }
        
        # Step 4: PERMANENT LINK GENERATE KAREIN (KOYEB KA LINK)
        permanent_link = f"{config.FQDN}/file/{file_unique_id}"
        
        # Step 5: User ko final response bhejein
        final_text = (
            f"✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"📦 **Size:** `{file_size_mb:.2f} MB`\n"
            f"🔗 **Permanent Link:**\n"
            f"`{permanent_link}`\n\n"
            f"🌐 **How to use:**\n"
            f"1. Copy the link above\n"
            f"2. Open in Chrome/Firefox/Safari\n"
            f"3. Video will play with full controls\n\n"
            f"⏰ **Validity:** Lifetime ♾️\n"
            f"📱 **Works on:** All browsers & devices"
        )
        
        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except:
            pass
        
        await status_msg.edit_text(final_text)
        
        # Ek extra button bhi bhejein link ke saath
        await message.reply_text(
            f"📤 **Quick Access:**\n[Open in Browser]({permanent_link})",
            disable_web_page_preview=False
        )
        
    except Exception as e:
        logger.error(f"Error handling file: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)}")
    finally:
        # Pyrogram client stop karein
        try:
            await pyro_client.stop()
        except:
            pass

# ====================
# APP STARTUP
# ====================
@app.on_event("startup")
async def startup_event():
    """App start hone par webhook set karein"""
    logger.info("Starting up File Hosting Bot...")
    
    # Webhook URL set karein
    if config.BOT_TOKEN and config.FQDN and config.SECRET_KEY:
        webhook_url = f"{config.FQDN}/webhook"
        try:
            bot = Bot(token=config.BOT_TOKEN)
            await bot.set_webhook(
                url=webhook_url,
                secret_token=config.SECRET_KEY,
                allowed_updates=["message", "callback_query"]
            )
            logger.info(f"Webhook set successfully: {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """App band hone par cleanup"""
    logger.info("Shutting down File Hosting Bot...")

# ====================
# MAIN ENTRY POINT
# ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot_server:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=False
      )
