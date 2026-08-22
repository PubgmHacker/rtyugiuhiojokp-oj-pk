"""Опорное фото верификации в анкете.

`dating_profiles.verified_photo` — URL фотографии анкеты, с которой совпало
лицо на живой проверке. По нему после верификации сверяются новые фото
(чужие снимки в подтверждённую анкету не попадают), а его удаление из анкеты
снимает галочку. Биометрии здесь нет: это ссылка на уже публичное фото.

Revision ID: c7e19a4d82f5
Revises: a2d84c19f3e7
Create Date: 2026-08-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e19a4d82f5"
down_revision: Union[str, Sequence[str], None] = "a2d84c19f3e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default нужен существующим строкам: колонка NOT NULL, а анкеты
    # уже есть. «Пустая строка» и означает «проверки не было».
    op.add_column(
        "dating_profiles",
        sa.Column("verified_photo", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("dating_profiles", "verified_photo")
