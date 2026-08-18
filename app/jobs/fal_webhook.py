from decimal import Decimal
from aiogram import Bot
from sqlalchemy import select

from app.budget.controller import CostController
from app.db.models import Job, JobStatus, Scene
from app.db.session import SessionLocal
from app.video.planner import GenerationPlan
from app.video.renderer import render_and_send

costs = CostController()


async def handle_fal_webhook(payload: dict, bot: Bot) -> dict:
    request_id = payload.get("request_id")
    status = str(payload.get("status", "")).upper()
    if not request_id:
        return {"ok": True, "ignored": "missing request_id"}

    async with SessionLocal() as session:
        scene = (await session.execute(
            select(Scene).where(Scene.request_id == request_id)
        )).scalar_one_or_none()
        if scene is None:
            return {"ok": True, "ignored": "unknown request_id"}
        scene_id = scene.id
        job_id = scene.job_id
        ledger_id = scene.ledger_id
        estimated_cost = Decimal(scene.estimated_cost or 0)
        already_done = scene.status in {"COMPLETED", "FAILED"}

    if already_done:
        return {"ok": True, "duplicate": True}

    if status == "OK":
        result = payload.get("payload") or {}
        video = result.get("video") or {}
        output_url = video.get("url")
        if not output_url:
            # A nominally successful callback without output has unknown billing state.
            # Keep the reservation locked instead of assuming the request was free.
            if ledger_id:
                await costs.quarantine(ledger_id, "OUTPUT_UNKNOWN")
            async with SessionLocal() as session:
                row = await session.get(Scene, scene_id)
                row.status = "FAILED_BILLING_UNKNOWN"
                await session.commit()
            return {"ok": True, "error": "successful webhook had no video URL"}

        # PixVerse 720p/no-audio has fixed per-generated-second billing. The reservation
        # was computed from fresh live pricing immediately before submit.
        if ledger_id:
            await costs.settle(ledger_id, estimated_cost)
        async with SessionLocal() as session:
            row = await session.get(Scene, scene_id)
            row.status = "COMPLETED"
            row.output_url = output_url
            row.actual_cost = estimated_cost
            await session.commit()
    else:
        # Failed provider callbacks are not assumed free. Preserve the reservation until
        # an administrator/provider billing check establishes the actual charge.
        if ledger_id:
            await costs.quarantine(ledger_id, "FAILED_UNKNOWN")
        async with SessionLocal() as session:
            row = await session.get(Scene, scene_id)
            row.status = "FAILED_BILLING_UNKNOWN"
            await session.commit()
        return {"ok": True, "scene": scene_id, "status": "FAILED_BILLING_UNKNOWN"}

    should_render = False
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        scenes = list((await session.execute(
            select(Scene).where(Scene.job_id == job_id)
        )).scalars())
        expected = len(GenerationPlan.model_validate_json(job.plan_json).operations) if job.plan_json else 0
        completed = sum(scene.status == "COMPLETED" for scene in scenes)
        failed = sum(
            scene.status in {"FAILED", "SUBMIT_FAILED", "SUBMIT_UNKNOWN", "FAILED_BILLING_UNKNOWN"}
            for scene in scenes
        )
        if failed:
            job.status = JobStatus.FAILED
            await session.commit()
        elif expected and completed >= expected and not job.output_storage_key and job.status != JobStatus.EDITING:
            job.status = JobStatus.EDITING
            await session.commit()
            should_render = True

    if should_render:
        try:
            await render_and_send(job_id, bot)
        except Exception:
            async with SessionLocal() as session:
                job = await session.get(Job, job_id)
                if job and not job.output_storage_key:
                    job.status = JobStatus.FAILED
                    await session.commit()
            raise

    return {"ok": True, "scene": scene_id, "status": "COMPLETED", "render": should_render}
