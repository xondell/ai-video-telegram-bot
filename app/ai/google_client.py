import asyncio
import logging
from pathlib import Path

import imageio_ffmpeg
from google import genai

from app.config import settings
from .schemas import AudioAnalysis, VideoScript

logger = logging.getLogger(__name__)


class GeminiService:
    def _client(self):
        if not settings.google_ai_api_key:
            raise RuntimeError("GOOGLE_AI_API_KEY is missing")
        return genai.Client(api_key=settings.google_ai_api_key)

    async def _normalize_audio(self, path: Path) -> Path:
        """Convert Telegram audio/voice to a Gemini-safe WAV."""
        output = path.with_name(f"{path.stem}.gemini.wav")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        proc = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await proc.communicate()

        if proc.returncode != 0 or not output.exists():
            detail = stderr.decode(errors="ignore")[-1000:]
            raise RuntimeError(f"Audio normalization failed: {detail}")

        return output

    async def _upload(self, path: Path):
        client = self._client()
        return await asyncio.to_thread(
            client.files.upload,
            file=str(path),
        )

    async def analyze_audio(
        self,
        path: Path,
        duration: float,
    ) -> AudioAnalysis:
        client = self._client()
        normalized = await self._normalize_audio(path)

        try:
            uploaded = await self._upload(normalized)

            prompt = (
                f"Transcribe and understand this audio. "
                f"ffprobe duration={duration:.3f}s. "
                "Return accurate timestamps, raw transcript and cleaned transcript. "
                "Do not invent words that are not audible."
            )

            models = [
                settings.gemini_primary_model,
                settings.gemini_fallback_model,
                settings.gemini_secondary_fallback_model,
            ]

            failures = []

            for model in models:
                try:
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model,
                        contents=[prompt, uploaded],
                        config={
                            "response_mime_type": "application/json",
                            "response_json_schema":
                                AudioAnalysis.model_json_schema(),
                        },
                    )

                    if not response.text:
                        raise RuntimeError(
                            "Gemini returned an empty response"
                        )

                    return AudioAnalysis.model_validate_json(
                        response.text
                    )

                except Exception as error:
                    failures.append(
                        f"{model}: "
                        f"{type(error).__name__}: {error}"
                    )

                    logger.warning(
                        "Gemini audio model %s failed",
                        model,
                        exc_info=True,
                    )

            raise RuntimeError(
                "Gemini audio analysis failed | "
                + " | ".join(failures)
            )

        finally:
            normalized.unlink(missing_ok=True)

    async def make_script(
        self,
        analysis: AudioAnalysis,
        style: str,
        ratio: str,
        intensity: str,
    ) -> VideoScript:
        client = self._client()

        prompt = f"""
Create a complete time-aligned visual script for the narration below.
Preserve meaning and timing.

Style: {style}
Aspect ratio: {ratio}
Editing intensity: {intensity}

Assign each scene importance from 0 to 1.
Write video model prompts in English.

Transcript:
{analysis.transcript_clean}
"""

        failures = []

        models = [
            settings.gemini_primary_model,
            settings.gemini_fallback_model,
            settings.gemini_secondary_fallback_model,
        ]

        for model in models:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema":
                            VideoScript.model_json_schema(),
                    },
                )

                if not response.text:
                    raise RuntimeError(
                        "Gemini returned an empty response"
                    )

                return VideoScript.model_validate_json(
                    response.text
                )

            except Exception as error:
                failures.append(
                    f"{model}: "
                    f"{type(error).__name__}: {error}"
                )

                logger.warning(
                    "Gemini script model %s failed",
                    model,
                    exc_info=True,
                )

        raise RuntimeError(
            "Gemini script generation failed | "
            + " | ".join(failures)
        )
