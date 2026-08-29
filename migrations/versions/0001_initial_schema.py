"""Начальная схема: та же, что раньше создавалась через Base.metadata.create_all

Revision ID: 0001
Revises:
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # База, созданная через create_all до появления миграций, уже содержит эти таблицы.
    # Тогда ревизия просто отмечается в alembic_version, а схема не трогается —
    # иначе первый же upgrade падал бы на «relation already exists».
    # В offline-режиме (alembic upgrade --sql) подключения нет и заглядывать некуда,
    # поэтому там всегда генерируем полный DDL.
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("movies"):
        return

    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_start_date", sa.TIMESTAMP(), nullable=False),
        sa.Column("user_end_date", sa.TIMESTAMP(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "movies",
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("vote_average", sa.Float(), nullable=False),
        sa.Column("vote_count", sa.Integer(), nullable=False),
        sa.Column("popularity", sa.Float(), nullable=False),
        sa.Column("poster", sa.String(length=512), nullable=True),
        sa.Column("tmdb_poster_path", sa.String(length=512), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("genres", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("keywords", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("production_countries", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("spoken_languages", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("original_language", sa.String(length=10), nullable=True),
        sa.Column("production_companies", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("actors", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("directors", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("adult", sa.Boolean(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.PrimaryKeyConstraint("tmdb_id"),
    )

    op.create_table(
        "users_anketa",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_rec_status", sa.Boolean(), nullable=False),
        sa.Column("mood", sa.String(), nullable=False),
        sa.Column("genres", sa.String(), nullable=False),
        sa.Column("era", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("themes", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_users_anketa_user_id", "users_anketa", ["user_id"])

    op.create_table(
        "users_interaction",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("interaction_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.tmdb_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_interaction_user_id", "users_interaction", ["user_id"])
    op.create_index("ix_users_interaction_interaction_type", "users_interaction", ["interaction_type"])
    op.create_index("ix_user_interaction", "users_interaction", ["user_id", "interaction_type"])

    # HNSW строится по пустой таблице мгновенно. На заполненной это долго —
    # поэтому наполнять базу лучше уже после миграций, а не наоборот.
    op.create_index(
        "ix_movies_embedding_hnsw",
        "movies",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 200},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_movies_embedding_hnsw", table_name="movies")
    op.drop_table("users_interaction")
    op.drop_index("ix_users_anketa_user_id", table_name="users_anketa")
    op.drop_table("users_anketa")
    op.drop_table("movies")
    op.drop_table("users")
