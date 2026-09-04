"""голосовые сообщения и видеокружки в личке

Revision ID: d7a1c4e92b58
Revises: c3f8a1d94e21
Create Date: 2026-09-03 18:10:00.000000

Голосовое или видеокружок — это файл в нашем R2 плюс то, чего у картинки
нет: длительность, форма кружка и волна голоса. В text ничего из этого не
кладём: превью списка чатов и уведомления собираются по media_kind, а
клиент рисует пузырь по остальным полям без декодирования файла.

Все колонки nullable: старые сообщения — текст и картинки — остаются как
были, и бот, который медиа не создаёт, пишет строки без них.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd7a1c4e92b58'
down_revision: Union[str, Sequence[str], None] = 'c3f8a1d94e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('dating_messages') as batch:
        batch.add_column(sa.Column('media_url', sa.String(), nullable=True))
        batch.add_column(sa.Column('media_kind', sa.String(length=16), nullable=True))
        batch.add_column(sa.Column('media_duration', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('media_shape', sa.String(length=16), nullable=True))
        batch.add_column(sa.Column('media_waveform', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('media_poster_url', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('dating_messages') as batch:
        batch.drop_column('media_poster_url')
        batch.drop_column('media_waveform')
        batch.drop_column('media_shape')
        batch.drop_column('media_duration')
        batch.drop_column('media_kind')
        batch.drop_column('media_url')
