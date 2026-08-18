import asyncio
import logging

from google import genai

from app.ai.schemas import VideoScript
from app.config import settings

logger = logging.getLogger(__name__)


class StoryboardEditorService:
    """Revise an existing storyboard without changing source narration/timing."""

    def _client(self):
        if not settings.google_ai_api_key:
            raise RuntimeError("GOOGLE_AI_API_KEY is missing")
        return genai.Client(api_key=settings.google_ai_api_key)

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

        models = [
            settings.gemini_primary_model,
            settings.gemini_fallback_model,
            settings.gemini_secondary_fallback_model,
        ]
        failures: list[str] = []
        client = self._client()

        for model in models:
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
                candidate = VideoScript.model_validate_json(response.text)
                return self._preserve_timeline(current, candidate)
            except Exception as error:
                failures.append(f"{model}: {type(error).__name__}: {error}")
                logger.warning("Storyboard edit failed on %s", model, exc_info=True)

        raise RuntimeError("Storyboard edit failed | " + " | ".join(failures))

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
