"""визиты в анкету — раздел «Гости»

Revision ID: b8f3e91c204d
Revises: a1e4c73b0d26
Create Date: 2026-08-04 14:10:00.000000

Одна строка на пару «гость + хозяин» с обновлением времени, а не журнал всех
заходов: анкету можно открыть десятки раз за вечер, и полный журнал распухал
бы без пользы — в разделе показывается «кто заходил», а не «сколько раз»
подряд.

Уникальный ключ по паре нужен не только от дублей: по нему работает UPSERT,
которым визит и создаётся, и обновляется одним запросом.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8f3e91c204d'
down_revision: Union[str, Sequence[str], None] = 'a1e4c73b0d26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_profile_visits',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('visitor_id', sa.String(), nullable=False),
        sa.Column('host_id', sa.String(), nullable=False),
        sa.Column('visits', sa.Integer(), nullable=False, server_default='1'),
        sa.Column(
            'last_seen_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['visitor_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['host_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('visitor_id', 'host_id', name='uq_visit_pair'),
    )
    # Раздел читает свои визиты по host_id, свежие сверху
    op.create_index(
        'ix_visit_host_seen', 'dating_profile_visits', ['host_id', 'last_seen_at']
    )


def downgrade() -> None:
    op.drop_index('ix_visit_host_seen', table_name='dating_profile_visits')
    op.drop_table('dating_profile_visits')
