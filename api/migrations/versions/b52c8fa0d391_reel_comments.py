"""комментарии к роликам, счётчики комментариев и просмотров

Revision ID: b52c8fa0d391
Revises: a17e3d05f8c2
Create Date: 2026-08-05 15:00:00.000000

Без комментариев лента роликов остаётся просмотром: самое сильное впечатление
от видео никуда не ведёт. Под видео написать проще, чем в личку первым, — здесь
ролики и превращаются в знакомства.

Счётчики лежат в самом ролике, как и лайки: лента показывает их на каждой
карточке, а COUNT по двум таблицам на каждый ролик — лишний проход на каждый
запрос ленты.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b52c8fa0d391'
down_revision: Union[str, Sequence[str], None] = 'a17e3d05f8c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_reels',
        sa.Column('comments_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'dating_reels',
        sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'dating_reel_comments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('reel_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['reel_id'], ['dating_reels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_reel_comment_reel', 'dating_reel_comments', ['reel_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_reel_comment_reel', table_name='dating_reel_comments')
    op.drop_table('dating_reel_comments')
    op.drop_column('dating_reels', 'views_count')
    op.drop_column('dating_reels', 'comments_count')
