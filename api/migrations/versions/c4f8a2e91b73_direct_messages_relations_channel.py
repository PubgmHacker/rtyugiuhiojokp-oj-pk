"""личка без мэтча, тип связи и телеграм-канал в анкете

Revision ID: c4f8a2e91b73
Revises: b8e4c19d3a72
Create Date: 2026-08-06 06:20:00.000000

Три вещи разом, потому что все три — колонки к существующим таблицам, и
дробить их на три прохода по прод-базе смысла нет.

**Личка без взаимного мэтча** живёт полями `dating_matches`, а не отдельной
таблицей беседы. Чат, сообщения, доставка, пуши, жалобы, блокировки и удаление
аккаунта уже завязаны на `match_id`; вторая таблица означала бы вторую копию
всего этого, а в этом проекте парные пути расходятся регулярно.

`kind` заполняется значением 'match' для всех существующих строк: беседы,
созданные до этой миграции, все возникли из взаимного лайка.

`initiator_id` — nullable и с индексом. Индекс нужен дважды: по нему считается
суточный лимит платных писем, и без него `ON DELETE CASCADE` при удалении
пользователя сканировал бы таблицу мэтчей целиком.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4f8a2e91b73'
down_revision: Union[str, Sequence[str], None] = 'b8e4c19d3a72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Личка без мэтча ──────────────────────────────────────────
    op.add_column(
        'dating_matches',
        sa.Column('kind', sa.String(), nullable=False, server_default='match'),
    )
    op.add_column(
        'dating_matches',
        sa.Column('initiator_id', sa.String(), nullable=True),
    )
    op.add_column(
        'dating_matches',
        sa.Column(
            'direct_answered', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_foreign_key(
        'fk_match_initiator', 'dating_matches', 'dating_users',
        ['initiator_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(
        'ix_match_initiator_created', 'dating_matches', ['initiator_id', 'created_at'],
    )

    # ── Анкета: тип связи, фильтр по нему, телеграм-канал ────────
    op.add_column(
        'dating_profiles',
        sa.Column('relation_type', sa.String(), nullable=False, server_default=''),
    )
    op.add_column(
        'dating_profiles',
        sa.Column(
            'filter_relation_type', sa.String(), nullable=False, server_default=''
        ),
    )
    op.add_column(
        'dating_profiles',
        sa.Column('tg_channel', sa.String(), nullable=False, server_default=''),
    )
    # Частичный индекс: фильтр по типу связи отсекает по непустому значению, а
    # пустых («не указано») в таблице большинство — полный индекс был бы
    # заметно толще без выигрыша.
    op.create_index(
        'ix_profile_relation_type', 'dating_profiles', ['relation_type'],
        postgresql_where=sa.text("relation_type <> ''"),
    )


def downgrade() -> None:
    op.drop_index('ix_profile_relation_type', table_name='dating_profiles')
    op.drop_column('dating_profiles', 'tg_channel')
    op.drop_column('dating_profiles', 'filter_relation_type')
    op.drop_column('dating_profiles', 'relation_type')

    op.drop_index('ix_match_initiator_created', table_name='dating_matches')
    op.drop_constraint('fk_match_initiator', 'dating_matches', type_='foreignkey')
    op.drop_column('dating_matches', 'direct_answered')
    op.drop_column('dating_matches', 'initiator_id')
    op.drop_column('dating_matches', 'kind')
