import time
from datetime import date
from decimal import Decimal

import httpx

from app.config import settings


class PricingUnavailable(RuntimeError):
    """Raised when current pricing cannot be verified safely."""


# Official fal.ai PixVerse V6 model page, verified 2026-08-18:
# 720p / generated audio OFF = $0.045 per generated second.
PIXVERSE_720P_NO_AUDIO_VERIFIED_PPS = Decimal("0.045")
PIXVERSE_PRICE_VERIFIED_ON = date(2026, 8, 18)

# Do not allow the manually verified resolution-specific price
# to silently live forever.
MAX_VERIFIED_PRICE_AGE_DAYS = 30


class FalPricingService:
    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._cache_ts: dict[str, float] = {}

    async def get_price(self, endpoint_id: str) -> dict:
        if not settings.fal_key:
            raise PricingUnavailable("FAL_KEY is missing")

        now = time.time()

        if (
            endpoint_id in self._cache
            and now - self._cache_ts.get(endpoint_id, 0)
            <= settings.price_cache_ttl_seconds
        ):
            return self._cache[endpoint_id]

        headers = {
            "Authorization": f"Key {settings.fal_key}"
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://api.fal.ai/v1/models/pricing",
                    params={"endpoint_id": endpoint_id},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as error:
            raise PricingUnavailable(
                f"fal pricing API unavailable: "
                f"{type(error).__name__}"
            ) from error

        prices = payload.get("prices") or []

        row = next(
            (
                p for p in prices
                if p.get("endpoint_id") == endpoint_id
            ),
            None,
        )

        if not row:
            raise PricingUnavailable(
                f"No live pricing returned for {endpoint_id}"
            )

        if str(row.get("currency", "USD")).upper() != "USD":
            raise PricingUnavailable(
                "Non-USD pricing is not supported"
            )

        self._cache[endpoint_id] = row
        self._cache_ts[endpoint_id] = now

        return row

    async def exact_pixverse_720p_no_audio_pps(
        self,
        endpoint_id: str,
    ) -> Decimal:

        if endpoint_id != "fal-ai/pixverse/v6/text-to-video":
            raise PricingUnavailable(
                f"Unsupported PixVerse pricing endpoint: "
                f"{endpoint_id}"
            )

        # Live API MUST work. We never generate paid video
        # solely from a hardcoded price.
        row = await self.get_price(endpoint_id)

        unit = (
            str(row.get("unit", ""))
            .lower()
            .replace(" ", "_")
        )

        accepted_units = {
            "second",
            "seconds",
            "video_second",
            "video_seconds",
            "generated_second",
            "generated_seconds",
        }

        if unit not in accepted_units:
            raise PricingUnavailable(
                f"Unexpected PixVerse billing unit: {unit!r}"
            )

        try:
            live_unit_price = Decimal(
                str(row.get("unit_price"))
            )
        except Exception as error:
            raise PricingUnavailable(
                "Invalid live fal unit_price"
            ) from error

        if live_unit_price <= Decimal("0"):
            raise PricingUnavailable(
                "Live fal price is not positive"
            )

        if live_unit_price > Decimal("0.20"):
            raise PricingUnavailable(
                "Live price is outside safety envelope"
            )

        age_days = (
            date.today() - PIXVERSE_PRICE_VERIFIED_ON
        ).days

        if age_days > MAX_VERIFIED_PRICE_AGE_DAYS:
            raise PricingUnavailable(
                "Resolution-specific PixVerse price "
                "verification is stale"
            )

        # fal's generic pricing API can expose a base unit price
        # that is lower than the selected 720p tier.
        #
        # Never use less than the currently verified 720p/no-audio
        # published price. If fal reports a HIGHER live price,
        # use the higher one to stay conservative.
        effective_price = max(
            live_unit_price,
            PIXVERSE_720P_NO_AUDIO_VERIFIED_PPS,
        )

        return effective_price
