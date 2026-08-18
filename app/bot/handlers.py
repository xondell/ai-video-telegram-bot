import json
import uuid
from decimal import Decimal
from pathlib import Path

from aiogram import F, Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.ai.google_client import GeminiService
from app.ai.schemas import AudioAnalysis, VideoScript
from app.budget.controller import BudgetExceeded, CostController
from app.config import settings
from app.db.models import Job, JobStatus, Scene, User
from app.db.session import SessionLocal
from app.models.registry import MODELS
from app.providers.fal.client import FalVideoClient
from app.providers.fal.pricing import FalPricingService, PricingUnavailable
from app.services.storage import storage
from app.utils.audio import InvalidAudio, probe_audio
from app.video.planner import GenerationPlan, GenerationPlanner
from .keyboards import confirm_kb, model_kb, ratio_kb, style_kb

router = Router()
gemini = GeminiService()
pricing = FalPricingService()
costs = CostController()
fal = FalVideoClient()


def _ratio_from_token(token: str) -> str:
    return token.replace("x", ":")


def _pixverse_ratio(ratio: str) -> str:
    # PixVerse supports 3:4 but not 4:5. Renderer crops it to final 4:5.
    return "3:4" if ratio == "4:5" else ratio


async def _user_for(message_or_callback) -> User:
    tg = message_or_callback.from_user
    async with SessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.telegram_user_id == tg.id)
        )).scalar_one_or_none()
        if user is None:
            user = User(telegram_user_id=tg.id, username=tg.username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def _owned_job(event, job_id: int) -> Job | None:
    user = await _user_for(event)
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None or job.user_id != user.id:
            return None
        return job


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎬 AI Video Generator\n\n"
        "Отправь voice или аудиофайл (до 3 минут). Я распознаю речь, создам сценарий, "
        "сгенерирую ключевые AI-сцены и соберу MP4.\n\n"
        "💰 HARD LIMIT платных media API: $2.00 на задачу."
    )


@router.message(Command("admin_budget"))
async def admin_budget(message: Message):
    if message.from_user.id not in settings.admins:
        return
    b = await costs.snapshot()
    await message.answer(
        f"💰 Project budget\nLimit: ${b['limit']:.2f}\nSpent: ${b['spent']:.2f}\n"
        f"Reserved: ${b['reserved']:.2f}\nAvailable: ${b['available']:.2f}"
    )


