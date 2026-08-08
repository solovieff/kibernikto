"""SQLAlchemy ORM models for kibernikto data storage."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatMessageRow(Base):
    """One ``ModelMessage`` per row — the canonical SQL history shape."""
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_chat_name_seq", "chat_id", "name", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False, default="default")  # agent namespace
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # "request" | "response"
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatDataRow(Base):
    __tablename__ = "chat_data"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    data: Mapped[dict | None] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
