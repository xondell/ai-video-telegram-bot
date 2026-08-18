from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from .models import Base, ProjectBudget


_kwargs = {"future": True}

if settings.async_database_url.startswith("postgresql+"):
    # Vercel/serverless: don't maintain an application-side connection pool.
    _kwargs["poolclass"] = NullPool

    # Supabase Transaction Pooler (:6543) doesn't support normal
    # prepared-statement behaviour. Psycopg 3 lets us disable it.
    _kwargs["connect_args"] = {
        "sslmode": "require",
        "prepare_threshold": None,
    }

engine = create_async_engine(
    settings.async_database_url,
    **_kwargs,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def init_db():
    # Local/dev convenience only.
    # Production Supabase uses the SQL migration.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        if await session.get(ProjectBudget, 1) is None:
            session.add(
                ProjectBudget(
                    id=1,
                    limit=settings.global_project_budget_usd,
                )
            )
            await session.commit()
