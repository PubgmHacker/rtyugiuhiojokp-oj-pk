"""вход через Sign in with Apple

Revision ID: e7a91c4f2b83
Revises: c3f8b2071e4d
Create Date: 2026-08-06 01:30:00.000000

App Store требует Sign in with Apple там, где вход идёт через сторонний сервис
(Guideline 4.8). У пришедшего из App Store человека Telegram может не быть
вовсе, поэтому `telegram_id` и `apple_id` оба nullable — но хотя бы одно из них
у пользователя есть, иначе войти он не мог.

Уникальность обязательна: без неё повторный вход тем же Apple ID создавал бы
второй аккаунт вместо возврата в свой.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7a91c4f2b83'
down_revision: Union[str, Sequence[str], None] = 'c3f8b2071e4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dating_users', sa.Column('apple_id', sa.String(), nullable=True))
    op.create_unique_constraint('uq_dating_users_apple_id', 'dating_users', ['apple_id'])


def downgrade() -> None:
    op.drop_constraint('uq_dating_users_apple_id', 'dating_users', type_='unique')
    op.drop_column('dating_users', 'apple_id')
