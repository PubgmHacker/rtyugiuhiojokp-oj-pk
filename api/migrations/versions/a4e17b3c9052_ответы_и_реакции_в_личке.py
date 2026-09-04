"""ответы на сообщения и реакции в личной переписке

Revision ID: a4e17b3c9052
Revises: d7a1c4e92b58
Create Date: 2026-09-04 11:20:00.000000

Две вещи, без которых личка не читается как мессенджер: цитата («на что
именно ты отвечаешь») и реакция («прочитал, отвечать нечего»). Обе живут
рядом, потому что обе про уже отправленное сообщение.

`reply_to_id` — ссылка сообщения на сообщение, `SET NULL`: удалённая реплика
не должна утаскивать за собой ответы на неё. Индекс обязателен — без него
`SET NULL` сканирует всю переписку.

Реакции — отдельная таблица со строкой на человека и уникальностью по паре
(сообщение, человек): одна реакция на реплику, повторное нажатие снимает,
другая — заменяет. Счётчики в колонках сообщения не подошли бы: набор кодов
ещё будет меняться, и каждое изменение стало бы миграцией схемы.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4e17b3c9052'
down_revision: Union[str, Sequence[str], None] = 'd7a1c4e92b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_messages', sa.Column('reply_to_id', sa.String(), nullable=True)
    )
    op.create_foreign_key(
        'fk_dating_messages_reply',
        'dating_messages', 'dating_messages',
        ['reply_to_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_dating_messages_reply', 'dating_messages', ['reply_to_id'])

    op.create_table(
        'dating_message_reactions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('message_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('key', sa.String(length=16), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(['message_id'], ['dating_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_message_reaction_user'),
    )
    op.create_index(
        'ix_message_reaction_message', 'dating_message_reactions', ['message_id']
    )


def downgrade() -> None:
    op.drop_index('ix_message_reaction_message', table_name='dating_message_reactions')
    op.drop_table('dating_message_reactions')
    op.drop_index('ix_dating_messages_reply', table_name='dating_messages')
    op.drop_constraint('fk_dating_messages_reply', 'dating_messages', type_='foreignkey')
    op.drop_column('dating_messages', 'reply_to_id')
