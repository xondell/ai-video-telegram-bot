from pathlib import Path
import httpx
from app.config import settings


class StorageUnavailable(RuntimeError):
    """Raised when Supabase Storage is not configured or unavailable."""


class SupabaseStorage:
    @property
    def enabled(self) -> bool:
        return bool(settings.supabase_url and settings.supabase_service_role_key)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def upload_file(self, local_path: Path, key: str, content_type: str, upsert: bool = True) -> str:
        if not self.enabled:
            raise StorageUnavailable("Supabase Storage environment variables are missing")
        url = (
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{settings.supabase_storage_bucket}/{key}"
        )
        headers = self._headers(content_type)
        headers["x-upsert"] = "true" if upsert else "false"
        async with httpx.AsyncClient(timeout=120) as client:
            with local_path.open("rb") as f:
                response = await client.post(url, content=f, headers=headers)
            response.raise_for_status()
        return key

    async def download_file(self, key: str, destination: Path) -> Path:
        if not self.enabled:
            raise StorageUnavailable("Supabase Storage environment variables are missing")
        url = (
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/authenticated/"
            f"{settings.supabase_storage_bucket}/{key}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination


storage = SupabaseStorage()
