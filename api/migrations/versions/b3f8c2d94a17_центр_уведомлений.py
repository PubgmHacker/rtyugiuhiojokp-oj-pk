"""центр уведомлений

Revision ID: b3f8c2d94a17
Revises: a9d47ce1f2b3
Create Date: 2026-08-22 16:40:00.000000

dating_notifications — лента событий без собственного экрана: итог жалобы,
галочка верификации вдогонку вебхуком. Читает мини-апп (GET /notifications),
бейдж непрочитанного едет в /badges.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f8c2d94a17'
down_revision: Union[str, Sequence[str], None] = 'a9d47ce1f2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `create_all` в lifespan мог создать таблицу по модели раньше миграции
    inspector = sa.inspect(op.get_bind())
    таблицы = set(inspector.get_table_names())

    if 'dating_notifications' not in таблицы:
        op.create_table(
            'dating_notifications',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column(
                'created_at', sa.DateTime(timezone=True),
                server_default=sa.text('now()'), nullable=False,
            ),
            sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(
                ['user_id'], ['dating_users.id'], ondelete='CASCADE',
            ),
        )
        op.create_index(
            'ix_notification_user', 'dating_notifications',
            ['user_id', 'created_at'],
        )


def downgrade() -> None:
    op.drop_index('ix_notification_user', table_name='dating_notifications')
    op.drop_table('dating_notifications')
