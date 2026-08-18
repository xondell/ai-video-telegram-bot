import math
from pathlib import Path
import httpx
from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select

from app.config import settings
from app.db.models import Job, Scene, JobStatus
from app.db.session import SessionLocal
from app.ai.schemas import AudioAnalysis
from app.services.storage import storage
from .subtitles import write_ass
from .ffmpeg import ffmpeg, normalize_audio, has_filter


_SIZE = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (720, 720),
    "4:5": (720, 900),
    "21:9": (1280, 548),
}


async def _download(url: str, path: Path):
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        path.write_bytes(response.content)


async def render_and_send(job_id: int, bot: Bot):
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if not job or job.output_storage_key:
            return
        result = await session.execute(
            select(Scene).where(Scene.job_id == job_id, Scene.status == "COMPLETED").order_by(Scene.scene_index)
        )
        scenes = list(result.scalars())
        if not scenes:
            raise RuntimeError("No completed video scenes")
        job.status = JobStatus.EDITING
        await session.commit()
        chat_id = job.telegram_chat_id
        duration = float(job.duration_seconds or 0)
        aspect_ratio = job.aspect_ratio or "16:9"
        transcript_json = job.transcript_json
        source_storage_key = job.source_audio_storage_key
        source_local = job.source_audio_path

    work = settings.temp_dir / f"render-{job_id}"
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio-source"
    if source_storage_key and storage.enabled:
        await storage.download_file(source_storage_key, audio)
    else:
        source = Path(source_local)
        if not source.exists():
            raise RuntimeError("Source audio is not available")
        audio.write_bytes(source.read_bytes())

    normalized_audio = work / "audio.m4a"
    await normalize_audio(audio, normalized_audio)

    clips: list[Path] = []
    for idx, scene in enumerate(scenes):
        clip = work / f"clip-{idx}.mp4"
        await _download(scene.output_url, clip)
        clips.append(clip)

    # Cycle through all generated scenes rather than loop one clip. The final trim follows narration length.
    repeats = max(1, math.ceil(duration / max(1, sum(scene.duration_seconds for scene in scenes))))
    concat_file = work / "clips.txt"
    lines = []
    for _ in range(repeats):
        for clip in clips:
            escaped = str(clip).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    subtitles = work / "subtitles.ass"
    if transcript_json:
        analysis = AudioAnalysis.model_validate_json(transcript_json)
        width, height = _SIZE.get(aspect_ratio, _SIZE["16:9"])
        write_ass(analysis, subtitles, width=width, height=height)

    width, height = _SIZE.get(aspect_ratio, _SIZE["16:9"])
    output = work / "final.mp4"
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    if subtitles.exists() and await has_filter("ass"):
        # Work directory uses safe generated paths without user-controlled characters.
        vf += f",ass={subtitles}"

    await ffmpeg(
        "-stream_loop", "-1", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(normalized_audio),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output.as_posix(),
    )

    # Telegram Bot API upload limits can be lower than our rendered file. Re-encode only when needed.
    max_bytes = 48 * 1024 * 1024
    if output.stat().st_size > max_bytes and duration > 0:
        target_total_bps = int(max_bytes * 8 / duration * 0.94)
        video_bps = max(220_000, target_total_bps - 128_000)
        compressed = work / "final-telegram.mp4"
        await ffmpeg(
            "-i", str(output),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-b:v", str(video_bps), "-maxrate", str(video_bps), "-bufsize", str(video_bps * 2),
            "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(compressed),
        )
        output = compressed

    storage_key = None
    if storage.enabled:
        storage_key = f"outputs/{job_id}/final.mp4"
        await storage.upload_file(output, storage_key, "video/mp4")

    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        job.output_path = str(output)
        job.output_storage_key = storage_key
        job.status = JobStatus.COMPLETED
        await session.commit()

    await bot.send_video(
        chat_id,
        FSInputFile(output),
        caption="✅ Video ready",
        supports_streaming=True,
    )
