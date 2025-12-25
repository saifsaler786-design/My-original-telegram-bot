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

        file_size = msg.media.document.file_size if msg.media.document else msg.media.photo.file_size
        mime_type = msg.media.document.mime_type if msg.media.document else "image/jpeg"

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
        
