"""категория нарушения в журнале модерации

Revision ID: f4c9d17a3e52
Revises: d8e2a47f19c3
Create Date: 2026-08-21 18:00:00.000000

Журнал модерации становится источником счёта страйков: «нарушение N из M»
считается по blocked-записям пользователя. Но правила разные — за рекламу
банят с третьего раза, за оскорбления с пятого, за наркотики со второго —
и без категории эти счётчики слились бы в один. Отдельная таблица страйков
не нужна: запись о нарушении уже есть, ей не хватает только категории.

server_default '' — старые строки журнала написаны до категорий; при счёте
страйков они не совпадают ни с одной категорией и не считаются: наказание
задним числом за докатегорийные записи было бы несправедливым.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4c9d17a3e52'
down_revision: Union[str, Sequence[str], None] = 'd8e2a47f19c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_ai_moderation_logs',
        sa.Column('category', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('dating_ai_moderation_logs', 'category')
