import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class JobStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    ANALYZING = "ANALYZING"
    SCRIPTING = "SCRIPTING"
    WAITING_SETTINGS = "WAITING_SETTINGS"
    PLANNING = "PLANNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    GENERATING = "GENERATING"
    EDITING = "EDITING"
    EXPORTING = "EXPORTING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False, length=32), default=JobStatus.UPLOADED)
    source_audio_path: Mapped[str] = mapped_column(Text)
    source_audio_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    style: Mapped[str | None] = mapped_column(String(128), nullable=True)
    intensity: Mapped[str] = mapped_column(String(32), default="balanced")
    subtitle_style: Mapped[str] = mapped_column(String(32), default="dynamic")
    music_style: Mapped[str] = mapped_column(String(32), default="none")
    selected_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    selected_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transcript_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Scene(Base):
    __tablename__ = "scenes"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    scene_index: Mapped[int] = mapped_column()
    duration_seconds: Mapped[int] = mapped_column()
    importance: Mapped[float] = mapped_column(default=0.5)
    provider: Mapped[str] = mapped_column(String(32), default="fal")
    model: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    ledger_id: Mapped[int | None] = mapped_column(ForeignKey("cost_ledger.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PLANNED")
    output_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("job_id", "scene_index", name="uq_job_scene"),)


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(255))
    estimated_max_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(32), default="RESERVED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectBudget(Base):
    __tablename__ = "project_budget"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    spent: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    limit: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=10)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
