from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class VideoModel:
    key: str
    provider: str
    endpoint: str
    display_name: str
    resolution: str
    seconds_per_clip: int
    paid_enabled: bool
    reference_price: Decimal | None = None


MODELS = {
    "pixverse-v6": VideoModel(
        "pixverse-v6", "fal", "fal-ai/pixverse/v6/text-to-video",
        "⚡ PixVerse V6 — Recommended", "720p", 5, True, Decimal("0.045")
    ),
    "hailuo-2.3": VideoModel(
        "hailuo-2.3", "fal", "fal-ai/minimax/hailuo-2.3/standard/text-to-video",
        "🎬 Hailuo 2.3 — Balanced", "768p", 6, False, None
    ),
    "kling-3": VideoModel(
        "kling-3", "fal", "fal-ai/kling-video/v3/standard/text-to-video",
        "💎 Kling 3 — Cinematic", "720p", 5, False, None
    ),
    "wan-2.7": VideoModel(
        "wan-2.7", "fal", "fal-ai/wan/v2.7/text-to-video",
        "🎥 Wan 2.7 — Advanced", "720p", 5, False, None
    ),
}
