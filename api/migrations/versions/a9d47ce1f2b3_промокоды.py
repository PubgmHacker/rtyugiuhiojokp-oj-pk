"""промокоды

Revision ID: a9d47ce1f2b3
Revises: e2a91c7f40d8
Create Date: 2026-08-22 14:10:00.000000

dating_promo_codes + dating_promo_activations — промокоды на подписку.
Выпускает админка, активирует пользователь в боте или мини-аппе. Лимит
активаций держится на used_count/max_uses, повторная активация одним
человеком — на уникальной паре (promo_id, user_id).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9d47ce1f2b3'
down_revision: Union[str, Sequence[str], None] = 'e2a91c7f40d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `create_all` в lifespan мог создать таблицы по моделям раньше миграции
    inspector = sa.inspect(op.get_bind())
    таблицы = set(inspector.get_table_names())

    if 'dating_promo_codes' not in таблицы:
        op.create_table(
            'dating_promo_codes',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.Column('tier', sa.String(), nullable=False),
            sa.Column('days', sa.Integer(), nullable=False),
            sa.Column('max_uses', sa.Integer(), nullable=False),
            sa.Column('used_count', sa.Integer(), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('comment', sa.String(), nullable=False),
            sa.Column(
                'created_at', sa.DateTime(timezone=True),
                server_default=sa.text('now()'), nullable=False,
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code', name='uq_promo_code'),
        )

    if 'dating_promo_activations' not in таблицы:
        op.create_table(
            'dating_promo_activations',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('promo_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column(
                'created_at', sa.DateTime(timezone=True),
                server_default=sa.text('now()'), nullable=False,
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(
                ['promo_id'], ['dating_promo_codes.id'], ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['user_id'], ['dating_users.id'], ondelete='CASCADE',
            ),
            sa.UniqueConstraint('promo_id', 'user_id', name='uq_promo_activation'),
        )
        op.create_index(
            'ix_promo_activation_user', 'dating_promo_activations', ['user_id'],
        )


def downgrade() -> None:
    op.drop_index('ix_promo_activation_user', table_name='dating_promo_activations')
    op.drop_table('dating_promo_activations')
    op.drop_table('dating_promo_codes')
