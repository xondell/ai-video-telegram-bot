from decimal import Decimal
from app.ai.schemas import VideoScript, Scene
from app.video.planner import GenerationPlanner

def test_pixverse_target_cap():
    scenes = [
        Scene(
            id=i, start=i*5, end=(i+1)*5, narration="x",
            importance=max(0.1, 1-i/100), video_prompt="cinematic shot"
        )
        for i in range(20)
    ]
    plan = GenerationPlanner().plan(
        VideoScript(title="x", visual_direction="x", scenes=scenes),
        "pixverse-v6", Decimal("0.045")
    )
    assert plan.estimated_cost <= Decimal("4.50")
    assert plan.generated_video_seconds == 40
