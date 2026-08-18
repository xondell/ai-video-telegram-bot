from pathlib import Path

import aiofiles
import httpx

from app.config import settings


class StorageUnavailable(RuntimeError):
    """Raised when Supabase Storage is unavailable."""


class SupabaseStorage:
    @property
    def enabled(self) -> bool:
        return bool(
            settings.supabase_url
            and settings.supabase_service_role_key
        )

    def _headers(
        self,
        content_type: str | None = None,
    ) -> dict[str, str]:

        key = settings.supabase_service_role_key

        headers = {
            "apikey": key,
        }

        # New sb_secret_* keys are opaque API keys, not JWTs.
        # Legacy service_role keys are JWTs and can be Bearer tokens.
        if not key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {key}"

        if content_type:
            headers["Content-Type"] = content_type

        return headers

    async def upload_file(
        self,
        local_path: Path,
        key: str,
        content_type: str,
        upsert: bool = True,
    ) -> str:

        if not self.enabled:
            raise StorageUnavailable(
                "Supabase Storage environment variables are missing"
            )

        url = (
            f"{settings.supabase_url.rstrip('/')}"
            f"/storage/v1/object/"
            f"{settings.supabase_storage_bucket}/{key}"
        )

        headers = self._headers(content_type)
        headers["x-upsert"] = (
            "true" if upsert else "false"
        )

        # Important:
        # AsyncClient cannot consume a normal synchronous file object.
        # Read asynchronously first and send bytes.
        async with aiofiles.open(local_path, "rb") as file:
            payload = await file.read()

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                url,
                content=payload,
                headers=headers,
            )

            response.raise_for_status()

        return key

    async def download_file(
        self,
        key: str,
        destination: Path,
    ) -> Path:

        if not self.enabled:
            raise StorageUnavailable(
                "Supabase Storage environment variables are missing"
            )

        url = (
            f"{settings.supabase_url.rstrip('/')}"
            f"/storage/v1/object/authenticated/"
            f"{settings.supabase_storage_bucket}/{key}"
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(
                url,
                headers=self._headers(),
            )

            response.raise_for_status()

        async with aiofiles.open(destination, "wb") as file:
            await file.write(response.content)

        return destination


storage = SupabaseStorage()
