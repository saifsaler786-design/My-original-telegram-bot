async def media_streamer(request, message_id):
    try:
        # Message fetch karein
        msg = await app.get_messages(CHANNEL_ID, message_id)
        file = getattr(msg, msg.media.value)
        filename = file.file_name or "Unknown_File"
        file_size = file.file_size
        mime_type = file.mime_type or "application/octet-stream"
    except Exception as e:
        return web.Response(status=404, text=f"File Not Found: {e}")

    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Length": str(file_size)
    }

    # Range request handle karna (Video Seeking ke liye)
    range_header = request.headers.get("Range")
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        headers["Content-Length"] = str(until_bytes - from_bytes + 1)
        status_code = 206
    else:
        from_bytes = 0
        until_bytes = file_size - 1
        status_code = 200

    # Generator function (Modified for Stability)
    async def file_generator():
        # Chunk size 1MB rakhenge stability ke liye
        chunk_size = 1024 * 1024 
        offset = from_bytes
        
        # Download chunks loop
        try:
            async for chunk in app.download_media(msg, offset=offset, limit=until_bytes - from_bytes + 1, in_memory=True, chunk_size=chunk_size):
                yield chunk
        except Exception as e:
            print(f"Stream Error: {e}")

    return web.Response(
        status=status_code,
        headers=headers,
        body=file_generator()
    )
