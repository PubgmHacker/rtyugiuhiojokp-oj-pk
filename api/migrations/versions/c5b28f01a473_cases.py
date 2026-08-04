"""кейсы с наградами внутри продукта

Revision ID: c5b28f01a473
Revises: b7e14c630f92
Create Date: 2026-08-04 18:20:00.000000

Попытки открытия даются за подписку — как у конкурента. Награды другие: у него
коллекционные персонажи, а это шестьдесят рисунков, ценных только тому, кто их
собирает. У нас выпадает то, что уже работает: суперлайки и минуты буста.

Суперлайки из кейса живут отдельным полем, а не прибавкой к суточной квоте:
квота считается по факту расхода за сутки, и прибавка к ней возобновлялась бы
каждый день сама — кейс давал бы бесконечный бонус.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5b28f01a473'
down_revision: Union[str, Sequence[str], None] = 'b7e14c630f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('bonus_superlikes', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_table(
        'dating_case_openings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('reward', sa.String(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False, server_default='1'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_case_user_created', 'dating_case_openings', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_case_user_created', table_name='dating_case_openings')
    op.drop_table('dating_case_openings')
    op.drop_column('dating_profiles', 'bonus_superlikes')
