"""device tokens for APNs push

Revision ID: d5b8f1c02e47
Revises: c4a7e0b91d33
Create Date: 2026-08-04 08:50:00.000000

Клиентская часть пушей была готова, но токен устройства некуда было
отправить. Токен уникален: APNs выдаёт его на пару «приложение +
устройство», и он переезжает к другому пользователю, если на телефоне
сменили аккаунт — уникальный ключ позволяет перепривязать запись вместо
того, чтобы слать пуши прежнему владельцу.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5b8f1c02e47'
down_revision: Union[str, Sequence[str], None] = 'c4a7e0b91d33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dating_device_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False, server_default='ios'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_device_token'),
    )
    # Отправка ищет все устройства пользователя
    op.create_index('ix_device_user', 'dating_device_tokens', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_device_user', table_name='dating_device_tokens')
    op.drop_table('dating_device_tokens')
