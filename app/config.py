import hashlib
import hmac
from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


SUPABASE_PROJECT_REF = "avpkxroflhlifjxfqbqi"
SUPABASE_PROJECT_URL = f"https://{SUPABASE_PROJECT_REF}.supabase.co"
SUPABASE_STORAGE_BUCKET = "bot-media"


class Settings(BaseSettings):
    """Runtime configuration.

    Only five values are expected from Vercel Environment Variables:
    Telegram, Google AI, fal.ai, Supabase database URL and Supabase service-role key.
    Everything else is a code-level safety default for this dedicated deployment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    google_ai_api_key: str = ""
    fal_key: str = ""
    supabase_database_url: str = ""
    supabase_service_role_key: str = ""

    # Dedicated Supabase project created for this bot. Public identifiers are not secrets.
    supabase_url: str = SUPABASE_PROJECT_URL
    supabase_storage_bucket: str = SUPABASE_STORAGE_BUCKET

    # Fixed model policy. Paid providers other than the strict PixVerse adapter stay disabled.
    gemini_primary_model: str = "gemini-3.1-flash-lite"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_secondary_fallback_model: str = "gemini-3.6-flash"
    google_image_model: str = "gemini-3.1-flash-image"
    enable_paid_google_images: bool = False
    enable_google_video: bool = False
    enable_paid_ai_music: bool = False

    # Hard safety limits are intentionally code defaults, not deploy-time knobs.
    max_job_cost_usd: Decimal = Decimal("2.00")
    target_job_cost_usd: Decimal = Decimal("1.80")
    emergency_reserve_usd: Decimal = Decimal("0.20")
    global_project_budget_usd: Decimal = Decimal("10.00")
    price_cache_ttl_seconds: int = 1200

    temp_dir: Path = Path("/tmp/ai-video")
    output_dir: Path = Path("/tmp/ai-video-output")
    max_audio_mb: int = 50
    max_audio_seconds: int = 180
    log_level: str = "INFO"

    @property
    def admins(self) -> set[int]:
        # No extra ADMIN env var. Add IDs here only if /admin_budget is needed later.
        return set()

    @property
    def async_database_url(self) -> str:
        url = self.supabase_database_url.strip()

        if url.startswith("postgresql+psycopg://"):
            return url

        if url.startswith("postgresql+asyncpg://"):
            return (
                "postgresql+psycopg://"
                + url[len("postgresql+asyncpg://"):]
            )

        if url.startswith("postgresql://"):
            return (
                "postgresql+psycopg://"
                + url[len("postgresql://"):]
            )

        if url.startswith("postgres://"):
            return (
                "postgresql+psycopg://"
                + url[len("postgres://"):]
            )

        return url

    @staticmethod
    def _derived_webhook_token(secret: str, purpose: str) -> str:
        if not secret:
            return ""
        return hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).hexdigest()[:48]

    @property
    def telegram_webhook_token(self) -> str:
        return self._derived_webhook_token(self.telegram_bot_token, "telegram-webhook-v1")

    @property
    def fal_webhook_token(self) -> str:
        return self._derived_webhook_token(self.fal_key, "fal-webhook-v1")

    @property
    def is_vercel_ready(self) -> bool:
        return all([
            self.telegram_bot_token,
            self.google_ai_api_key,
            self.fal_key,
            self.supabase_database_url,
            self.supabase_service_role_key,
        ])

    def validate_runtime(self):
        missing = []
        for key, value in {
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "GOOGLE_AI_API_KEY": self.google_ai_api_key,
            "FAL_KEY": self.fal_key,
            "SUPABASE_DATABASE_URL": self.supabase_database_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
        }.items():
            if not value:
                missing.append(key)
        if missing:
            raise RuntimeError("Missing required env vars: " + ", ".join(missing))


settings = Settings()
