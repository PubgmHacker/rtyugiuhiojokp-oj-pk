"""тонкие настройки приватности

Revision ID: d0b6f48a35c7
Revises: c9a5d72e138b
Create Date: 2026-08-04 15:20:00.000000

Приватность держалась на одном `is_incognito`, и он перегружен: тем же флагом
работают пауза аккаунта и автоскрытие по жалобам. Разделять его смыслы задним
числом рискованно, поэтому тонкие настройки — отдельные поля.

Все три по умолчанию выключены: анкета, которая после обновления вдруг
перестала показывать возраст, выглядит поломанной.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd0b6f48a35c7'
down_revision: Union[str, Sequence[str], None] = 'c9a5d72e138b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ФЛАГИ = ("hide_age", "hide_distance", "hide_from_visitors")


def upgrade() -> None:
    for имя in _ФЛАГИ:
        op.add_column(
            'dating_profiles',
            sa.Column(имя, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for имя in _ФЛАГИ:
        op.drop_column('dating_profiles', имя)
