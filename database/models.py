from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column, relationship
from sqlalchemy import BigInteger, DATETIME, Text, String, Float, Integer, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.ext.asyncio import AsyncAttrs


# Базовый класс для всех моделей
class Base(AsyncAttrs, DeclarativeBase):
    pass

# ─────────────────────────────────────

class Users(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_start_date: Mapped[DateTime] = mapped_column(DATETIME, nullable=False)
    user_end_date: Mapped[DateTime] = mapped_column(DATETIME, nullable=False)

# ─────────────────────────────────────

class Movies(Base):
    __tablename__ = "movies"

    imdb: Mapped[str] = mapped_column(String, primary_key=True)
    movie_name: Mapped[str] = mapped_column(String, nullable=False)
    movie_description: Mapped[str] = mapped_column(Text, nullable=False)
    movie_rating: Mapped[float] = mapped_column(Float, nullable=False)
    movie_poster: Mapped[str] = mapped_column(String, nullable=False)
    movie_year: Mapped[int] = mapped_column(Integer, nullable=False)
    movie_genre: Mapped[str] = mapped_column(String, nullable=False)
    movie_duration: Mapped[int] = mapped_column(Integer, nullable=False)





# ─────────────────────────────────────

class Users_anketa(Base):
    __tablename__ = "users_anketa"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), primary_key=True, index=True)
    user_rec_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ans1: Mapped[str] = mapped_column(String, nullable=False)
    ans2: Mapped[str] = mapped_column(String, nullable=False)
    ans3: Mapped[str] = mapped_column(String, nullable=False)
    ans4: Mapped[str] = mapped_column(String, nullable=False)
    ans5: Mapped[str] = mapped_column(String, nullable=False)
    ans6: Mapped[str] = mapped_column(String, nullable=False)
    ans7: Mapped[str] = mapped_column(String, nullable=False)

    user: Mapped[Users] = relationship(backref="anketa")

# ─────────────────────────────────────

class Users_interaction(Base):
    __tablename__ = "users_interaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), index=True)
    movie_id: Mapped[str] = mapped_column(String, ForeignKey("movies.imdb"), index=True)
    interaction_type: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "like", "dislike", etc.

    user: Mapped[Users] = relationship(backref="interactions")
    movie: Mapped[Movies] = relationship(backref="interactions")

    __table_args__ = (
        Index("ix_user_interaction", "user_id", "interaction_type"),
    )
