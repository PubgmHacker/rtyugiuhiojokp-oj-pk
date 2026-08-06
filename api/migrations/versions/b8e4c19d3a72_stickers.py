"""коллекционные наклейки из кейсов

Revision ID: b8e4c19d3a72
Revises: a3d5f27b91c4
Create Date: 2026-08-06 04:10:00.000000

Из кейса выпадали только суперлайки и минуты буста: их тратят и забывают, и
повода открыть кейс завтра не оставалось. Наклейка остаётся навсегда и видна в
анкете — у кейса появляется второй смысл, собрать набор.

Дубликаты не хранятся отдельными строками: уникальный ключ (user_id, code) плюс
счётчик. Иначе таблица растёт линейно от числа открытий, а показать надо один
значок с числом.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e4c19d3a72'
down_revision: Union[str, Sequence[str], None] = 'a3d5f27b91c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_stickers_owned',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'code', name='uq_sticker_owner'),
    )
    op.create_index('ix_sticker_user', 'dating_stickers_owned', ['user_id'])

    # Выбранная наклейка — та единственная, которую видят другие
    op.add_column('dating_profiles', sa.Column('sticker', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('dating_profiles', 'sticker')
    op.drop_index('ix_sticker_user', table_name='dating_stickers_owned')
    op.drop_table('dating_stickers_owned')
