import asyncio
from pathlib import Path
import imageio_ffmpeg


def exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


async def ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        exe(), "-y", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(err.decode(errors="ignore")[-6000:])


async def normalize_audio(src: Path, dst: Path):
    await ffmpeg(
        "-i", str(src), "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-c:a", "aac", "-b:a", "160k", str(dst),
    )


async def has_filter(name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        exe(), "-hide_banner", "-filters",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    for line in out.decode(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False
