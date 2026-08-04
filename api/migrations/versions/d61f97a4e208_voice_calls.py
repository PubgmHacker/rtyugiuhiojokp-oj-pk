"""журнал звонков голосовой рулетки

Revision ID: d61f97a4e208
Revises: c5b28f01a473
Create Date: 2026-08-04 19:00:00.000000

Записи разговора нет и быть не должно. Журнал нужен ради жалоб: пожаловавшийся
на голос даже не знает имени собеседника, и без пары «кто с кем» разобрать
такую жалобу невозможно.

Длительность пишется при разрыве — до него она неизвестна. Ноль означает, что
соединение так и не собралось.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd61f97a4e208'
down_revision: Union[str, Sequence[str], None] = 'c5b28f01a473'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_voice_calls',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('caller_id', sa.String(), nullable=False),
        sa.Column('callee_id', sa.String(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['caller_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['callee_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_voice_call_created', 'dating_voice_calls', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_voice_call_created', table_name='dating_voice_calls')
    op.drop_table('dating_voice_calls')
