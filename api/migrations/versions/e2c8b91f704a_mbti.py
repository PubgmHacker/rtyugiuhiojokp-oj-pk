"""тип личности MBTI в анкете

Revision ID: e2c8b91f704a
Revises: d0b6f48a35c7
Create Date: 2026-08-04 15:50:00.000000

Ещё одно поле для подбора «своих»: аудитория, ради которой заводились
субкультуры, MBTI знает и ищет по нему.

Фильтра по MBTI намеренно нет: шестнадцать типов сузили бы выдачу так, что
в небольшом городе не осталось бы никого. Поле показываем в карточке — этого
достаточно, чтобы оно работало как повод для разговора.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2c8b91f704a'
down_revision: Union[str, Sequence[str], None] = 'd0b6f48a35c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('mbti', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('dating_profiles', 'mbti')
