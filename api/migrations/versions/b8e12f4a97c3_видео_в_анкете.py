"""видеоролики в анкете

Revision ID: b8e12f4a97c3
Revises: a9d40c7b21e8
Create Date: 2026-08-25 12:00:00.000000

Анкета получает видеоролики рядом с фото: список публичных URL из R2
(profile-videos/{user_id}/…), до MAX_PROFILE_VIDEOS штук. Отдельная колонка,
а не общий список с фото: у фото есть гейт «живой человек» и опорный снимок
верификации, видео этих проверок не проходит и подменять фото не должно.

server_default '[]' — у существующих анкет видео нет, и читающий код
(`as_list`) сразу видит пустой список, а не NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision: str = 'b8e12f4a97c3'
down_revision: Union[str, Sequence[str], None] = 'a9d40c7b21e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_profiles',
        sa.Column('videos', JSON(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('dating_profiles', 'videos')
