"""список забаненных Telegram-аккаунтов

Revision ID: f04a71bc9e35
Revises: e83c02d5b719
Create Date: 2026-08-05 12:00:00.000000

Удаление аккаунта каскадом стирало и баны, и жалобы: забаненный удалял себя,
регистрировался тем же Telegram-аккаунтом и приходил чистым. Аудит назвал это
блокером, и правильно — модерация без памяти не работает вовсе.

Храним только telegram_id и причину. Этого хватает, чтобы не пустить обратно,
и не хватает, чтобы считаться хранением персональных данных удалённого
человека: App Store требует настоящего удаления (5.1.1(v)), и профиль, фото,
переписка удаляются как раньше.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f04a71bc9e35'
down_revision: Union[str, Sequence[str], None] = 'e83c02d5b719'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_banned_identities',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False, server_default=''),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', name='uq_banned_telegram'),
    )

    # Уже забаненные попадают в список сразу: иначе правка защищает только от
    # будущих банов, а те, кого забанили до неё, вернутся при первой чистке
    op.execute(
        """
        INSERT INTO dating_banned_identities (id, telegram_id, reason)
        SELECT gen_random_uuid()::text, telegram_id, 'перенос при миграции'
        FROM dating_users
        WHERE is_banned = true AND telegram_id IS NOT NULL
        ON CONFLICT (telegram_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table('dating_banned_identities')
