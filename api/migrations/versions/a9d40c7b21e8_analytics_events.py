"""событийная аналитика — воронка от /start до покупки

Revision ID: a9d40c7b21e8
Revises: c7e51a08d3f6
Create Date: 2026-08-23 12:00:00.000000

Аналитики не было вообще — ни одного трекинга: воронку CPI → анкета →
первый свайп → D1 → покупка и окупаемость канала посмотреть было нечем,
платный трафик лился бы вслепую. Внешние трекеры дейтингу противопоказаны
(передача данных третьим лицам — отдельный пункт согласия), поэтому события
лежат в своём Postgres, а воронка считается обычным SQL
(готовые запросы — в services/analytics.py).

dedup_key превращает событие в веху: у «первого свайпа» это user:event
(одна строка на всю жизнь), у ежедневных — user:event:день. UNIQUE
игнорирует NULL, поэтому события без дедупликации пишутся свободно.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision: str = 'a9d40c7b21e8'
down_revision: Union[str, Sequence[str], None] = 'c7e51a08d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_analytics_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column(
            'user_id',
            sa.String(),
            sa.ForeignKey('dating_users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('event', sa.String(length=64), nullable=False),
        sa.Column('props', JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('dedup_key', sa.String(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedup_key'),
    )
    # Воронка режется по событию и окну дат
    op.create_index(
        'ix_analytics_event_created',
        'dating_analytics_events',
        ['event', 'created_at'],
    )
    # Траектория человека: какие вехи прошёл и когда
    op.create_index(
        'ix_analytics_user_event',
        'dating_analytics_events',
        ['user_id', 'event'],
    )


def downgrade() -> None:
    op.drop_index('ix_analytics_user_event', table_name='dating_analytics_events')
    op.drop_index('ix_analytics_event_created', table_name='dating_analytics_events')
    op.drop_table('dating_analytics_events')
