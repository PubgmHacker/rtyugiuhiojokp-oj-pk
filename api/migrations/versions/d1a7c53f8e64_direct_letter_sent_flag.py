"""флаг «письмо раунда отправлено» в личке без мэтча

Revision ID: d1a7c53f8e64
Revises: c4f8a2e91b73
Create Date: 2026-08-08 07:40:00.000000

Правило «одно письмо до ответа» держалось на подсчёте сообщений беседы, и это
неверно: строка `dating_matches` у пары ОДНА и переиспользуется. Размэтч гасит
её (`is_active=False`), следующее письмо реактивирует ту же строку — а
сообщения прошлого раунда никуда не делись и отказывали отправителю в первом же
письме нового раунда. Попытка сузить подсчёт по `created_at` беседы дала худшее:
на SQLite `server_default=now()` пишет секунды без микросекунд, связанный
datetime — с микросекундами, сравнение идёт строками, условие всегда ложно и
правило молча открывалось совсем.

Поэтому факт письма — явный флаг раунда, ровно как у `direct_answered` рядом
(там та же причина уже записана: «держим флагом, а не считаем сообщения
запросом»). Раунд — это одна пара «письмо → ответ»; оба флага гасятся при
реактивации беседы.

Существующим строкам ставим `false`: колонка нужна только для `kind='direct'`, а
у беседы, которая уже дожила до этой миграции, отправитель либо получил ответ
(`direct_answered=true`, флаг не смотрится вовсе), либо ещё пишет первое письмо
— и false для него верное значение. Бэкфила по сообщениям нет намеренно: он
воспроизвёл бы ровно тот подсчёт, из-за которого колонка и заводится.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1a7c53f8e64'
down_revision: Union[str, Sequence[str], None] = 'c4f8a2e91b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_matches',
        sa.Column(
            'direct_letter_sent', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('dating_matches', 'direct_letter_sent')
