"""Bounded handling of uploaded files: never read an unbounded upload into memory, and clean up partial files."""
import os

from fastapi import HTTPException, UploadFile, status

CHUNK_BYTES = 1024 * 1024


def _too_large(max_bytes: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                         detail=f"The file is too large. The limit is {max_bytes // (1024 * 1024)} MB.")


async def read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """The whole upload, or HTTP 413 as soon as it exceeds `max_bytes` (the rest is never read)."""
    data = bytearray()
    while chunk := await file.read(CHUNK_BYTES):
        data += chunk
        if len(data) > max_bytes:
            raise _too_large(max_bytes)
    return bytes(data)


async def save_upload_limited(file: UploadFile, path: str, max_bytes: int) -> int:
    """Stream the upload to `path`. Over the limit → the partial file is removed and HTTP 413 is raised."""
    written = 0
    try:
        with open(path, "wb") as target:
            while chunk := await file.read(CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise _too_large(max_bytes)
                target.write(chunk)
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    return written
