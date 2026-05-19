"""Modelos de base de datos."""

import uuid
import datetime as dt
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    picture_url: Mapped[str] = mapped_column(String(512), default="")
    provider: Mapped[str] = mapped_column(String(20))  # "google" o "github"
    provider_id: Mapped[str] = mapped_column(String(255))  # id en Google/GitHub
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relaciones
    subscription: Mapped["Subscription"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    memories: Mapped[list["Memory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chats: Mapped[list["ChatTurn"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_user_provider_id", "provider", "provider_id"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free, pro, premium
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, cancelled, past_due, trialing
    stripe_customer_id: Mapped[str] = mapped_column(String(255), default="")
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), default="")
    trial_ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="subscription")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), default="general")
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="memories")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # alta, normal, baja
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="tasks")


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_text: Mapped[str] = mapped_column(Text)
    jarvis_text: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="chats")


class InboxItem(Base):
    """Inbox de tareas async: el usuario las manda desde móvil/web y el companion
    las lee cuando arranca. Como un buzón entre dispositivos del mismo usuario."""
    __tablename__ = "inbox_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Lo que pidió el usuario
    prompt: Mapped[str] = mapped_column(Text)
    # Resultado del LLM (vacío hasta que el worker lo procesa)
    response: Mapped[str] = mapped_column(Text, default="")
    # Herramientas usadas durante el procesamiento
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    # Estado: pending → processing → ready → read (o failed)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # De dónde vino: mobile_web, desktop, api
    source: Mapped[str] = mapped_column(String(20), default="mobile_web")
    # Título corto para mostrar en lista (auto-generado del prompt)
    title: Mapped[str] = mapped_column(String(120), default="")
    # Error si falló
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BriefingConfig(Base):
    __tablename__ = "briefing_configs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    time: Mapped[str] = mapped_column(String(5), default="08:00")  # "HH:MM"
    timezone: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    last_fired_date: Mapped[str] = mapped_column(String(10), default="")  # "YYYY-MM-DD"
