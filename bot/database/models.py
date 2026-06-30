from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)
from sqlalchemy.dialects.postgresql import JSON


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "dating_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="user")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Profile(Base):
    __tablename__ = "dating_profiles"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    bio: Mapped[str] = mapped_column(String, default="")
    gender: Mapped[str] = mapped_column(String, default="other")
    birth_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    city: Mapped[str] = mapped_column(String, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    photos: Mapped[dict | list] = mapped_column(JSON, default=list)
    interests: Mapped[dict | list] = mapped_column(JSON, default=list)
    ai_bio: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_status: Mapped[str] = mapped_column(String, default="none")
    is_incognito: Mapped[bool] = mapped_column(Boolean, default=False)
    looking_for: Mapped[str] = mapped_column(String, default="any")
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=99)
    distance_max: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Like(Base):
    __tablename__ = "dating_likes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    liker_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    liked_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String, default="like")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    __tablename__ = "dating_matches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user1_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    user2_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "dating_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[str] = mapped_column(String, ForeignKey("dating_matches.id", ondelete="CASCADE"))
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("dating_users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
