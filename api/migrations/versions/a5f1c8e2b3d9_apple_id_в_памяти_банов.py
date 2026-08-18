"""apple_id в памяти банов

Revision ID: a5f1c8e2b3d9
Revises: a4e7c92f61bd
Create Date: 2026-08-17 12:00:00.000000

Память банов знала только telegram_id, а вход через Apple передавал в проверку
строковый apple_id: по BigInteger-колонке он не совпадал никогда — обход бана
проходил, — а на asyncpg сравнение строки с int8 роняло вход 500-й. Даём памяти
отдельную привязку apple_id и храним каждую личность своей строкой: у пришедшего
из App Store нет Telegram, у забаненного в боте — Apple.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a5f1c8e2b3d9'
down_revision: Union[str, Sequence[str], None] = 'a4e7c92f61bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_banned_identities',
        sa.Column('apple_id', sa.String(), nullable=True),
    )
    # Строка хранит ровно одну привязку — вторая пустует, поэтому telegram_id
    # больше не обязателен
    op.alter_column(
        'dating_banned_identities',
        'telegram_id',
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    # Частичный уникальный: дубли apple-банов не нужны, а строки без apple_id
    # (баны через Telegram) под ограничение не попадают
    op.create_index(
        'uq_banned_apple',
        'dating_banned_identities',
        ['apple_id'],
        unique=True,
        postgresql_where=sa.text('apple_id IS NOT NULL'),
    )

    # Уже забаненные через Apple тоже попадают в список — иначе правка ловит
    # только будущие баны, а прежние вернутся при первой чистке аккаунта
    op.execute(
        """
        INSERT INTO dating_banned_identities (id, apple_id, reason)
        SELECT gen_random_uuid()::text, apple_id, 'перенос при миграции'
        FROM dating_users
        WHERE is_banned = true AND apple_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index('uq_banned_apple', table_name='dating_banned_identities')
    # Apple-строки не переживут возврат NOT NULL на telegram_id
    op.execute("DELETE FROM dating_banned_identities WHERE telegram_id IS NULL")
    op.alter_column(
        'dating_banned_identities',
        'telegram_id',
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_column('dating_banned_identities', 'apple_id')
