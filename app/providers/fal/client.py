import os
import fal_client
from app.config import settings


class FalVideoClient:
    def __init__(self):
        if settings.fal_key:
            os.environ["FAL_KEY"] = settings.fal_key

    async def submit(self, endpoint: str, arguments: dict, webhook_url: str) -> str:
        if not settings.fal_key:
            raise RuntimeError("FAL_KEY is missing")
        handle = await fal_client.submit_async(
            endpoint,
            arguments=arguments,
            webhook_url=webhook_url,
            headers={"X-Fal-No-Retry": "1"},
        )
        return handle.request_id
