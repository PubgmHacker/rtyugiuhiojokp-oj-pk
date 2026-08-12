"""схема оформления приложения в анкете

Revision ID: f4c92a71de60
Revises: e7b1c4d92f38
Create Date: 2026-08-11 10:02:44.310827

Настройка хранится на сервере, а не в localStorage: внешний вид,
пропадающий при переустановке приложения, читается как потеря данных.
Пустая строка — базовая схема, поэтому nullable здесь не нужен.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4c92a71de60'
down_revision: Union[str, Sequence[str], None] = 'e7b1c4d92f38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('app_theme', sa.String(), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('dating_profiles', 'app_theme')
