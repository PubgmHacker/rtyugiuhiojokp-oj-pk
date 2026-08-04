"""убрать мёртвую схему: swipe_sessions и profile.verification_status

Revision ID: e6c9a2d13f58
Revises: d5b8f1c02e47
Create Date: 2026-08-04 12:20:00.000000

Обе сущности объявлены, но ни один роутер, сервис или хендлер их не читает
и не пишет:

- `dating_swipe_sessions` — таблица под серверную память просмотренных анкет,
  которая так и не понадобилась: дека отсеивает виденное по `dating_likes`.
- `dating_profiles.verification_status` — дубль: признак верификации живёт в
  `dating_users.is_verified`, именно его отдают роутеры и показывает бейдж в
  интерфейсе. Вторая колонка со своим набором значений только путала бы
  того, кто возьмётся делать верификацию селфи.

Возврат восстанавливает и таблицу, и колонку, но не данные — их не было.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6c9a2d13f58'
down_revision: Union[str, Sequence[str], None] = 'd5b8f1c02e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('dating_swipe_sessions')
    op.drop_column('dating_profiles', 'verification_status')


def downgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('verification_status', sa.String(), nullable=False, server_default='none'),
    )
    op.create_table(
        'dating_swipe_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('viewed_ids', sa.JSON(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
