"""Лимитированные обложки карточки.

`dating_decor_owned` — владение обложками, по строке на выпадение из кейса.
Раньше право на обложку вычислялось из числа наклеек и тарифа; теперь обложки
лимитированные и достаются только из кейса, поэтому владение хранится явно,
как у наклеек.

Бэкфилл: уже надетые обложки записываются во владение. Иначе после деплоя
человек не смог бы заново выбрать то, что честно заработал по старым правилам
и носит прямо сейчас.

Revision ID: d8f31c72ab90
Revises: c7e19a4d82f5
Create Date: 2026-08-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f31c72ab90"
down_revision: Union[str, Sequence[str], None] = "c7e19a4d82f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dating_decor_owned",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["dating_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code", name="uq_decor_owner"),
    )
    op.create_index("ix_decor_user", "dating_decor_owned", ["user_id"])

    # Надетая обложка становится собственной: снять и надеть обратно должно
    # оставаться возможным, иначе смена правил отняла бы уже заработанное.
    op.execute(
        """
        INSERT INTO dating_decor_owned (id, user_id, code, created_at)
        SELECT gen_random_uuid()::text, user_id, decor, now()
        FROM dating_profiles
        WHERE decor IS NOT NULL AND decor <> ''
        ON CONFLICT ON CONSTRAINT uq_decor_owner DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_decor_user", table_name="dating_decor_owned")
    op.drop_table("dating_decor_owned")
