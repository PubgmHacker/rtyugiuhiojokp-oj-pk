"""платный буст показов анкеты

Revision ID: f3a71d95c806
Revises: e2c8b91f704a
Create Date: 2026-08-04 16:20:00.000000

Буст был только реферальный — за приглашённых друзей. Платного, ограниченного
по времени, не было, хотя у конкурента это понятная покупка с явным эффектом
(30 минут, кратный рост показов).

Храним момент окончания, а не флаг со счётчиком: прошедшая дата сама означает
«буста нет», и ничего не нужно чистить по расписанию — пропущенный запуск
уборщика иначе оставил бы анкету поднятой навсегда.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a71d95c806'
down_revision: Union[str, Sequence[str], None] = 'e2c8b91f704a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('boost_until', sa.DateTime(timezone=True), nullable=True),
    )
    # Журнал включений: по нему считается суточный остаток. Счётчик в анкете
    # пришлось бы обнулять по расписанию, а пропущенный запуск дал бы безлимит
    op.create_table(
        'dating_boost_activations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_boost_user_created', 'dating_boost_activations', ['user_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_boost_user_created', table_name='dating_boost_activations')
    op.drop_table('dating_boost_activations')
    op.drop_column('dating_profiles', 'boost_until')
