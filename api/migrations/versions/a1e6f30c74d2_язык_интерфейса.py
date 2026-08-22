"""Язык интерфейса на аккаунте.

`dating_users.locale` — код языка, выбранный на первом шаге онбординга бота
(язык → политика → рассылки). До этой колонки выбор жил только в FSM-состоянии
бота: он не переживал ни перезапуск, ни истечение ключа состояния, и человек,
выбравший узбекский, дальше получал русский интерфейс — а мини-апп о выборе не
узнавал вовсе.

Язык на аккаунте, а не в анкете: он нужен уведомлениям (бан, итог жалобы), где
анкета не загружается, и обязан пережить удаление анкеты.

Бэкфилл не нужен: `server_default 'ru'` заполняет существующие строки, и это
верно по факту — весь продукт до сих пор говорит по-русски, и все, кто уже
пользуется ботом, пользуются им на русском.

Revision ID: a1e6f30c74d2
Revises: d8f31c72ab90
Create Date: 2026-08-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1e6f30c74d2"
down_revision: Union[str, Sequence[str], None] = "d8f31c72ab90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dating_users",
        sa.Column(
            "locale",
            sa.String(),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dating_users", "locale")
