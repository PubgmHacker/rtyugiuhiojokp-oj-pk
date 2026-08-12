"""ключ платежа у подарка: один чек — один подарок

Revision ID: c7e2a8f13b95
Revises: b83d1e4af927
Create Date: 2026-08-11 11:42:07.331508

Колонки стрика (`burnt_from_days`, `burnt_at`, nullable у
`revives_refreshed_at`) здесь НЕ трогаем: их добавляет `e7b1c4d92f38`,
которая стоит раньше в цепочке. Повторный add_column упал бы на
DuplicateColumn и остановил бы весь upgrade на боевой базе.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c7e2a8f13b95'
down_revision: Union[str, Sequence[str], None] = 'b83d1e4af927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ключ платежа у подарка: один чек — один подарок, сколько бы раз Apple
    # ни повторила доставку. Уникальность в БД, а не в коде: два запроса
    # приходят параллельно и проверка «сначала посмотреть» их не разводит.
    op.add_column(
        "dating_gift_subscriptions",
        sa.Column("payment_id", sa.String(), nullable=True),
    )
    # Частичный уникальный индекс: подарки из бота платежа не имеют, и
    # обычная уникальность запретила бы второй такой подарок — NULL'ы в
    # UNIQUE ведут себя по-разному в разных СУБД, поэтому условие явное.
    op.create_index(
        "uq_gift_payment",
        "dating_gift_subscriptions",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
        sqlite_where=sa.text("payment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_gift_payment", table_name="dating_gift_subscriptions")
    op.drop_column("dating_gift_subscriptions", "payment_id")
