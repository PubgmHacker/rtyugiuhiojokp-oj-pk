"""верификация профиля

Revision ID: b9c4e71f52a8
Revises: a5f1c8e2b3d9
Create Date: 2026-08-18 12:00:00.000000

Галочка `is_verified` до сих пор не значила ничего: бот ставил её каждому,
кто дошёл до конца анкеты (set_profile_ready), а сид — админу. Бейдж
«профиль подтверждён» показывался людям, которых никто не проверял, — то
есть врал ровно там, где обещал доверие.

Теперь галочка выдаётся только за живую проверку (съёмка лица с поворотами
головы + сравнение с фото анкеты, api/routers/verification.py). Поэтому:

* заводим журнал попыток — без кадров, только задание и вердикт: кадры
  биометричны и не сохраняются нигде;
* сбрасываем все ранее розданные галочки — они не были заработаны, и
  оставить их значило бы навсегда смешать «прошёл проверку» с «дошёл до
  конца анкеты».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b9c4e71f52a8'
down_revision: Union[str, Sequence[str], None] = 'a5f1c8e2b3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_verification_attempts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('poses', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='issued'),
        sa.Column('reason', sa.String(), nullable=False, server_default=''),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_verification_user_created',
        'dating_verification_attempts',
        ['user_id', 'created_at'],
    )

    # Старые галочки не заработаны — обнуляем все. Кто хочет бейдж, проходит
    # проверку; админам сид больше галочку не ставит по той же причине.
    op.execute("UPDATE dating_users SET is_verified = false")


def downgrade() -> None:
    op.drop_index(
        'ix_verification_user_created', table_name='dating_verification_attempts'
    )
    op.drop_table('dating_verification_attempts')
    # Галочки не восстанавливаем: их прежний источник (авто-выдача ботом)
    # удалён из кода, а «вернуть всем» — то же враньё, от которого уходили.
