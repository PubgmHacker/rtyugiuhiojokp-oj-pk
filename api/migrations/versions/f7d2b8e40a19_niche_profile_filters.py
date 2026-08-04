"""нишевые поля анкеты и фильтры по ним

Revision ID: f7d2b8e40a19
Revises: e6c9a2d13f58
Create Date: 2026-08-04 12:45:00.000000

Пол, возраст и расстояние у нас фильтровались и раньше. Не хватало того, по
чему люди на самом деле ищут «своих»: цель знакомства, субкультура, рост и
город.

Пустая строка везде означает «не указано», а не «искать пустое»: анкета без
субкультуры должна показываться всем, и наоборот — выключенный фильтр не
должен сужать выдачу. Поэтому колонки NOT NULL со значением по умолчанию '',
а рост nullable: ноль сантиметров — не «не указан», а ерунда.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7d2b8e40a19'
down_revision: Union[str, Sequence[str], None] = 'e6c9a2d13f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_СТРОКОВЫЕ = (
    'goal',
    'subculture',
    'filter_goal',
    'filter_subculture',
    'filter_city',
)
_ЧИСЛОВЫЕ = ('height_cm', 'filter_height_min', 'filter_height_max')


def upgrade() -> None:
    for имя in _СТРОКОВЫЕ:
        op.add_column(
            'dating_profiles',
            sa.Column(имя, sa.String(), nullable=False, server_default=''),
        )
    for имя in _ЧИСЛОВЫЕ:
        op.add_column('dating_profiles', sa.Column(имя, sa.Integer(), nullable=True))

    # Частичный индекс: подавляющее большинство анкет субкультуру не укажет,
    # и держать их в индексе незачем — искать будут по заполненным.
    op.create_index(
        'ix_profile_subculture',
        'dating_profiles',
        ['subculture'],
        postgresql_where=sa.text("subculture <> ''"),
    )
    op.create_index(
        'ix_profile_goal',
        'dating_profiles',
        ['goal'],
        postgresql_where=sa.text("goal <> ''"),
    )


def downgrade() -> None:
    op.drop_index('ix_profile_goal', table_name='dating_profiles')
    op.drop_index('ix_profile_subculture', table_name='dating_profiles')
    for имя in _ЧИСЛОВЫЕ + _СТРОКОВЫЕ:
        op.drop_column('dating_profiles', имя)
