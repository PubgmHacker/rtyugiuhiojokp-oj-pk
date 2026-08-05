"""пересыл ролика в личный чат и в комнату

Revision ID: c3f8b2071e4d
Revises: b52c8fa0d391
Create Date: 2026-08-05 17:00:00.000000

Ролик хочется показать конкретному человеку или в общий чат — без этого лента
замкнута сама на себя. Репост наружу в Telegram Mini App смысла не имеет:
ссылку всё равно откроют внутри Telegram, поэтому пересылаем внутри сервиса.

`SET NULL`, а не `CASCADE`: если автор удалит ролик, сообщение остаётся в
переписке, просто превью пропадает. Вырезать чужую реплику из истории только
потому, что видео удалили, неправильно — люди помнят, о чём говорили.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8b2071e4d'
down_revision: Union[str, Sequence[str], None] = 'b52c8fa0d391'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for таблица in ('dating_messages', 'dating_room_messages'):
        op.add_column(таблица, sa.Column('reel_id', sa.String(), nullable=True))
        op.create_foreign_key(
            f'fk_{таблица}_reel',
            таблица,
            'dating_reels',
            ['reel_id'],
            ['id'],
            ondelete='SET NULL',
        )
        # Без индекса `SET NULL` при удалении ролика заставляет Postgres
        # просканировать всю таблицу сообщений, чтобы найти ссылки на него
        op.create_index(f'ix_{таблица}_reel', таблица, ['reel_id'])


def downgrade() -> None:
    for таблица in ('dating_messages', 'dating_room_messages'):
        op.drop_index(f'ix_{таблица}_reel', table_name=таблица)
        op.drop_constraint(f'fk_{таблица}_reel', таблица, type_='foreignkey')
        op.drop_column(таблица, 'reel_id')
