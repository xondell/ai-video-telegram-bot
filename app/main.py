import hmac
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from app.bot.handlers import router
from app.config import settings
from app.db.models import TelegramUpdate
from app.db.session import SessionLocal
from app.jobs.fal_webhook import handle_fal_webhook

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
app = FastAPI(title="AI Video Telegram Bot", version="0.3.0")
dp = Dispatcher()
dp.include_router(router)
_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN is not configured")
    if _bot is None:
        _bot = Bot(settings.telegram_bot_token)
    return _bot


@app.get("/")
@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "ai-video-telegram-bot",
        "runtime": "vercel-webhook",
        "configured": settings.is_vercel_ready,
        "supabase_project_ref": "avpkxroflhlifjxfqbqi",
        "supabase_storage_configured": bool(settings.supabase_service_role_key),
        "hard_job_limit_usd": str(settings.max_job_cost_usd),
        "global_budget_usd": str(settings.global_project_budget_usd),
        "manual_env_count": 5,
    }


@app.post("/api/telegram/{token}")
async def telegram_webhook(token: str, request: Request):
    expected = settings.telegram_webhook_token
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook path")

    bot = get_bot()
    payload = await request.json()
    update = Update.model_validate(payload, context={"bot": bot})

    # Telegram retries webhook deliveries; make update processing idempotent across Vercel instances.
    async with SessionLocal() as session:
        session.add(TelegramUpdate(update_id=update.update_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"ok": True, "duplicate": True}

    # Pass the deployment base URL into aiogram context. This avoids PUBLIC_BASE_URL env.
    base_url = str(request.base_url).rstrip("/")
    await dp.feed_update(bot, update, public_base_url=base_url)
    return {"ok": True}


@app.post("/api/fal/webhook/{token}")
async def fal_webhook(token: str, request: Request):
    expected = settings.fal_webhook_token
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid fal webhook path")
    return await handle_fal_webhook(await request.json(), get_bot())
