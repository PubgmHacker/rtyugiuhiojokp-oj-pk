"""видео-лента (reels) и лайки роликов

Revision ID: c9a5d72e138b
Revises: b8f3e91c204d
Create Date: 2026-08-04 14:45:00.000000

Свайп-дека была единственным способом знакомиться. Ролики дают второй формат:
человека видно живым, а не набором из четырёх фото.

`likes_count` лежит прямо в ролике, хотя лайки есть и отдельной таблицей: лента
сортируется по популярности, и COUNT по лайкам на каждый ролик означал бы
лишний проход на каждый запрос ленты. Таблица лайков всё равно нужна — по ней
видно, лайкнул ли конкретный человек, и она же не даёт лайкнуть дважды.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9a5d72e138b'
down_revision: Union[str, Sequence[str], None] = 'b8f3e91c204d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_reels',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('video_url', sa.String(), nullable=False),
        sa.Column('cover_url', sa.String(), nullable=False, server_default=''),
        sa.Column('caption', sa.String(), nullable=False, server_default=''),
        sa.Column('likes_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reel_created', 'dating_reels', ['created_at'])
    op.create_index('ix_reel_author', 'dating_reels', ['user_id'])

    op.create_table(
        'dating_reel_likes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('reel_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['reel_id'], ['dating_reels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reel_id', 'user_id', name='uq_reel_like'),
    )
    op.create_index('ix_reel_like_reel', 'dating_reel_likes', ['reel_id'])


def downgrade() -> None:
    op.drop_index('ix_reel_like_reel', table_name='dating_reel_likes')
    op.drop_table('dating_reel_likes')
    op.drop_index('ix_reel_author', table_name='dating_reels')
    op.drop_index('ix_reel_created', table_name='dating_reels')
    op.drop_table('dating_reels')
