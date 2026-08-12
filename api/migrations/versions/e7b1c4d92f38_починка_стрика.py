"""починка стрика: память о сгоревшей серии + честная месячная квота

Revision ID: e7b1c4d92f38
Revises: 9a3a83105bea
Create Date: 2026-08-11 09:14:02.118440

Три вещи. Первая — колонки `burnt_from_days` и `burnt_at`: без них
восстановление возвращало серию к единице, потому что прежнюю длину
никто не помнил. Вторая — снимаем `server_default=now()` с
`revives_refreshed_at` и обнуляем его: со значением по умолчанию первый
же вызов начисления квоты считал текущий месяц уже обработанным и
выходил, поэтому `revives_left` навсегда оставался нулём. Третья —
досыпаем квоту тем парам, у которых серия уже накопилась: они месяцами
её не получали из-за той же ошибки.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7b1c4d92f38'
down_revision: Union[str, Sequence[str], None] = '9a3a83105bea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_chat_streaks',
        sa.Column('burnt_from_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.add_column(
        'dating_chat_streaks',
        sa.Column('burnt_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column(
        'dating_chat_streaks',
        'revives_refreshed_at',
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        nullable=True,
    )
    # Обнуляем метку у всех: она была выставлена автоматически при
    # создании строки и означала «квота за этот месяц выдана», хотя
    # выдачи не было ни одной.
    op.execute("UPDATE dating_chat_streaks SET revives_refreshed_at = NULL")

    # Начисляем квоту по фактической длине серии — те же пороги, что в
    # services/streaks.py: 300+ дней → 3, 100+ → 2, 10+ → 1.
    op.execute(
        """
        UPDATE dating_chat_streaks
        SET revives_left = CASE
            WHEN streak_days >= 300 THEN 3
            WHEN streak_days >= 100 THEN 2
            WHEN streak_days >= 10 THEN 1
            ELSE 0
        END
        """
    )


def downgrade() -> None:
    op.alter_column(
        'dating_chat_streaks',
        'revives_refreshed_at',
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text('now()'),
        nullable=False,
    )
    op.drop_column('dating_chat_streaks', 'burnt_at')
    op.drop_column('dating_chat_streaks', 'burnt_from_days')
