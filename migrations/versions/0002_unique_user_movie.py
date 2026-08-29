"""Уникальность пары (user_id, movie_id) в users_interaction

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Констрейнт не встанет, пока в таблице есть дубли, а они там почти наверняка
    # есть: до этой миграции add_movies_by_interaction делал read-then-write без
    # защиты от гонки. Оставляем самую свежую строку по каждой паре — у неё
    # наибольший id, то есть последнее действие пользователя.
    op.execute(
        """
        DELETE FROM users_interaction a
        USING users_interaction b
        WHERE a.user_id = b.user_id
          AND a.movie_id = b.movie_id
          AND a.id < b.id
        """
    )

    op.create_unique_constraint(
        "uq_user_movie", "users_interaction", ["user_id", "movie_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_movie", "users_interaction", type_="unique")
