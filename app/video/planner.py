from decimal import Decimal, ROUND_DOWN
from pydantic import BaseModel
from app.config import settings
from app.models.registry import MODELS
from app.ai.schemas import VideoScript


class PlannedScene(BaseModel):
    scene_id: int
    seconds: int
    prompt: str
    negative_prompt: str = ""
    importance: float


class GenerationPlan(BaseModel):
    model_key: str
    endpoint: str
    estimated_cost: Decimal
    generated_video_seconds: int
    operations: list[PlannedScene]


class GenerationPlanner:
    def plan(self, script: VideoScript, model_key: str, price_per_second: Decimal) -> GenerationPlan:
        model = MODELS[model_key]
        if not model.paid_enabled:
            raise RuntimeError(f"Paid generation is disabled for {model_key} until exact live pricing is supported")
        clip = model.seconds_per_clip
        affordable = int((settings.target_job_cost_usd / price_per_second).to_integral_value(rounding=ROUND_DOWN))
        max_seconds = max(0, (affordable // clip) * clip)
        scenes = sorted(script.scenes, key=lambda scene: scene.importance, reverse=True)
        operations: list[PlannedScene] = []
        used = 0
        for scene in scenes:
            if used + clip > max_seconds:
                break
            operations.append(PlannedScene(
                scene_id=scene.id,
                seconds=clip,
                prompt=scene.video_prompt,
                negative_prompt=scene.negative_prompt,
                importance=scene.importance,
            ))
            used += clip
        cost = (price_per_second * used).quantize(Decimal("0.000001"))
        if not operations:
            raise RuntimeError("No AI-video operation fits the configured target budget")
        if cost > settings.target_job_cost_usd or cost > settings.max_job_cost_usd:
            raise RuntimeError("Unsafe generation plan")
        return GenerationPlan(
            model_key=model_key,
            endpoint=model.endpoint,
            estimated_cost=cost,
            generated_video_seconds=used,
            operations=operations,
        )
