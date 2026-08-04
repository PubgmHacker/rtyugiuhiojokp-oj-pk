"""profile sample_key for deck sampling

Revision ID: c4a7e0b91d33
Revises: b2f1c47ade90
Create Date: 2026-08-04 08:20:00.000000

Дека выбирала анкеты через `ORDER BY random()`. Такому запросу приходится
присвоить случайное число каждой подходящей строке и отсортировать весь
набор — индекс не применим, и на десятках тысяч анкет это последовательное
сканирование на каждый показ.

`sample_key` даёт анкете постоянное случайное место в порядке выдачи: дека
берёт случайную точку и читает следующие строки по индексу. Индекс частичный
— невидимки и незаполненные анкеты в деку не попадают, значит и в индексе им
места нет.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4a7e0b91d33'
down_revision: Union[str, Sequence[str], None] = 'b2f1c47ade90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default заполняет ключ и у существующих анкет — без него они
    # получили бы NULL и выпали из выдачи
    op.add_column(
        'dating_profiles',
        sa.Column(
            'sample_key',
            sa.Float(),
            nullable=False,
            server_default=sa.text('random()'),
        ),
    )
    op.create_index(
        'ix_profile_sample',
        'dating_profiles',
        ['sample_key'],
        postgresql_where=sa.text("NOT is_incognito AND display_name <> ''"),
    )


def downgrade() -> None:
    op.drop_index('ix_profile_sample', table_name='dating_profiles')
    op.drop_column('dating_profiles', 'sample_key')
