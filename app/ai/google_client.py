import asyncio
from pathlib import Path
from google import genai
from google.genai import types
from app.config import settings
from .schemas import AudioAnalysis, VideoScript

class GeminiService:
    def _client(self):
        if not settings.google_ai_api_key:
            raise RuntimeError("GOOGLE_AI_API_KEY is missing")
        return genai.Client(api_key=settings.google_ai_api_key)

    async def _upload(self, path: Path):
        client = self._client()
        return await asyncio.to_thread(client.files.upload, file=str(path))

    async def analyze_audio(self, path: Path, duration: float) -> AudioAnalysis:
        client = self._client()
        uploaded = await self._upload(path)
        prompt = (
            f"Transcribe and understand this audio. ffprobe duration={duration:.3f}s. "
            "Return accurate timestamps, raw transcript and cleaned transcript. "
            "Do not invent words that are not audible."
        )
        models = [
            settings.gemini_primary_model,
            settings.gemini_fallback_model,
            settings.gemini_secondary_fallback_model,
        ]
        last = None
        for model in models:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=[uploaded, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AudioAnalysis,
                    ),
                )
                return AudioAnalysis.model_validate_json(response.text)
            except Exception as e:
                last = e
        raise RuntimeError(f"Gemini audio analysis failed: {last}")

    async def make_script(self, analysis: AudioAnalysis, style: str, ratio: str, intensity: str) -> VideoScript:
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
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_primary_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VideoScript,
            ),
        )
        return VideoScript.model_validate_json(response.text)
