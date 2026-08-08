"""SQLAlchemy ORM models for kibernikto data storage."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatHistoryRow(Base):
    __tablename__ = "chat_history"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    messages: Mapped[list | None] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class ChatDataRow(Base):
    __tablename__ = "chat_data"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    data: Mapped[dict | None] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )