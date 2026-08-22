"""рассылки и суммы платежей

Revision ID: c7e94a20d1b5
Revises: f4c9d17a3e52
Create Date: 2026-08-22 01:10:00.000000

Два дела одной ревизии — обе для админки:

* dating_broadcasts — рассылка через бота: строка и задача, и отчёт
  (бот обновляет счётчики, админка показывает прогресс);
* amount/currency в dating_processed_payments — до этого журнал платежей
  помнил только факт и дни, и выручку было не из чего считать. Суммы в
  минорных единицах валюты (XTR — звёзды, RUB — копейки, USDT — сотые);
  NULL — сумма неизвестна: старые строки и платежи App Store, чью выручку
  считает Apple.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e94a20d1b5'
down_revision: Union[str, Sequence[str], None] = 'f4c9d17a3e52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `create_all` в lifespan поднимает недостающие таблицы по моделям, поэтому
    # на уже запускавшейся базе dating_broadcasts может существовать до этой
    # ревизии — без проверки create_table уронил бы всю пачку миграций
    inspector = sa.inspect(op.get_bind())
    существующие = set(inspector.get_table_names())

    if 'dating_broadcasts' not in существующие:
        op.create_table(
            'dating_broadcasts',
            sa.Column('id', sa.String(), nullable=False),
            # Без FK: история рассылок переживает удаление админа,
            # рядом имя-снапшот — как в dating_admin_audit_log
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('created_by_name', sa.String(), server_default='', nullable=False),
            sa.Column('text', sa.String(), nullable=False),
            sa.Column('segment', sa.String(), server_default='all', nullable=False),
            sa.Column('status', sa.String(), server_default='queued', nullable=False),
            sa.Column('total', sa.Integer(), server_default='0', nullable=False),
            sa.Column('sent', sa.Integer(), server_default='0', nullable=False),
            sa.Column('failed', sa.Integer(), server_default='0', nullable=False),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                server_default=sa.text('now()'),
                nullable=False,
            ),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    колонки = {c['name'] for c in inspector.get_columns('dating_processed_payments')}
    if 'amount' not in колонки:
        op.add_column(
            'dating_processed_payments',
            sa.Column('amount', sa.Integer(), nullable=True),
        )
    if 'currency' not in колонки:
        op.add_column(
            'dating_processed_payments',
            sa.Column('currency', sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column('dating_processed_payments', 'currency')
    op.drop_column('dating_processed_payments', 'amount')
    op.drop_table('dating_broadcasts')
