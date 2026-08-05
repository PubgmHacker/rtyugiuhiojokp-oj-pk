"""пауза аккаунта отдельно от платного инкогнито

Revision ID: a17e3d05f8c2
Revises: f04a71bc9e35
Create Date: 2026-08-05 13:30:00.000000

Пауза и инкогнито делили одно поле `is_incognito`, потому что из деки убирают
оба. Аудит показал, к чему это привело: команда `/pause` в боте бесплатно
включала то, что в мини-аппе стоит 149 руб и требует Plus.

Смыслы разные. Инкогнито — платная функция («вас видят только те, кого лайкнули
вы»). Пауза — базовое право уйти из поиска, и брать за него деньги нельзя:
человек, которому нужно исчезнуть, не должен для этого платить.

Существующие значения переносим в паузу, а не в инкогнито: тех, кто уже
скрылся, нельзя молча вернуть в выдачу, а вот отобрать у них платную функцию,
за которую они не платили, — можно.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a17e3d05f8c2'
down_revision: Union[str, Sequence[str], None] = 'f04a71bc9e35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('is_paused', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Кто уже скрыт — считаем на паузе: вернуть их в выдачу без спроса нельзя.
    # Инкогнито при этом снимаем: платную функцию получали и те, кто не платил
    op.execute(
        """
        UPDATE dating_profiles
        SET is_paused = true, is_incognito = false
        WHERE is_incognito = true
        """
    )

    # Частичный индекс деки пересоздаём: выборка теперь фильтрует и по паузе,
    # а индекс с прежним условием она бы просто не использовала
    op.drop_index('ix_profile_sample', table_name='dating_profiles')
    op.create_index(
        'ix_profile_sample',
        'dating_profiles',
        ['sample_key'],
        postgresql_where=sa.text(
            "NOT is_incognito AND NOT is_paused AND display_name <> ''"
        ),
    )


def downgrade() -> None:
    op.drop_index('ix_profile_sample', table_name='dating_profiles')
    op.create_index(
        'ix_profile_sample',
        'dating_profiles',
        ['sample_key'],
        postgresql_where=sa.text("NOT is_incognito AND display_name <> ''"),
    )

    # Возвращаем прежнее поведение: пауза снова становится инкогнито
    op.execute(
        "UPDATE dating_profiles SET is_incognito = true WHERE is_paused = true"
    )
    op.drop_column('dating_profiles', 'is_paused')
