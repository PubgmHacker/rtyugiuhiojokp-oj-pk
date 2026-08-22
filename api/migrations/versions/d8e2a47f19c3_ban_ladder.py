"""лестница банов: срок блокировки на пользователе и в памяти банов

Revision ID: d8e2a47f19c3
Revises: c3b8f9d21e07
Create Date: 2026-08-21 14:00:00.000000

До этого бан был один — вечный. Для катфишинга это правильно, но за спам или
рекламу в анкете вечный бан несоразмерен: человек либо уходит навсегда, либо
идёт по кругу «удалил аккаунт — вернулся». Временный бан с растущим сроком
(24 ч → 72 ч → 7 дней → вечный) наказывает, не выжигая базу пользователей,
а платная досрочная разблокировка превращает нарушителя в выручку вместо
потери.

`banned_until` NULL при is_banned=TRUE означает вечный бан — прежнее
поведение сохраняется для всех уже забаненных без единого UPDATE.

Копия срока в dating_banned_identities обязательна: удаливший аккаунт уносит
с собой users.banned_until, и без копии вернувшийся через повторную
регистрацию получал бы вечный бан вместо остатка срока (или наоборот —
чистую историю, если бы мы перестали наследовать бан вовсе).

Фонового джоба снятия банов нет намеренно: истечение проверяется лениво в
get_current_user и login-путях. Джоб — ещё один процесс, который может встать
молча; ленивая проверка отказать не может.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8e2a47f19c3'
down_revision: Union[str, Sequence[str], None] = 'c3b8f9d21e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_users',
        sa.Column('banned_until', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'dating_banned_identities',
        sa.Column('banned_until', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('dating_banned_identities', 'banned_until')
    op.drop_column('dating_users', 'banned_until')
