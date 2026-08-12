"""оформление карточки

Revision ID: d5a1b8e04c37
Revises: c7e2a8f13b95
Create Date: 2026-08-11 11:48:19.204773
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd5a1b8e04c37'
down_revision: Union[str, Sequence[str], None] = 'c7e2a8f13b95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable без server_default: «без рамки» — это NULL, а не пустая
    # строка. Пустая строка потребовала бы отличать её от NULL в каждом
    # чтении, и однажды это забудут сделать.
    op.add_column("dating_profiles", sa.Column("decor", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("dating_profiles", "decor")
