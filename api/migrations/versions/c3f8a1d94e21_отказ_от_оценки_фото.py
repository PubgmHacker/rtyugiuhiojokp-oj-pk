"""отказ от оценки фото

Revision ID: c3f8a1d94e21
Revises: b8e12f4a97c3
Create Date: 2026-08-31 12:00:00.000000

Оценки фото становятся видимыми: владелец видит, кто и сколько поставил
(у конкурента — только средняя без имён). Открытость симметрична, и колонка
хранит ровно этот выход: hide_from_ratings=True — человек не появляется
в чужой очереди оценки и сам ставить оценки не может. Дефолт False —
участие по умолчанию, как у всех.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d94e21'
down_revision: Union[str, Sequence[str], None] = 'b8e12f4a97c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('hide_from_ratings', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('dating_profiles', 'hide_from_ratings')
