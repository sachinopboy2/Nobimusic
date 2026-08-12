"""Render a welcome card: banner template + joiner's pfp (circle on the left) +
their name written next to it.

Layout for the 735×420 banner:
- Profile photo: 280×280 circle, centered roughly at x=170, y=210
- Name: drawn to the right of the photo, vertically centered around y=210

If the user has no profile photo, we draw a colored initial avatar.

The result is returned as a BytesIO ready for sendPhoto.
"""

import asyncio
import colorsys
import hashlib
import io
import os

import aiohttp
from PIL import Image, ImageDraw, ImageFont

# Banner + fallback-avatar art for the welcome card. Third-party (i.ibb.co)
# placeholders; override with WELCOME_BANNER_URL / WELCOME_AVATAR_URL in .env.
BANNER_URL = os.getenv(
    "WELCOME_BANNER_URL", "https://i.ibb.co/NgL0V3hK/bdef780de3ae.jpg"
).strip()
BANNER_CACHE = "/tmp/warborn_banner.jpg"
DEFAULT_AVATAR_URL = os.getenv(
    "WELCOME_AVATAR_URL", "https://i.ibb.co/NdrW3Th2/5fd3624c12fa.jpg"
).strip()
DEFAULT_AVATAR_CACHE = "/tmp/warborn_default_avatar.jpg"

# Layout for the banner (735x420).
PFP_CENTER = (170, 200)
PFP_RADIUS = 140
BANNER_W = 735
BANNER_H = 420
# Name is drawn centered along the banner's lower portion.
NAME_X_CENTER = BANNER_W // 2
NAME_Y_CENTER = 370
NAME_MAX_WIDTH = BANNER_W - 60

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NAME_FONT_SIZE = 44
NAME_FONT_MIN_SIZE = 22


async def _fetch_remote(url: str, cache_path: str) -> Image.Image:
    if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                data = await r.read()
        with open(cache_path, "wb") as f:
            f.write(data)
    return Image.open(cache_path).convert("RGBA")


async def _fetch_banner() -> Image.Image:
    return await _fetch_remote(BANNER_URL, BANNER_CACHE)


async def _fetch_default_avatar() -> Image.Image:
    return await _fetch_remote(DEFAULT_AVATAR_URL, DEFAULT_AVATAR_CACHE)


def _initial_avatar(name: str, user_id: int, size: int) -> Image.Image:
    """Fallback used only if the remote default avatar fails to download."""
    initial = (name.strip() or "?")[0].upper()
    hue = (hashlib.md5(str(user_id).encode()).digest()[0]) / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.6, 0.85)
    bg = (int(r * 255), int(g * 255), int(b * 255), 255)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=bg)

    try:
        font = ImageFont.truetype(FONT_PATH, int(size * 0.6))
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        initial,
        fill=(255, 255, 255, 255),
        font=font,
    )
    return img


def _round_avatar(src: Image.Image, size: int) -> Image.Image:
    """Crop-to-square then circular-mask the source image."""
    src = src.convert("RGBA")
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    src = src.crop((left, top, left + side, top + side)).resize(
        (size, size), Image.LANCZOS
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    """Pick the largest font size that keeps the text within max_width."""
    size = NAME_FONT_SIZE
    while size >= NAME_FONT_MIN_SIZE:
        try:
            font = ImageFont.truetype(FONT_PATH, size)
        except OSError:
            return ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(FONT_PATH, NAME_FONT_MIN_SIZE)


def _compose(
    banner: Image.Image,
    avatar: Image.Image,
    display_name: str,
) -> bytes:
    canvas = banner.copy()
    diameter = PFP_RADIUS * 2

    # White ring around the pfp so it stands out on any banner.
    ring = Image.new("RGBA", (diameter + 16, diameter + 16), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (0, 0, diameter + 16, diameter + 16), fill=(255, 255, 255, 230)
    )
    canvas.paste(
        ring,
        (PFP_CENTER[0] - PFP_RADIUS - 8, PFP_CENTER[1] - PFP_RADIUS - 8),
        ring,
    )

    avatar_round = _round_avatar(avatar, diameter)
    canvas.paste(
        avatar_round, (PFP_CENTER[0] - PFP_RADIUS, PFP_CENTER[1] - PFP_RADIUS), avatar_round
    )

    draw = ImageDraw.Draw(canvas)
    font = _fit_font(draw, display_name, NAME_MAX_WIDTH)
    bbox = draw.textbbox((0, 0), display_name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = NAME_X_CENTER - text_w // 2 - bbox[0]
    text_y = NAME_Y_CENTER - text_h // 2 - bbox[1]

    # Soft shadow so the name reads on light or dark banners.
    shadow_off = 2
    draw.text(
        (text_x + shadow_off, text_y + shadow_off),
        display_name,
        fill=(0, 0, 0, 180),
        font=font,
    )
    draw.text((text_x, text_y), display_name, fill=(255, 255, 255, 255), font=font)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=90)
    out.seek(0)
    return out.getvalue()


async def render_welcome_card(
    display_name: str,
    user_id: int,
    avatar_path: str | None,
) -> io.BytesIO:
    """Return a BytesIO of the rendered card. `avatar_path` may be None."""
    banner = await _fetch_banner()
    if avatar_path and os.path.exists(avatar_path):
        try:
            avatar = Image.open(avatar_path)
        except Exception:
            avatar = None
    else:
        avatar = None

    if avatar is None:
        try:
            avatar = await _fetch_default_avatar()
        except Exception:
            avatar = _initial_avatar(display_name, user_id, PFP_RADIUS * 2)

    data = await asyncio.to_thread(_compose, banner, avatar, display_name)
    bio = io.BytesIO(data)
    bio.name = "welcome.jpg"
    return bio
