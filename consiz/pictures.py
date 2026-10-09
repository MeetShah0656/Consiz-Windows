"""Pictures in Explain mode (T-11): a picture file selected in Explorer, or a screenshot on the clipboard.

The picture is shrunk on this PC and sent to the AI as a small JPEG, but ONLY after the person says yes every time: unlike
text, a picture cannot have its passwords and keys removed first. Platform-free (no UI here).
"""
from __future__ import annotations

import base64
import io
import itertools
import os

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
UNREADABLE_EXTS = frozenset({".heic", ".heif", ".svg", ".raw", ".cr2", ".nef", ".arw", ".dng"})   # cannot be opened here
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_B64_CHARS = 1_500_000                    # the server refuses more than 1.8 million characters per picture
_STEPS = ((1400, 72), (1100, 66), (800, 60), (560, 55))        # (longest side in pixels, JPEG quality): smaller until it fits


class PictureError(ValueError):
    """A picture problem with a message a person can act on."""


def is_picture_file(path: str) -> bool:
    return os.path.splitext(str(path))[1].lower() in IMAGE_EXTS


def is_unreadable_picture(path: str) -> bool:
    return os.path.splitext(str(path))[1].lower() in UNREADABLE_EXTS


def to_jpeg_b64(source) -> str:
    """A picture file path (or an already opened PIL image) as base64 JPEG, at most 1400 px on its longest side."""
    from PIL import Image, ImageOps
    try:
        if isinstance(source, (str, os.PathLike)):
            if os.path.getsize(source) > MAX_FILE_BYTES:
                raise PictureError("That picture file is too big (over 40 MB).")
            img = Image.open(source)
            img.load()
        else:
            img = source
        img = ImageOps.exif_transpose(img)                     # phone photos: stand upright
        if img.mode in ("RGBA", "LA", "P"):                    # transparent parts become white, not black
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.split()[-1])
            img = flat
        else:
            img = img.convert("RGB")
    except PictureError:
        raise
    except Exception as e:
        raise PictureError(f"Could not open this picture ({type(e).__name__}).") from e
    for side, quality in _STEPS:
        small = img.copy()
        small.thumbnail((side, side), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        if len(b64) <= MAX_B64_CHARS:
            return b64
    raise PictureError("This picture is too detailed to send.")


# The last picture explained, so follow-up questions in the same chat can still be about it.
_memory: dict = {"tag": "", "images": []}
_numbers = itertools.count(1)


def remember(label: str, images: list[str]) -> str:
    """Keep the picture for follow-ups; returns the line that stands for it in the chat's context."""
    tag = f"(picture {next(_numbers)}: {label}. It was described in the first answer.)"
    _memory["tag"], _memory["images"] = tag, list(images)
    return tag


def remembered(context: str) -> list[str]:
    """The picture(s) behind this chat, or [] when the chat is about something else."""
    return list(_memory["images"]) if context and context == _memory["tag"] else []
