import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client, idle
from pyrogram.types import Message
from pyrogram.enums import ParseMode
import asyncio

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables se credentials load karo ---
# Yehi variables aap baad mein Koyeb par bhi set karenge
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# Pyrogram client initialize karo (file channel mein upload karne ke liye)
pyro_app = Client("my_bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Bot ke command handlers ---

# /start command ka handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User /start command bhejta hai to is function ko call karo."""
    welcome_text = (
        "🤖 **Welcome to the File Vault Bot!**\n\n"
        "Mujhe koi bhi file bhejiye (video, document, image, etc.), aur main aapko permanent stream aur download links dungi.\n\n"
        "📤 **Sirf file upload karo, baaki kaam mera!**"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

# File receive karne ka handler
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jab koi user file bhejta hai, use channel mein upload karo aur permanent links banao."""
    user = update.effective_user
    message = update.message

    # Pehle user ko "Processing..." message bhejo
    status_msg = await message.reply_text("⏳ Processing your file...")

    try:
        # Agar file video hai to video ki properties le lo
        if message.video:
            file_obj = message.video
            file_name = message.video.file_name if message.video.file_name else "video.mp4"
            mime_type = "video/mp4"
            file_size_mb = file_obj.file_size / (1024 * 1024)  # Bytes se MB mein convert
        # Agar koi aur document hai (PDF, ZIP, etc.)
        elif message.document:
            file_obj = message.document
            file_name = message.document.file_name if message.document.file_name else "file"
            mime_type = message.document.mime_type
            file_size_mb = file_obj.file_size / (1024 * 1024)
        elif message.photo:
            # Photo ke liye - sabse high resolution wali photo lein
            file_obj = message.photo[-1]
            file_name = "photo.jpg"
            mime_type = "image/jpeg"
            file_size_mb = file_obj.file_size / (1024 * 1024)
        else:
            await status_msg.edit_text("❌ Unsupported file type. Please send a video, document, or image.")
            return

        # File size check (Optional: Telegram limit se chhota hi hoga)
        if file_size_mb > 2000:  # 2GB Telegram bot limit se zyada
            await status_msg.edit_text("❌ File size is too large. Maximum limit is 2GB.")
            return

        # Step 1: User se file download karo
        # Yeha bot token ka istemal hoga (python-telegram-bot ke through)
        tg_file = await file_obj.get_file()
        download_path = f"downloads/{file_name}"
        await tg_file.download_to_drive(custom_path=download_path)
        logger.info(f"File downloaded: {download_path}")

        # Step 2: Downloaded file ko Pyrogram ke through private channel mein upload karo
        # Yeha API ID/HASH ka istemal hoga (direct Telegram API access)
        await status_msg.edit_text("📤 Uploading to secure channel...")

        # Pyrogram client start karo (agar already running nahi hai)
        if not pyro_app.is_connected:
            await pyro_app.start()

        # File ko channel mein bhejo
        sent_message: Message = await pyro_app.send_document(
            chat_id=CHANNEL_ID,
            document=download_path,
            caption=f"📄 {file_name}",
            disable_notification=True
        )
        logger.info(f"File uploaded to channel, message_id: {sent_message.id}")

        # Step 3: Permanent links generate karo
        # Telegram ka feature: channel ke message se direct file ka link ban jata hai
        file_link = f"https://t.me/c/{str(CHANNEL_ID).replace('-100', '')}/{sent_message.id}"

        # Stream link (video ke liye) - Telegram player mein direct play
        stream_link = file_link  # Telegram automatically streams playable media

        # Step 4: User ko final message bhejo formatted tarike se
        final_text = (
            f"✅ **File Upload Complete!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"📦 **Size:** `{file_size_mb:.2f} MB`\n"
            f"🎬 **Stream:** [Click to Stream]({stream_link})\n"
            f"⬇️ **Download:** [Click to Download]({file_link})\n"
            f"⏰ **Validity:** Lifetime ♾️\n\n"
            f"_Links hamesha ke liye kaam karenge_"
        )

        await status_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)

        # Step 5: Local file delete karo (storage bachane ke liye)
        os.remove(download_path)

    except Exception as e:
        logger.error(f"Error handling file: {e}")
        await status_msg.edit_text("❌ An error occurred while processing your file. Please try again.")
    finally:
        # Pyrogram client stop karo
        if pyro_app.is_connected:
            await pyro_app.stop()

# /help command ka handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User /help command bhejta hai to is function ko call karo."""
    help_text = (
        "🆘 **Bot Help Guide**\n\n"
        "1. Send me any file (video, document, image, etc.)\n"
        "2. I will upload it to a private Telegram channel\n"
        "3. You will get permanent stream and download links\n\n"
        "📝 **Note:**\n"
        "• Files are stored in a private channel (not public)\n"
        "• Links will never expire\n"
        "• Maximum file size: 2GB\n\n"
        "Developed with ❤️ using Python"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# Main function - bot start karo
async def main() -> None:
    """Bot ko start karo aur handlers register karo."""
    # Python-telegram-bot application banao
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers register karo
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # File handlers register karo (sabhi files catch karo)
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL | filters.PHOTO, handle_file))

    # Downloads folder banao agar nahi hai to
    os.makedirs("downloads", exist_ok=True)

    logger.info("Bot starting...")
    # Bot ko run karo
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
