"""ffprobe metadata + compress-to-fit for Telegram upload limits."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("WarbornMusic.media_processor")

MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_PHOTO_BYTES = 10 * 1024 * 1024


@dataclass
class VideoInfo:
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    bitrate: Optional[int] = None


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout, stderr


async def probe_video(filepath: str) -> VideoInfo:
    rc, stdout, _ = await _run(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", filepath,
    )
    if rc != 0:
        return VideoInfo()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return VideoInfo()

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    fmt = data.get("format", {})
    duration = None
    for src in (video_stream, fmt):
        if src and src.get("duration"):
            try:
                duration = float(src["duration"])
                break
            except (TypeError, ValueError):
                pass

    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    bitrate = None
    if fmt.get("bit_rate"):
        try:
            bitrate = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            pass

    return VideoInfo(width=width, height=height, duration=duration, bitrate=bitrate)


async def compress_to_fit(
    filepath: str,
    target_bytes: int = MAX_VIDEO_BYTES,
    min_video_kbps: int = 200,
    audio_kbps: int = 96,
) -> Optional[str]:
    info = await probe_video(filepath)
    if not info.duration or info.duration <= 0:
        return None

    out_path = os.path.splitext(filepath)[0] + "_compressed.mp4"
    budget_bits = target_bytes * 8 * 0.92
    total_kbps = budget_bits / info.duration / 1000
    video_kbps = max(min_video_kbps, int(total_kbps - audio_kbps))

    for attempt, factor in enumerate((1.0, 0.75, 0.5)):
        vkbps = max(min_video_kbps, int(video_kbps * factor))
        rc, _, stderr = await _run(
            "ffmpeg", "-y", "-i", filepath,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{vkbps}k", "-maxrate", f"{int(vkbps * 1.3)}k",
            "-bufsize", f"{vkbps * 2}k",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-movflags", "+faststart",
            out_path,
        )
        if rc != 0:
            logger.warning("compress_to_fit: ffmpeg failed (attempt %d)", attempt)
            continue
        if os.path.exists(out_path) and os.path.getsize(out_path) <= target_bytes:
            return out_path

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass
    return None


async def prepare_for_upload(filepath: str) -> Optional[str]:
    ext = os.path.splitext(filepath)[1].lower()
    is_video = ext in (".mp4", ".mov", ".webm", ".mkv")
    limit = MAX_VIDEO_BYTES if is_video else MAX_PHOTO_BYTES
    size = os.path.getsize(filepath)
    if size <= limit:
        return filepath
    if not is_video:
        return None
    return await compress_to_fit(filepath, target_bytes=limit)
