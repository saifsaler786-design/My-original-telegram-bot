from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import asyncio

API_ID = "29579893"
API_HASH = "a534ef5a149a4e8a5e6c7366b8f718a3"
BOT_TOKEN = "8145896177:AAHb1ki8gsUBJzuzK0dAexdJ3WDHC3sLvWc"
CHANNEL_ID = -1002653856134

app = Client("stream_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
web_app = web.Application()

# MIME types - MKV served as MP4 for browser compatibility
MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/mp4",
    ".mov": "video/mp4",
    ".m4v": "video/mp4",
    ".flv": "video/mp4",
    ".wmv": "video/mp4",
}

def get_mime_type(file_name):
    if file_name:
        ext = "." + file_name.lower().split(".")[-1] if "." in file_name else ""
        return MIME_TYPES.get(ext, "video/mp4")
    return "video/mp4"

async def handle_stream(request):
    message_id = int(request.match_info['id'])
    
    try:
        message = await app.get_messages(CHANNEL_ID, message_id)
        
        if not message.video and not message.document:
            return web.Response(text="No video found", status=404)
        
        media = message.video or message.document
        file_size = media.file_size
        file_name = getattr(media, 'file_name', None) or f"video_{message_id}.mp4"
        mime_type = get_mime_type(file_name)
        
        range_header = request.headers.get('Range')
        
        if range_header:
            range_str = range_header.replace('bytes=', '')
            start, end = range_str.split('-')
            start = int(start)
            end = int(end) if end else file_size - 1
        else:
            start = 0
            end = file_size - 1
        
        content_length = end - start + 1
        
        headers = {
            'Content-Type': mime_type,
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'inline; filename="{file_name}"',
            'Cache-Control': 'no-cache',
        }
        
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
            status = 206
        else:
            status = 200
        
        response = web.StreamResponse(status=status, headers=headers)
        await response.prepare(request)
        
        current_pos = 0
        bytes_sent = 0
        bytes_to_send = content_length
        
        async for chunk in app.stream_media(message):
            chunk_size = len(chunk)
            chunk_end = current_pos + chunk_size
            
            if chunk_end <= start:
                current_pos = chunk_end
                continue
            
            if current_pos >= end + 1:
                break
            
            if current_pos < start:
                skip = start - current_pos
                chunk = chunk[skip:]
                current_pos = start
            
            if bytes_sent + len(chunk) > bytes_to_send:
                chunk = chunk[:bytes_to_send - bytes_sent]
            
            if chunk:
                await response.write(chunk)
                bytes_sent += len(chunk)
            
            current_pos = chunk_end
            
            if bytes_sent >= bytes_to_send:
                break
        
        await response.write_eof()
        return response
        
    except Exception as e:
        print(f"Stream error: {e}")
        return web.Response(text=f"Error: {str(e)}", status=500)

async def handle_download(request):
    message_id = int(request.match_info['id'])
    
    try:
        message = await app.get_messages(CHANNEL_ID, message_id)
        
        if not message.video and not message.document:
            return web.Response(text="No video found", status=404)
        
        media = message.video or message.document
        file_size = media.file_size
        file_name = getattr(media, 'file_name', None) or f"video_{message_id}.mp4"
        
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Length': str(file_size),
            'Content-Disposition': f'attachment; filename="{file_name}"',
        }
        
        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)
        
        async for chunk in app.stream_media(message):
            await response.write(chunk)
        
        await response.write_eof()
        return response
        
    except Exception as e:
        print(f"Download error: {e}")
        return web.Response(text=f"Error: {str(e)}", status=500)

web_app.router.add_get('/stream/{id}', handle_stream)
web_app.router.add_get('/download/{id}', handle_download)

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "🎬 **Video Stream Bot**\n\n"
        "Send me a video and I'll give you:\n"
        "• 📺 Stream link (plays in browser)\n"
        "• 📥 Download link (saves to device)\n\n"
        "✅ Supports: MP4, MKV, WebM, AVI, MOV\n"
        "✅ Seeking enabled for all videos"
    )

@app.on_message(filters.video | filters.document)
async def handle_video(client: Client, message: Message):
    try:
        fwd = await message.forward(CHANNEL_ID)
        message_id = fwd.id
        
        media = message.video or message.document
        file_name = getattr(media, 'file_name', None) or "video"
        
        base_url = "https://pyro-test-nikhil0987.koyeb.app"
        stream_link = f"{base_url}/stream/{message_id}"
        download_link = f"{base_url}/download/{message_id}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 Stream", url=stream_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await message.reply_text(
            f"✅ **{file_name}**\n\n"
            f"📺 Stream: `{stream_link}`\n"
            f"📥 Download: `{download_link}`",
            reply_markup=keyboard
        )
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

async def start_services():
    await app.start()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    print("Bot and Web Server started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_services())
        
