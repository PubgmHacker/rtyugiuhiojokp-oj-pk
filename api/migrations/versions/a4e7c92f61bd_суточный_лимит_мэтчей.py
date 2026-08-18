"""суточный лимит открытых мэтчей

Revision ID: a4e7c92f61bd
Revises: d5a1b8e04c37
Create Date: 2026-08-15 21:48:03.117204
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a4e7c92f61bd'
down_revision: Union[str, Sequence[str], None] = 'd5a1b8e04c37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Отметка «этот человек открывал этот мэтч». Одна строка на пару:
    # суточный лимит стоит на РАЗНЫХ мэтчах, а повторный вход в уже открытый
    # чат обязан быть бесплатным (см. services/quotas.py).
    op.create_table(
        "dating_match_views",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("dating_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            sa.String(),
            sa.ForeignKey("dating_matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "match_id", name="uq_match_view"),
    )
    # Квота считается как «сколько разных мэтчей открыто за окно» — ровно
    # (user_id, viewed_at)
    op.create_index(
        "ix_match_view_user_seen", "dating_match_views", ["user_id", "viewed_at"]
    )
    # Нужен для FK: без него удаление мэтча сканирует таблицу просмотров целиком
    op.create_index("ix_match_view_match", "dating_match_views", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_match_view_match", table_name="dating_match_views")
    op.drop_index("ix_match_view_user_seen", table_name="dating_match_views")
    op.drop_table("dating_match_views")
