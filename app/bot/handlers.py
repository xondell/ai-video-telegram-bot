import json
import re
import logging
import uuid
from decimal import Decimal
from pathlib import Path

from aiogram import F, Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ForceReply, Message
from sqlalchemy import select

from app.ai.google_client import GeminiService
from app.ai.schemas import AudioAnalysis, VideoScript
from app.ai.script_editor import StoryboardEditorService
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
from .keyboards import confirm_kb, model_kb, ratio_kb, storyboard_kb, style_kb

logger = logging.getLogger(__name__)

router = Router()
gemini = GeminiService()
pricing = FalPricingService()
costs = CostController()
fal = FalVideoClient()
storyboard_editor = StoryboardEditorService()


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




def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _storyboard_pages(script: VideoScript, max_chars: int = 3600) -> list[str]:
    blocks = [
        "🎬 СЦЕНАРИЙ ПЕРЕД ГЕНЕРАЦИЕЙ\n"
        f"Название: {script.title}\n"
        f"Visual direction: {script.visual_direction}"
    ]
    for i, scene in enumerate(script.scenes, 1):
        block = (
            f"{i:02d} • {_clock(scene.start)}–{_clock(scene.end)}\n"
            f"🗣 {scene.narration}\n"
            f"🎥 {scene.video_prompt}"
        )
        if scene.camera:
            block += f"\n📷 Camera: {scene.camera}"
        if scene.transition:
            block += f"\n↪️ Transition: {scene.transition}"
        blocks.append(block)

    pages: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pages.append(current)
            current = block[:max_chars]
    if current:
        pages.append(current)
    return pages or ["🎬 Сценарий пуст."]


async def _show_storyboard(message: Message, job_id: int, script: VideoScript, note: str = ""):
    pages = _storyboard_pages(script)
    for index, page in enumerate(pages):
        prefix = (note + "\n\n") if note and index == 0 else ""
        markup = storyboard_kb(job_id) if index == len(pages) - 1 else None
        await message.answer(prefix + page, reply_markup=markup)

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎬 AI Video Generator\n\n"
        f"Отправь voice или аудиофайл (до {settings.max_audio_seconds} секунд). "
        "Я распознаю речь, создам сценарий, "
        "сгенерирую ключевые AI-сцены и соберу MP4.\n\n"
        f"💰 HARD LIMIT платных media API: ${settings.max_job_cost_usd:.2f} на задачу."
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
        logger.exception(
            "Audio analysis failed for job_id=%s",
            job_id,
        )
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
            f"Эта модель пока заблокирована: нет достаточно строгого live cost adapter для hard limit ${settings.max_job_cost_usd:.2f}.",
            show_alert=True,
        )
    if not job.aspect_ratio or not job.style or not job.transcript_json:
        return await callback.answer("Настройки job неполные", show_alert=True)

    await callback.answer("Создаю сценарий…")
    await callback.message.edit_text(
        "🧠 Создаю сценарий. Платная video generation ещё НЕ запускается…"
    )

    try:
        analysis = AudioAnalysis.model_validate_json(job.transcript_json)
        script = await gemini.make_script(
            analysis,
            job.style,
            job.aspect_ratio,
            job.intensity,
        )
    except Exception as error:
        return await callback.message.edit_text(
            f"⚠️ Не удалось создать сценарий: {type(error).__name__}.\n"
            "Платная генерация не запускалась."
        )

    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.selected_provider = vm.provider
        row.selected_model = model_key
        row.script_json = script.model_dump_json()
        row.plan_json = None
        row.estimated_cost = Decimal("0")
        row.status = JobStatus.WAITING_CONFIRMATION
        await session.commit()

    await _show_storyboard(
        callback.message,
        job_id,
        script,
        note=(
            f"📐 {job.aspect_ratio}  •  🎨 {job.style}  •  🤖 {vm.display_name}\n"
            "Проверь сценарий. До подтверждения никакие платные fal.ai video-запросы не отправляются."
        ),
    )


