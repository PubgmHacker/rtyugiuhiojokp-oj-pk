"""бонусные бусты

Revision ID: e2a91c7f40d8
Revises: c7e94a20d1b5
Create Date: 2026-08-22 12:40:00.000000

bonus_boosts в dating_profiles — включения буста, купленные паком за
Telegram Stars. Отдельный пул рядом с bonus_superlikes: суточная квота
считается по факту расхода и возобновляется сама, а купленное не сгорает.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2a91c7f40d8'
down_revision: Union[str, Sequence[str], None] = 'c7e94a20d1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `create_all` в lifespan мог создать колонку по модели раньше миграции
    inspector = sa.inspect(op.get_bind())
    колонки = {c['name'] for c in inspector.get_columns('dating_profiles')}
    if 'bonus_boosts' not in колонки:
        op.add_column(
            'dating_profiles',
            sa.Column(
                'bonus_boosts', sa.Integer(),
                server_default='0', nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column('dating_profiles', 'bonus_boosts')
