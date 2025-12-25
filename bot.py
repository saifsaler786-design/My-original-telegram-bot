import base64
import asyncio
from aiohttp import web
from pyrogram import Client, filters, idle

API_ID = 22401925
API_HASH = "c7770339a011e6993e76c84e59d6641c"
BOT_TOKEN = "7732754577:AAEzM8GklmpGmJy2cHWWbPqVwOCb3VXSZNU"
PORT = 8080
CHUNK_SIZE = 1024 * 1024  # 1MB chunks - memory leak fix

app = Client("stream_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.video | filters.document | filters.audio | filters.photo)
async def handle_media(client, message):
    chat_id = message.chat.id
    msg_id = message.id

    if message.video:
        filename = message.video.file_name or "video.mp4"
    elif message.document:
        filename = message.document.file_name or "document"
    elif message.audio:
        filename = message.audio.file_name or "audio.mp3"
    elif message.photo:
        filename = "photo.jpg"
    else:
        filename = "file"

    raw = f"{chat_id}|{msg_id}|{filename}"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()

    stream_link = f"http://0.0.0.0:{PORT}/stream/{encoded}"
    download_link = f"http://0.0.0.0:{PORT}/download/{encoded}"

    await message.reply_text(
        f"**Stream Link:**\n`{stream_link}`\n\n**Download Link:**\n`{download_link}`"
    )


async def handle_stream(request):
    try:
        encoded = request.match_info.get("encoded")
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
        chat_id, msg_id, filename = decoded.split("|")
        chat_id = int(chat_id)
        msg_id = int(msg_id)

        msg = await app.get_messages(chat_id, msg_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="File not found")

        if msg.video:
            file_size = msg.video.file_size
            mime_type = msg.video.mime_type or "video/mp4"
        elif msg.document:
            file_size = msg.document.file_size
            mime_type = msg.document.mime_type or "application/octet-stream"
        elif msg.audio:
            file_size = msg.audio.file_size
            mime_type = msg.audio.mime_type or "audio/mpeg"
        elif msg.photo:
            file_size = msg.photo.file_size
            mime_type = "image/jpeg"
        else:
            return web.Response(status=400, text="Unsupported media")

        # Range header parsing for seek support
        range_header = request.headers.get("Range")
        start = 0
        end = file_size - 1

        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] and range_match[1].isdigit() else file_size - 1

        content_length = end - start + 1
        offset = start - (start % CHUNK_SIZE)
        skip_bytes = start % CHUNK_SIZE

        headers = {
            "Content-Type": mime_type,
            "Content-Length": str(content_length),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{filename}"',
        }

        if range_header:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response = web.StreamResponse(status=206, headers=headers)
        else:
            response = web.StreamResponse(status=200, headers=headers)

        await response.prepare(request)

        sent = 0
        async for chunk in app.stream_media(msg, offset=offset):
            if skip_bytes > 0:
                if len(chunk) <= skip_bytes:
                    skip_bytes -= len(chunk)
                    continue
                chunk = chunk[skip_bytes:]
                skip_bytes = 0

            remaining = content_length - sent
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if chunk:
                await response.write(chunk)
                sent += len(chunk)

            if sent >= content_length:
                break

        await response.write_eof()
        return response

    except Exception as e:
        print(f"Stream error: {e}")
        return web.Response(status=500, text=str(e))


async def handle_download(request):
    try:
        encoded = request.match_info.get("encoded")
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
        chat_id, msg_id, filename = decoded.split("|")
        chat_id = int(chat_id)
        msg_id = int(msg_id)

        msg = await app.get_messages(chat_id, msg_id)
        if not msg or not msg.media:
            return web.Response(status=404, text="File not found")

        if msg.video:
            file_size = msg.video.file_size
        elif msg.document:
            file_size = msg.document.file_size
        elif msg.audio:
            file_size = msg.audio.file_size
        elif msg.photo:
            file_size = msg.photo.file_size
        else:
            return web.Response(status=400, text="Unsupported media")

        # Range header support for resume
        range_header = request.headers.get("Range")
        start = 0
        end = file_size - 1

        if range_header:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] and range_match[1].isdigit() else file_size - 1

        content_length = end - start + 1
        offset = start - (start % CHUNK_SIZE)
        skip_bytes = start % CHUNK_SIZE

        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(content_length),
            "Accept-Ranges": "bytes",
        }

        if range_header:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response = web.StreamResponse(status=206, headers=headers)
        else:
            response = web.StreamResponse(status=200, headers=headers)

        await response.prepare(request)

        sent = 0
        async for chunk in app.stream_media(msg, offset=offset):
            if skip_bytes > 0:
                if len(chunk) <= skip_bytes:
                    skip_bytes -= len(chunk)
                    continue
                chunk = chunk[skip_bytes:]
                skip_bytes = 0

            remaining = content_length - sent
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if chunk:
                await response.write(chunk)
                sent += len(chunk)

            if sent >= content_length:
                break

        await response.write_eof()
        return response

    except Exception as e:
        print(f"Download error: {e}")
        return web.Response(status=500, text=str(e))


async def start_services():
    await app.start()
    print("Bot started!")

    web_app = web.Application()
    web_app.router.add_get("/stream/{encoded}", handle_stream)
    web_app.router.add_get("/download/{encoded}", handle_download)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Server running on port {PORT}")

    try:
        await idle()
    finally:
        await runner.cleanup()
        await app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_services())
    
