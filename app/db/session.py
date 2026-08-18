from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.config import settings
from .models import Base, ProjectBudget

_kwargs = {"future": True}
if settings.async_database_url.startswith("postgresql+"):
    _kwargs["poolclass"] = NullPool
    _kwargs["connect_args"] = {"ssl": "require"}
engine = create_async_engine(settings.async_database_url, **_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    # Local/dev convenience only. Production Supabase should use the SQL migration.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        if await s.get(ProjectBudget, 1) is None:
            s.add(ProjectBudget(id=1, limit=settings.global_project_budget_usd))
            await s.commit()
