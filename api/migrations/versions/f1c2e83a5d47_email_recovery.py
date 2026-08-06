"""почта для восстановления доступа

Revision ID: f1c2e83a5d47
Revises: e7a91c4f2b83
Create Date: 2026-08-06 02:40:00.000000

Единственный способ вернуться в свой аккаунт, если потерян Telegram. Без неё
вместе с Telegram теряется и оплаченная подписка — вернуть её было нечем, и
для платящего это прямая потеря денег.

Уникальность обязательна: одна почта не должна открывать два аккаунта, иначе
восстановление становится способом угона чужого.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1c2e83a5d47'
down_revision: Union[str, Sequence[str], None] = 'e7a91c4f2b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dating_users', sa.Column('email', sa.String(), nullable=True))
    op.create_unique_constraint('uq_dating_users_email', 'dating_users', ['email'])


def downgrade() -> None:
    op.drop_constraint('uq_dating_users_email', 'dating_users', type_='unique')
    op.drop_column('dating_users', 'email')
