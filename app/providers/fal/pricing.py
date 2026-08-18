import time
from decimal import Decimal
import httpx
from app.config import settings


class PricingUnavailable(RuntimeError):
    """Raised when current pricing cannot be verified safely."""


class FalPricingService:
    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._cache_ts: dict[str, float] = {}

    async def get_price(self, endpoint_id: str) -> dict:
        if not settings.fal_key:
            raise PricingUnavailable("FAL_KEY is missing")
        now = time.time()
        if endpoint_id in self._cache and now - self._cache_ts.get(endpoint_id, 0) <= settings.price_cache_ttl_seconds:
            return self._cache[endpoint_id]
        headers = {"Authorization": f"Key {settings.fal_key}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.fal.ai/v1/models/pricing",
                params={"endpoint_id": endpoint_id},
                headers=headers,
            )
            response.raise_for_status()
            prices = response.json().get("prices", [])
        row = next((p for p in prices if p.get("endpoint_id") == endpoint_id), None)
        if not row:
            raise PricingUnavailable(f"No live pricing returned for {endpoint_id}")
        if str(row.get("currency", "USD")).upper() != "USD":
            raise PricingUnavailable("Non-USD pricing is not supported")
        self._cache[endpoint_id] = row
        self._cache_ts[endpoint_id] = now
        return row

    async def exact_pixverse_720p_no_audio_pps(self, endpoint_id: str) -> Decimal:
        row = await self.get_price(endpoint_id)
        unit = str(row.get("unit", "")).lower().replace(" ", "_")
        if unit not in {"second", "seconds", "video_second", "generated_second", "video_seconds"}:
            raise PricingUnavailable(f"Unexpected PixVerse billing unit: {unit!r}")
        value = Decimal(str(row.get("unit_price")))
        # Fail closed if the live endpoint price is below the currently published 720p/no-audio
        # floor. This prevents accidentally treating a cheaper resolution/default as 720p pricing.
        if value < Decimal("0.045"):
            raise PricingUnavailable(
                f"Live unit price ${value}/s is below the verified 720p/no-audio floor; refusing paid generation"
            )
        if value > Decimal("0.20"):
            raise PricingUnavailable("Live price is outside the configured safety envelope")
        return value
