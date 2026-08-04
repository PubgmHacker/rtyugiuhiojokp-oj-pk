"""текст, приложенный к лайку

Revision ID: a1e4c73b0d26
Revises: f7d2b8e40a19
Create Date: 2026-08-04 13:20:00.000000

Кнопка «Написать» в боте существовала, но отвечала «напишите после мэтча» —
то есть не делала ничего. Между тем сказать пару слов вместе с лайком это
единственный способ выделиться до мэтча, и у конкурента он есть.

Текст живёт на самом лайке, а не в сообщениях: сообщения привязаны к мэтчу,
которого в этот момент ещё нет.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1e4c73b0d26'
down_revision: Union[str, Sequence[str], None] = 'f7d2b8e40a19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_likes',
        sa.Column('message', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('dating_likes', 'message')
