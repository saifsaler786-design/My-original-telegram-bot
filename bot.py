import os
import asyncio
import logging
import json
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
PORT = int(os.environ.get("PORT", "8080"))
APP_URL = os.environ.get("APP_URL", "http://localhost:8080")

ADMIN_IDS = [5332466812]
CHUNK_SIZE = 1024 * 1024  # 1MB (instant start)

STATS_FILE = "stats.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "stream_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ================= STATS =================
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"users": 0, "files": 0}
    with open(STATS_FILE, "r") as f:
        return json.load(f)

def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f)

stats = load_stats()

# ================= UTILS =================
def get_file_info(msg: Message):
    if msg.document:
        return msg.document.file_name, msg.document.file_size, msg.document.mime_type
    if msg.video:
        return msg.video.file_name or "video.mp4", msg.video.file_size, msg.video.mime_type
    if msg.audio:
        return msg.audio.file_name or "audio.mp3", msg.audio.file_size, msg.audio.mime_type
    return "file", 0, "application/octet-stream"

# ================= HTML PLAYER =================
async def stream_page(request):
    mid = request.match_info["message_id"]
    return web.Response(
        content_type="text/html",
        text=f"""
<!DOCTYPE html>
<html>
<head>
<title>Streaming</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ margin:0; background:#000; color:#fff; text-align:center }}
video {{ width:100%; height:auto }}
.controls button {{ padding:10px; margin:5px; font-size:16px }}
</style>
</head>
<body>
<video id="v" controls autoplay playsinline>
  <source src="/stream-data/{mid}" type="video/mp4">
</video>
<div class="controls">
<button onclick="v.currentTime-=10">⏪ 10s</button>
<button onclick="v.playbackRate=1">1x</button>
<button onclick="v.playbackRate=1.5">1.5x</button>
<button onclick="v.playbackRate=2">2x</button>
<button onclick="v.currentTime+=10">10s ⏩</button>
</div>
<p>Powered by SAIFSALER</p>
</body>
</html>
"""
    )

# ================= STREAM DATA (INSTANT) =================
async def stream_data(request):
    mid = int(request.match_info["message_id"])
    msg = await app.get_messages(CHANNEL_ID, mid)
    if not msg or not msg.media:
        return web.Response(text="Not Found", status=404)

    name, size, mime = get_file_info(msg)
    range_h = request.headers.get("Range")

    start = 0
    end = size - 1
    if range_h:
        start = int(range_h.split("=")[1].split("-")[0])

    headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{name}"'
    }

    if range_h:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(size - start)

    resp = web.StreamResponse(status=206 if range_h else 200, headers=headers)
    await resp.prepare(request)

    async for chunk in app.stream_media(msg, offset=start // CHUNK_SIZE):
        await resp.write(chunk)

    await resp.write_eof()
    return resp

# ================= DOWNLOAD (INSTANT) =================
async def download_file(request):
    mid = int(request.match_info["message_id"])
    msg = await app.get_messages(CHANNEL_ID, mid)
    if not msg or not msg.media:
        return web.Response(text="Not Found", status=404)

    name, size, mime = get_file_info(msg)

    headers = {
        "Content-Type": mime,
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Length": str(size)
    }

    resp = web.StreamResponse(headers=headers)
    await resp.prepare(request)

    async for chunk in app.stream_media(msg):
        await resp.write(chunk)

    await resp.write_eof()
    return resp

# ================= HEALTH =================
async def health(request):
    return web.Response(text="OK")

# ================= BOT =================
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(_, m):
    uid = m.from_user.id
    if uid not in ADMIN_IDS:
        stats["users"] += 1
        save_stats(stats)

    await m.reply_text(
        "👋 Salam!\n\n"
        "📤 File bhejo\n"
        "🎬 Instant Stream\n"
        "⬇️ Instant Download\n\n"
        "⚡ Powered by SAIFSALER"
    )

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_cmd(_, m):
    await m.reply_text(
        f"👤 Users: {stats['users']}\n"
        f"📁 Files: {stats['files']}"
    )

@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def file_handler(_, m):
    ask = await m.reply_text("✏️ New filename bhejo ya /skip likho")
    reply = await app.listen(m.chat.id)

    fname = None
    if reply.text != "/skip":
        fname = reply.text

    sent = await m.copy(CHANNEL_ID, file_name=fname)
    stats["files"] += 1
    save_stats(stats)

    await ask.delete()
    await reply.delete()
    await m.delete()

    await m.reply_text(
        f"✅ Done!\n\n"
        f"🎬 Stream:\n{APP_URL}/stream/{sent.id}\n\n"
        f"⬇️ Download:\n{APP_URL}/download/{sent.id}",
        disable_web_page_preview=True
    )

# ================= RUN =================
async def main():
    await app.start()

    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/stream/{message_id}", stream_page)
    web_app.router.add_get("/stream-data/{message_id}", stream_data)
    web_app.router.add_get("/download/{message_id}", download_file)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    from pyrogram import idle
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
    
