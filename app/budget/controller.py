from decimal import Decimal
from sqlalchemy import text
from app.config import settings
from app.db.models import CostLedger, Job, ProjectBudget
from app.db.session import SessionLocal, engine


class BudgetExceeded(RuntimeError):
    """Raised when a reservation or settlement would exceed a hard budget limit."""


class CostController:
    async def _begin_locking(self, s):
        if engine.dialect.name == "sqlite":
            await s.connection()
            await s.execute(text("BEGIN IMMEDIATE"))

    async def reserve(self, job_id: int, operation: str, provider: str, model: str, max_cost: Decimal) -> int:
        max_cost = Decimal(max_cost)
        if max_cost <= 0 or max_cost > settings.max_job_cost_usd:
            raise BudgetExceeded("Invalid reservation amount")

        async with SessionLocal() as s:
            await self._begin_locking(s)
            lock = engine.dialect.name != "sqlite"
            job = await s.get(Job, job_id, with_for_update=lock)
            budget = await s.get(ProjectBudget, 1, with_for_update=lock)
            if job is None or budget is None:
                await s.rollback()
                raise RuntimeError("Missing job/project budget")

            job_spent = Decimal(job.actual_cost or 0)
            job_reserved = Decimal(job.reserved_cost or 0)
            global_spent = Decimal(budget.spent or 0)
            global_reserved = Decimal(budget.reserved or 0)

            if job_spent + job_reserved + max_cost > settings.max_job_cost_usd:
                await s.rollback()
                raise BudgetExceeded("Per-job $5.00 hard limit")
            if global_spent + global_reserved + max_cost > Decimal(budget.limit):
                await s.rollback()
                raise BudgetExceeded("Global project budget exceeded")

            job.reserved_cost = job_reserved + max_cost
            budget.reserved = global_reserved + max_cost
            row = CostLedger(
                job_id=job_id, operation=operation, provider=provider, model=model,
                estimated_max_cost=max_cost, reserved_cost=max_cost, status="RESERVED"
            )
            s.add(row)
            await s.flush()
            ledger_id = row.id
            await s.commit()
            return ledger_id

    async def settle(self, ledger_id: int, actual_cost: Decimal):
        actual_cost = Decimal(actual_cost)
        async with SessionLocal() as s:
            await self._begin_locking(s)
            lock = engine.dialect.name != "sqlite"
            row = await s.get(CostLedger, ledger_id, with_for_update=lock)
            if row is None:
                await s.rollback()
                raise RuntimeError("Unknown ledger entry")
            if row.status == "SETTLED":
                await s.rollback()
                return
            job = await s.get(Job, row.job_id, with_for_update=lock)
            budget = await s.get(ProjectBudget, 1, with_for_update=lock)
            reserved = Decimal(row.reserved_cost or 0)
            if actual_cost < 0 or actual_cost > reserved:
                await s.rollback()
                raise BudgetExceeded("Actual cost exceeds reservation")
            if Decimal(job.actual_cost or 0) + actual_cost > settings.max_job_cost_usd:
                await s.rollback()
                raise BudgetExceeded("Settlement would exceed per-job hard limit")
            if Decimal(budget.spent or 0) + actual_cost > Decimal(budget.limit):
                await s.rollback()
                raise BudgetExceeded("Settlement would exceed global hard limit")

            job.reserved_cost = Decimal(job.reserved_cost or 0) - reserved
            budget.reserved = Decimal(budget.reserved or 0) - reserved
            job.actual_cost = Decimal(job.actual_cost or 0) + actual_cost
            budget.spent = Decimal(budget.spent or 0) + actual_cost
            row.actual_cost = actual_cost
            row.reserved_cost = Decimal("0")
            row.status = "SETTLED"
            await s.commit()

    async def quarantine(self, ledger_id: int, status: str = "UNKNOWN_BILLING"):
        """Keep the full reservation locked when provider billing is uncertain.

        This is intentionally conservative: an unknown network/provider failure must never
        make money available for another paid call until billing is reconciled.
        """
        async with SessionLocal() as s:
            await self._begin_locking(s)
            lock = engine.dialect.name != "sqlite"
            row = await s.get(CostLedger, ledger_id, with_for_update=lock)
            if row is None or row.status == "SETTLED":
                await s.rollback()
                return
            if Decimal(row.reserved_cost or 0) <= 0:
                await s.rollback()
                return
            row.status = status[:32]
            await s.commit()

    async def release(self, ledger_id: int):
        async with SessionLocal() as s:
            await self._begin_locking(s)
            lock = engine.dialect.name != "sqlite"
            row = await s.get(CostLedger, ledger_id, with_for_update=lock)
            if row is None or row.status != "RESERVED":
                await s.rollback()
                return
            if row.status == "SETTLED":
                await s.rollback()
                return
            job = await s.get(Job, row.job_id, with_for_update=lock)
            budget = await s.get(ProjectBudget, 1, with_for_update=lock)
            reserved = Decimal(row.reserved_cost or 0)
            job.reserved_cost = max(Decimal("0"), Decimal(job.reserved_cost or 0) - reserved)
            budget.reserved = max(Decimal("0"), Decimal(budget.reserved or 0) - reserved)
            row.reserved_cost = Decimal("0")
            row.status = "RELEASED"
            await s.commit()

    async def snapshot(self):
        async with SessionLocal() as s:
            b = await s.get(ProjectBudget, 1)
            if b is None:
                return {"limit": settings.global_project_budget_usd, "spent": Decimal(0), "reserved": Decimal(0), "available": settings.global_project_budget_usd}
            return {
                "limit": Decimal(b.limit),
                "spent": Decimal(b.spent),
                "reserved": Decimal(b.reserved),
                "available": Decimal(b.limit) - Decimal(b.spent) - Decimal(b.reserved),
            }
