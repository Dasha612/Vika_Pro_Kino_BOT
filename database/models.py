from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column, relationship
from sqlalchemy import BigInteger, TIMESTAMP, Text, String, Float, Date, Integer, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.types import JSON
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION

# Базовый класс для всех моделей
class Base(AsyncAttrs, DeclarativeBase):
    pass

# ─────────────────────────────────────

class Users(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_start_date: Mapped[DateTime] = mapped_column(TIMESTAMP, nullable=False)
    user_end_date: Mapped[DateTime] = mapped_column(TIMESTAMP, nullable=False)

# ─────────────────────────────────────


class Movies(Base):
    __tablename__ = "movies"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    vote_average: Mapped[float] = mapped_column(Float, nullable=False)
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    popularity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    poster: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tmdb_poster_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    release_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)

    genres: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # НОВОЕ:
    production_countries: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    spoken_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    original_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    production_companies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    actors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    directors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    tagline: Mapped[str | None] = mapped_column(Text, nullable=True)
    adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # эмбеддинг
    embedding: Mapped[list[float] | None] = mapped_column(
        ARRAY(DOUBLE_PRECISION), nullable=True
    )



# ─────────────────────────────────────

class Users_anketa(Base):
    __tablename__ = "users_anketa"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), primary_key=True, index=True)
    user_rec_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mood: Mapped[str] = mapped_column(String, nullable=False)
    genres: Mapped[str] = mapped_column(String, nullable=False)
    era: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)
    themes: Mapped[str] = mapped_column(String, nullable=False)

    user: Mapped[Users] = relationship(backref="anketa")

# ─────────────────────────────────────

class Users_interaction(Base):
    __tablename__ = "users_interaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "like", "dislike", etc.

    user: Mapped[Users] = relationship(backref="interactions")
    movie: Mapped[Movies] = relationship(backref="interactions")

    __table_args__ = (
        Index("ix_user_interaction", "user_id", "interaction_type"),
    )
