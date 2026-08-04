"""оценка фото по шкале 1-5

Revision ID: a4d90e28b165
Revises: f3a71d95c806
Create Date: 2026-08-04 17:00:00.000000

Отдельный формат: показываем фото, человек ставит оценку. Заходить в
приложение становится зачем-то ещё, кроме свайпов.

Оценка привязана к анкете, а не к конкретному фото: иначе один человек
наставил бы шесть оценок одному и тому же лицу. Уникальный ключ по паре
позволяет переоценить, но не проголосовать дважды.

Среднюю оценку не храним — считаем запросом. Оценок на человека немного, а
расходящийся кеш пришлось бы пересчитывать по расписанию.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4d90e28b165'
down_revision: Union[str, Sequence[str], None] = 'f3a71d95c806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_photo_ratings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('rater_id', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['rater_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rater_id', 'target_id', name='uq_photo_rating'),
    )
    op.create_index('ix_photo_rating_target', 'dating_photo_ratings', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_photo_rating_target', table_name='dating_photo_ratings')
    op.drop_table('dating_photo_ratings')