@router.callback_query(F.data.startswith("sb:"))
async def storyboard_action(callback: CallbackQuery):
    _, raw_job_id, action = callback.data.split(":", 2)
    job_id = int(raw_job_id)
    job = await _owned_job(callback, job_id)
    if not job or not job.script_json or not job.selected_model:
        return await callback.answer("Сценарий не найден", show_alert=True)

    if action == "cancel":
        async with SessionLocal() as session:
            row = await session.get(Job, job_id)
            row.status = JobStatus.CANCELLED
            await session.commit()
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=None)
        return await callback.message.answer("❌ Задача отменена.")

    script = VideoScript.model_validate_json(job.script_json)

    if action == "edit":
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=None)
        return await callback.message.answer(
            f"✏️ РЕДАКТИРОВАНИЕ СЦЕНАРИЯ\nEDIT_JOB_ID={job_id}\n\n"
            "Ответь НА ЭТО сообщение обычным текстом и напиши, что изменить.\n\n"
            "Например:\n"
            "• В сцене 1 вместо города сделай лес на рассвете.\n"
            "• Сцену 2 сделай менее футуристичной.\n"
            "• Добавь больше крупных планов и плавные переходы.\n\n"
            "Тайминг и исходная речь останутся неизменными.",
            reply_markup=ForceReply(selective=True),
        )

    if action == "regen":
        await callback.answer("Регенерирую сценарий…")
        await callback.message.edit_reply_markup(reply_markup=None)
        status = await callback.message.answer("🔄 Создаю альтернативный сценарий…")
        try:
            new_script = await storyboard_editor.regenerate(
                script,
                style=job.style or "",
                ratio=job.aspect_ratio or "",
            )
        except Exception as error:
            return await status.edit_text(
                f"⚠️ Не удалось регенерировать сценарий: {type(error).__name__}"
            )
        async with SessionLocal() as session:
            row = await session.get(Job, job_id)
            row.script_json = new_script.model_dump_json()
            row.plan_json = None
            row.estimated_cost = Decimal("0")
            row.status = JobStatus.WAITING_CONFIRMATION
            await session.commit()
        await status.edit_text("✅ Альтернативный сценарий готов.")
        return await _show_storyboard(callback.message, job_id, new_script)

    if action != "approve":
        return await callback.answer("Unknown action", show_alert=True)

    vm = MODELS[job.selected_model]
    await callback.answer("Проверяю live price…")
    await callback.message.edit_reply_markup(reply_markup=None)
    status = await callback.message.answer(
        "💰 Сценарий принят. Считаю безопасный план генерации…"
    )
    try:
        pps = await pricing.exact_pixverse_720p_no_audio_pps(vm.endpoint)
        plan = GenerationPlanner().plan(script, job.selected_model, pps)
    except Exception as error:
        return await status.edit_text(
            f"⚠️ Не удалось построить безопасный план: {type(error).__name__}.\n"
            "Платная генерация не запускалась."
        )

    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.plan_json = plan.model_dump_json()
        row.estimated_cost = plan.estimated_cost
        row.status = JobStatus.WAITING_CONFIRMATION
        await session.commit()

    analysis = AudioAnalysis.model_validate_json(job.transcript_json)
    await status.edit_text(
        f"🎬 Всё готово к генерации\n\n"
        f"📐 {job.aspect_ratio}\n🎨 {job.style}\n🤖 {vm.display_name}\n"
        f"⏱ Final: ~{analysis.duration_seconds:.0f}s\n\n"
        f"💰 HARD LIMIT: ${settings.max_job_cost_usd:.2f}\n"
        f"🎯 Planned maximum: ${plan.estimated_cost:.2f}\n"
        f"🛡 Headroom: ${(settings.max_job_cost_usd - plan.estimated_cost):.2f}\n"
        f"🎞 Unique AI video: ~{plan.generated_video_seconds}s\n\n"
        "Нажатие «Создать» запустит платные video-запросы.",
        reply_markup=confirm_kb(job_id),
    )


@router.message(F.text)
async def storyboard_edit_reply(message: Message):
    reply = message.reply_to_message
    if not reply or not reply.text:
        return
    match = re.search(r"EDIT_JOB_ID=(\d+)", reply.text)
    if not match:
        return

    job_id = int(match.group(1))
    job = await _owned_job(message, job_id)
    if not job or not job.script_json:
        return await message.answer("Сценарий не найден или уже недоступен.")

    instructions = (message.text or "").strip()
    if not instructions:
        return await message.answer("Напиши, что именно нужно изменить.")
    if len(instructions) > 4000:
        return await message.answer(
            "Слишком длинное описание правок. Максимум 4000 символов."
        )

    status = await message.answer("✏️ Применяю правки к сценарию…")
    script = VideoScript.model_validate_json(job.script_json)
    try:
        new_script = await storyboard_editor.revise(
            script,
            instructions,
            style=job.style or "",
            ratio=job.aspect_ratio or "",
        )
    except Exception as error:
        return await status.edit_text(
            f"⚠️ Не удалось применить правки: {type(error).__name__}. "
            "Ответь на сообщение редактирования ещё раз."
        )

    async with SessionLocal() as session:
        row = await session.get(Job, job_id)
        row.script_json = new_script.model_dump_json()
        row.plan_json = None
        row.estimated_cost = Decimal("0")
        row.status = JobStatus.WAITING_CONFIRMATION
        await session.commit()

    await status.edit_text("✅ Правки применены. Вот обновлённый сценарий:")
    await _show_storyboard(message, job_id, new_script)


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
