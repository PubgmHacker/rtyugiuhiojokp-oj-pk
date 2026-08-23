"""индексы горячих путей

Revision ID: c7e51a08d3f6
Revises: b3f8c2d94a17
Create Date: 2026-08-22 19:30:00.000000

Аудит под запуск на 1000+ пользователей: пять запросов, которые зовутся на
каждый вход или свайп, не имели поддерживающего индекса и читали таблицы
целиком. Каждый индекс здесь привязан к конкретному месту в коде:

* ix_message_unread (частичный) — COUNT непрочитанных в /badges и списке
  чатов, UPDATE отметки прочтения. Непрочитанных на порядки меньше, чем
  сообщений, поэтому индекс крошечный.
* ix_like_liker_created — квоты лайков/суперлайков за скользящее окно,
  считаются на каждом свайпе (services/quotas.py).
* ix_referral_referrer — COUNT приглашённых на каждом GET /profiles/me
  и в ранжировании деки; FK был вовсе без индекса.
* ix_notification_unread (частичный) — красная точка колокольчика.
* ix_ai_moderation_user_created / ix_ai_moderation_created — журнал
  модерации пишется на каждое сообщение и не имел ни одного индекса.

Без CONCURRENTLY сознательно: миграция едет в lifespan до приёма трафика,
а таблицы на момент включения ещё небольшие — обычный CREATE INDEX здесь
занимает миллисекунды и, в отличие от CONCURRENTLY, работает в транзакции.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e51a08d3f6'
down_revision: Union[str, Sequence[str], None] = 'b3f8c2d94a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (имя, таблица, колонки, условие частичного индекса или None)
_ИНДЕКСЫ = [
    (
        'ix_message_unread', 'dating_messages',
        ['match_id', 'sender_id'], 'read_at IS NULL',
    ),
    (
        'ix_like_liker_created', 'dating_likes',
        ['liker_id', 'created_at'], None,
    ),
    ('ix_referral_referrer', 'dating_referrals', ['referrer_id'], None),
    (
        'ix_notification_unread', 'dating_notifications',
        ['user_id'], 'read_at IS NULL',
    ),
    (
        'ix_ai_moderation_user_created', 'dating_ai_moderation_logs',
        ['user_id', 'created_at'], None,
    ),
    (
        'ix_ai_moderation_created', 'dating_ai_moderation_logs',
        ['created_at'], None,
    ),
]


def upgrade() -> None:
    # `create_all` в lifespan мог уже создать часть индексов по моделям —
    # на чистой базе он бежит раньше штампа. Проверяем каждый по имени.
    inspector = sa.inspect(op.get_bind())
    таблицы = set(inspector.get_table_names())

    for имя, таблица, колонки, условие in _ИНДЕКСЫ:
        if таблица not in таблицы:
            continue  # таблицу заведёт create_all сразу с индексом из модели
        существующие = {i['name'] for i in inspector.get_indexes(таблица)}
        if имя in существующие:
            continue
        if условие:
            op.create_index(
                имя, таблица, колонки, postgresql_where=sa.text(условие),
            )
        else:
            op.create_index(имя, таблица, колонки)


def downgrade() -> None:
    for имя, таблица, _, _ in reversed(_ИНДЕКСЫ):
        op.drop_index(имя, table_name=таблица)
