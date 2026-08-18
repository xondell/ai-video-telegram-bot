import asyncio
import re
from pathlib import Path
import imageio_ffmpeg
from app.config import settings


class InvalidAudio(ValueError):
    """Raised when an uploaded file is not a supported audio input."""


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def probe_audio(path: Path, telegram_duration: float | None = None) -> float:
    if telegram_duration and 0 < telegram_duration <= settings.max_audio_seconds:
        return float(telegram_duration)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode(errors="ignore")
    match = _DURATION.search(text)
    if not match:
        raise InvalidAudio("Could not determine audio duration")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0 or duration > settings.max_audio_seconds:
        raise InvalidAudio(
            f"Duration {duration:.1f}s exceeds the {settings.max_audio_seconds}s limit"
        )
    return duration
