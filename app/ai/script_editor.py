import asyncio
import logging

from google import genai

from app.ai.schemas import AudioAnalysis, VideoScript
from app.config import settings

logger = logging.getLogger(__name__)


class StoryboardEditorService:
    def _client(self):
        if not settings.google_ai_api_key:
            raise RuntimeError("GOOGLE_AI_API_KEY is missing")
        return genai.Client(api_key=settings.google_ai_api_key)

    def _models(self) -> list[str]:
        return [
            settings.gemini_primary_model,
            settings.gemini_fallback_model,
            settings.gemini_secondary_fallback_model,
        ]

    async def _structured(
        self,
        prompt: str,
        error_prefix: str,
    ) -> VideoScript:
        client = self._client()
        failures: list[str] = []

        for model in self._models():
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": VideoScript.model_json_schema(),
                    },
                )

                if not response.text:
                    raise RuntimeError("Gemini returned an empty storyboard")

                return VideoScript.model_validate_json(response.text)

            except Exception as error:
                failures.append(f"{model}: {type(error).__name__}: {error}")
                logger.warning(
                    "%s on %s",
                    error_prefix,
                    model,
                    exc_info=True,
                )

        raise RuntimeError(f"{error_prefix} | " + " | ".join(failures))

    async def from_user_text(
        self,
        analysis: AudioAnalysis,
        user_text: str,
        *,
        style: str = "",
        ratio: str = "",
        intensity: str = "",
    ) -> VideoScript:
        user_text = user_text.strip()
        if not user_text:
            raise ValueError("User storyboard is empty")

        prompt = f"""
You are a technical storyboard formatter.

IMPORTANT:
The USER wrote the visual scenario themselves.
Their scenario is AUTHORITATIVE.
Do NOT replace it with a different creative concept.

SOURCE AUDIO ANALYSIS JSON:
{analysis.model_dump_json()}

USER'S OWN STORYBOARD:
{user_text}

VIDEO SETTINGS:
- style: {style}
- aspect ratio: {ratio}
- editing intensity: {intensity}
- exact source audio duration: {analysis.duration_seconds:.3f} seconds

Build a VideoScript matching the requested JSON schema.

STRICT RULES:
1. Preserve the user's visual ideas, scene order, subjects, locations,
   actions, mood and requested details.
2. Do not invent a different story.
3. You may only add minimal technical details needed by a video model:
   camera movement, shot type, transition, lighting wording and prompt formatting.
4. If the user explicitly numbered scenes, preserve that order.
5. If the user did not provide scene boundaries, split the user's text
   into sensible scenes that cover the complete source-audio duration.
6. Scene timing must start at 0 and cover the full audio duration.
   Avoid gaps and overlaps.
7. narration must represent the ACTUAL source audio/transcript for that
   time range. Never replace the spoken audio with visual-description text.
8. video_prompt must faithfully translate the user's visual intention
   into a strong ENGLISH text-to-video prompt.
9. Do not add logos, text overlays, subtitles or extra characters unless requested.
10. importance must be between 0 and 1.
11. Return only data matching the JSON schema.
"""

        return await self._structured(
            prompt,
            "User storyboard structuring failed",
        )

    async def revise(
        self,
        current: VideoScript,
        instructions: str,
        *,
        style: str = "",
        ratio: str = "",
    ) -> VideoScript:
        instructions = instructions.strip()
        if not instructions:
            raise ValueError("Edit instructions are empty")

        prompt = f"""
You are editing a storyboard for an AI-generated video.

USER EDIT REQUEST:
{instructions}

CURRENT STORYBOARD JSON:
{current.model_dump_json()}

Context:
- visual style: {style}
- aspect ratio: {ratio}

Rules:
1. Apply the user's requested visual changes faithfully.
2. Preserve every scene id, start time, end time and narration exactly.
3. Do not add or remove scenes.
4. You may change title, visual_direction, importance, visual_type,
   video_prompt, negative_prompt, camera and transition.
5. video_prompt must remain suitable for a text-to-video model and be in English.
6. Return only data matching the requested JSON schema.
"""

        candidate = await self._structured(prompt, "Storyboard edit failed")
        return self._preserve_timeline(current, candidate)

    async def regenerate(
        self,
        current: VideoScript,
        *,
        style: str = "",
        ratio: str = "",
    ) -> VideoScript:
        return await self.revise(
            current,
            "Create a clearly different alternative visual concept for every scene. "
            "Keep the same narration and timing, but substantially change the imagery, "
            "camera ideas and transitions while respecting the selected style.",
            style=style,
            ratio=ratio,
        )

    @staticmethod
    def _preserve_timeline(current: VideoScript, candidate: VideoScript) -> VideoScript:
        by_id = {scene.id: scene for scene in candidate.scenes}
        scenes = []
        for old in current.scenes:
            new = by_id.get(old.id, old)
            scenes.append(new.model_copy(update={
                "id": old.id,
                "start": old.start,
                "end": old.end,
                "narration": old.narration,
            }))
        return candidate.model_copy(update={"scenes": scenes})