@router.message(F.voice | F.audio | F.document)
async def audio_upload(message: Message, bot: Bot):
    obj = message.voice or message.audio or message.document
    if obj.file_size and obj.file_size > settings.max_audio_mb * 1024 * 1024:
        return await message.answer("Файл слишком большой.")

    if message.voice:
        suffix = ".ogg"
        tg_duration = message.voice.duration
    elif message.audio:
        suffix = Path(message.audio.file_name or "audio.mp3").suffix.lower() or ".mp3"
        tg_duration = message.audio.duration
    else:
        suffix = Path(message.document.file_name or "audio.bin").suffix.lower() or ".bin"
        tg_duration = None

    if suffix not in {".ogg", ".mp3", ".wav", ".m4a", ".aac", ".mp4", ".bin"}:
        return await message.answer("Неподдерживаемый формат.")

    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    local_path = settings.temp_dir / f"{uuid.uuid4()}{suffix}"
    tg_file = await bot.get_file(obj.file_id)
    await bot.download_file(tg_file.file_path, destination=local_path)

    try:
        duration = await probe_audio(local_path, tg_duration)
    except InvalidAudio as error:
        local_path.unlink(missing_ok=True)
        return await message.answer(f"Некорректное аудио: {error}")

    user = await _user_for(message)
    async with SessionLocal() as session:
        job = Job(
            user_id=user.id,
            telegram_chat_id=message.chat.id,
            source_audio_path=str(local_path),
            duration_seconds=duration,
            status=JobStatus.ANALYZING,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    progress = await message.answer("🎧 Анализирую аудио...")
    storage_key = None
    try:
        if storage.enabled:
            storage_key = f"audio/{job_id}/source{suffix}"
            await storage.upload_file(local_path, storage_key, getattr(obj, "mime_type", None) or "application/octet-stream")
        analysis = await gemini.analyze_audio(local_path, duration)
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            job.source_audio_storage_key = storage_key
            job.transcript_json = analysis.model_dump_json()
            job.status = JobStatus.WAITING_SETTINGS
            await session.commit()
    except Exception as error:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                await session.commit()
        return await progress.edit_text(f"Ошибка анализа: {type(error).__name__}")

    await progress.edit_text(
        f"✅ Аудио распознано: {duration:.1f} сек.\n\n📐 Выберите формат",
        reply_markup=ratio_kb(job_id),
    )


@router.callback_query(F.data.startswith("r:"))
async def choose_ratio(callback: CallbackQuery):
    _, raw_job_id, token = callback.data.split(":", 2)
    job_id = int(raw_job_id)
    job = await _owned_job(callback, job_id)
    if not job:
        return await callback.answer("Job not found", show_alert=True)
    ratio = _ratio_from_token(token)
    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.aspect_ratio = ratio
        await session.commit()
    await callback.answer()
    await callback.message.edit_text("🎨 Выберите стиль", reply_markup=style_kb(job_id))


@router.callback_query(F.data.startswith("s:"))
async def choose_style(callback: CallbackQuery):
    _, raw_job_id, style = callback.data.split(":", 2)
    job_id = int(raw_job_id)
    job = await _owned_job(callback, job_id)
    if not job:
        return await callback.answer("Job not found", show_alert=True)
    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.style = style
        await session.commit()
    await callback.answer()
    await callback.message.edit_text("🤖 Выберите AI-модель", reply_markup=model_kb(job_id))


@router.callback_query(F.data.startswith("m:"))
async def choose_model(callback: CallbackQuery):
    _, raw_job_id, selected = callback.data.split(":", 2)
    job_id = int(raw_job_id)
    job = await _owned_job(callback, job_id)
    if not job:
        return await callback.answer("Job not found", show_alert=True)
    model_key = "pixverse-v6" if selected == "auto" else selected
    vm = MODELS.get(model_key)
    if vm is None or not vm.paid_enabled:
        return await callback.answer(
            "Эта модель пока заблокирована: нет достаточно строгого live cost adapter для hard limit $2.",
            show_alert=True,
        )
    if not job.aspect_ratio or not job.style or not job.transcript_json:
        return await callback.answer("Настройки job неполные", show_alert=True)

    await callback.answer("Создаю сценарий и считаю live price…")
    await callback.message.edit_text("🧠 Создаю сценарий и безопасный generation plan…")
    try:
        analysis = AudioAnalysis.model_validate_json(job.transcript_json)
        script = await gemini.make_script(analysis, job.style, job.aspect_ratio, job.intensity)
        pps = await pricing.exact_pixverse_720p_no_audio_pps(vm.endpoint)
        plan = GenerationPlanner().plan(script, model_key, pps)
    except (PricingUnavailable, Exception) as error:
        return await callback.message.edit_text(
            f"⚠️ Не удалось построить безопасный план: {type(error).__name__}.\n"
            "Платная генерация не запускалась."
        )

    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.selected_provider = vm.provider
        row.selected_model = model_key
        row.script_json = script.model_dump_json()
        row.plan_json = plan.model_dump_json()
        row.estimated_cost = plan.estimated_cost
        row.status = JobStatus.WAITING_CONFIRMATION
        await session.commit()

    await callback.message.edit_text(
        f"🎬 Ваше видео\n\n📐 {job.aspect_ratio}\n🎨 {job.style}\n"
        f"🤖 {vm.display_name}\n⏱ Final: ~{analysis.duration_seconds:.0f}s\n\n"
        f"💰 HARD LIMIT: $2.00\n🎯 Planned maximum: ${plan.estimated_cost:.2f}\n"
        f"🛡 Headroom: ${(settings.max_job_cost_usd - plan.estimated_cost):.2f}\n"
        f"🎞 Unique AI video: ~{plan.generated_video_seconds}s",
        reply_markup=confirm_kb(job_id),
    )


@router.callback_query(F.data.startswith("c:"))
async def confirm(callback: CallbackQuery, public_base_url: str):
    _, raw_job_id, action = callback.data.split(":", 2)
    job_id = int(raw_job_id)
    job = await _owned_job(callback, job_id)
    if not job:
        return await callback.answer("Job not found", show_alert=True)
    if action == "cancel":
        async with SessionLocal() as session:
            row = await session.get(Job, job_id)
            row.status = JobStatus.CANCELLED
            await session.commit()
        await callback.answer()
        return await callback.message.edit_text("❌ Отменено.")

    if job.status != JobStatus.WAITING_CONFIRMATION or not job.plan_json or not job.script_json:
        return await callback.answer("Job is not ready for generation", show_alert=True)

    vm = MODELS[job.selected_model]
    try:
        pps = await pricing.exact_pixverse_720p_no_audio_pps(vm.endpoint)
        script = VideoScript.model_validate_json(job.script_json)
        # Re-plan at confirmation using fresh live pricing. Never trust the earlier summary blindly.
        plan = GenerationPlanner().plan(script, job.selected_model, pps)
    except Exception as error:
        return await callback.answer(f"Live price validation failed: {type(error).__name__}", show_alert=True)

    # Atomically claim the job before any paid request. A duplicate Telegram callback
    # must not start a second paid generation path on another Vercel instance.
    async with SessionLocal() as session:
        row = await session.get(Job, job_id, with_for_update=True)
        if row is None or row.status != JobStatus.WAITING_CONFIRMATION:
            await session.rollback()
            return await callback.answer("Generation already started or job is no longer ready", show_alert=True)
        row.plan_json = plan.model_dump_json()
        row.estimated_cost = plan.estimated_cost
        row.status = JobStatus.GENERATING
        await session.commit()

    await callback.answer("Запускаю AI-сцены…")
    await callback.message.edit_text("🎬 Создание видео\n\n✅ Script\n✅ Live price\n⏳ Submitting AI scenes…")
    webhook_url = f"{public_base_url.rstrip('/')}/api/fal/webhook/{settings.fal_webhook_token}"
    submitted = 0
    try:
        for index, op in enumerate(plan.operations):
            max_cost = (pps * Decimal(op.seconds)).quantize(Decimal("0.000001"))
            ledger_id = await costs.reserve(job_id, "video_generation", "fal", vm.endpoint, max_cost)
            scene = Scene(
                job_id=job_id,
                scene_index=index,
                duration_seconds=op.seconds,
                importance=op.importance,
                provider="fal",
                model=vm.endpoint,
                prompt=op.prompt,
                negative_prompt=op.negative_prompt,
                estimated_cost=max_cost,
                ledger_id=ledger_id,
                status="SUBMITTING",
            )
            async with SessionLocal() as session:
                session.add(scene)
                await session.commit()
                await session.refresh(scene)
                scene_db_id = scene.id
            try:
                request_id = await fal.submit(
                    vm.endpoint,
                    {
                        "prompt": op.prompt,
                        "aspect_ratio": _pixverse_ratio(job.aspect_ratio),
                        "resolution": "720p",
                        "duration": op.seconds,
                        "negative_prompt": op.negative_prompt[:2000],
                        "generate_audio_switch": False,
                        "generate_multi_clip_switch": False,
                        "thinking_type": "auto",
                    },
                    webhook_url,
                )
            except Exception:
                # The request may have reached fal.ai even when the client lost the response.
                # Keep the reservation locked until billing is reconciled; releasing it here
                # could let a later request push the job above the $2 hard cap.
                await costs.quarantine(ledger_id, "SUBMIT_UNKNOWN")
                async with SessionLocal() as session:
                    row = await session.get(Scene, scene_db_id)
                    row.status = "SUBMIT_UNKNOWN"
                    await session.commit()
                raise
            async with SessionLocal() as session:
                row = await session.get(Scene, scene_db_id)
                row.request_id = request_id
                row.status = "QUEUED"
                await session.commit()
            submitted += 1
    except (BudgetExceeded, Exception) as error:
        await callback.message.edit_text(
            f"⚠️ Generation stopped after {submitted} submitted scene(s): {type(error).__name__}.\n"
            "Новые платные запросы остановлены. Уже успешно отправленные запросы остаются учтёнными в budget ledger."
        )
        return

    await callback.message.edit_text(
        f"🎬 Создание видео\n\n✅ Script\n✅ Live price\n✅ Submitted {submitted}/{len(plan.operations)} AI scenes\n"
        "⏳ fal.ai работает асинхронно. Результаты придут через webhook, затем бот сам соберёт MP4."
    )
