"""истории на сутки и их просмотры

Revision ID: b83d1e4af927
Revises: f4c92a71de60
Create Date: 2026-08-11 12:41:09.552173

Срок жизни держим в колонке, а не считаем от created_at: сутки — текущее
правило, а не закон, и продление до 48 часов не должно переписывать логику
всех запросов.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b83d1e4af927'
down_revision: Union[str, Sequence[str], None] = 'f4c92a71de60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `create_all` в lifespan поднимает таблицы по моделям ДО alembic, поэтому
    # на любой уже запускавшейся базе эти таблицы существуют, а ревизия — нет.
    # Без проверки create_table падает DuplicateTableError, а транзакционный
    # DDL Postgres откатывает вместе с ним ВСЮ пачку миграций: колонки из
    # предыдущих ревизий не появляются, и приложение падает на первом же
    # запросе к ним. Именно так ложился вход через /auth/dev.
    существующие = set(sa.inspect(op.get_bind()).get_table_names())

    if 'dating_stories' not in существующие:
        op.create_table(
            'dating_stories',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('media_url', sa.String(), nullable=False),
            sa.Column('object_key', sa.String(), server_default='', nullable=False),
            sa.Column('caption', sa.String(), server_default='', nullable=False),
            sa.Column('audience', sa.String(), server_default='matches', nullable=False),
            sa.Column('views_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('replies_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                server_default=sa.text('now()'),
                nullable=False,
            ),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_story_author_created', 'dating_stories', ['user_id', 'created_at'])
        op.create_index('ix_story_expires', 'dating_stories', ['expires_at'])

    if 'dating_story_views' not in существующие:
        op.create_table(
            'dating_story_views',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('story_id', sa.String(), nullable=False),
            sa.Column('viewer_id', sa.String(), nullable=False),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                server_default=sa.text('now()'),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(['story_id'], ['dating_stories.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['viewer_id'], ['dating_users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('story_id', 'viewer_id', name='uq_story_view'),
        )
        op.create_index('ix_story_view_viewer', 'dating_story_views', ['viewer_id', 'story_id'])


def downgrade() -> None:
    op.drop_index('ix_story_view_viewer', table_name='dating_story_views')
    op.drop_table('dating_story_views')
    op.drop_index('ix_story_expires', table_name='dating_stories')
    op.drop_index('ix_story_author_created', table_name='dating_stories')
    op.drop_table('dating_stories')
