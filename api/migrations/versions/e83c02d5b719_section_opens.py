"""учёт открытий разделов

Revision ID: e83c02d5b719
Revises: d61f97a4e208
Create Date: 2026-08-05 10:00:00.000000

Разделов много, и спор «эта фича нужна или лишняя» бесконечен, пока нет данных:
каждый судит по себе. Здесь копится ровно то, что нужно для решения — кто и
какой раздел открывал.

Одна строка на пару «человек + раздел» с обновлением счётчика, а не журнал
каждого тапа: журнал стал бы самой большой таблицей в базе, а для ответа
«сколько людей вообще заходит в кейсы» нужны уникальные посетители, не тапы.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e83c02d5b719'
down_revision: Union[str, Sequence[str], None] = 'd61f97a4e208'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_section_opens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('section', sa.String(), nullable=False),
        sa.Column('opens', sa.Integer(), nullable=False, server_default='1'),
        sa.Column(
            'last_open_at',
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
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'section', name='uq_section_open'),
    )
    op.create_index('ix_section_open_section', 'dating_section_opens', ['section'])


def downgrade() -> None:
    op.drop_index('ix_section_open_section', table_name='dating_section_opens')
    op.drop_table('dating_section_opens')
