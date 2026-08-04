"""blocks, processed payments, hot-path indexes

Revision ID: b2f1c47ade90
Revises: 48debbfc3b80
Create Date: 2026-08-04 06:10:00.000000

Три независимых изменения, объединённые в одну ревизию, потому что все
относятся к одному релизу:

1. `dating_blocks` — постоянная блокировка пользователя. Размэтч удаляет
   лайки, но не мешает паре снова увидеть друг друга в деке; App Store
   Guideline 1.2 требует именно необратимого запрета контакта.
2. `dating_processed_payments` — журнал зачтённых платежей. Уникальный ключ
   (provider, external_id) — единственная надёжная защита от повторного
   начисления премиума по одному и тому же оплаченному инвойсу.
3. Индексы под горячие запросы. Изначальная схема не создавала ни одного
   индекса кроме PK и unique-констрейнтов, из-за чего выборка деки, история
   переписки и подсчёт жалоб шли последовательным сканированием таблиц.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2f1c47ade90'
down_revision: Union[str, Sequence[str], None] = '48debbfc3b80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_blocks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('blocker_id', sa.String(), nullable=False),
        sa.Column('blocked_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['blocker_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['blocked_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blocker_id', 'blocked_id', name='uq_block_pair'),
    )
    op.create_index('ix_block_blocker', 'dating_blocks', ['blocker_id'])
    op.create_index('ix_block_blocked', 'dating_blocks', ['blocked_id'])

    op.create_table(
        'dating_processed_payments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'external_id', name='uq_payment_external'),
    )

    # Дека собирает исключения по liker_id, «кто меня лайкнул» — по liked_id
    op.create_index('ix_like_liker', 'dating_likes', ['liker_id'])
    op.create_index('ix_like_liked', 'dating_likes', ['liked_id'])
    # Список чатов ищет мэтчи пользователя с любой стороны нормализованной пары
    op.create_index('ix_match_user1', 'dating_matches', ['user1_id'])
    op.create_index('ix_match_user2', 'dating_matches', ['user2_id'])
    # История переписки: выборка по мэтчу с сортировкой по времени
    op.create_index('ix_message_match_created', 'dating_messages', ['match_id', 'created_at'])
    # Эскалация жалоб считает разных жалобщиков по одной цели
    op.create_index('ix_report_reported', 'dating_reports', ['reported_id'])


def downgrade() -> None:
    op.drop_index('ix_report_reported', table_name='dating_reports')
    op.drop_index('ix_message_match_created', table_name='dating_messages')
    op.drop_index('ix_match_user2', table_name='dating_matches')
    op.drop_index('ix_match_user1', table_name='dating_matches')
    op.drop_index('ix_like_liked', table_name='dating_likes')
    op.drop_index('ix_like_liker', table_name='dating_likes')

    op.drop_table('dating_processed_payments')

    op.drop_index('ix_block_blocked', table_name='dating_blocks')
    op.drop_index('ix_block_blocker', table_name='dating_blocks')
    op.drop_table('dating_blocks')
