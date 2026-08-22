"""проверка профиля через провайдера (Sumsub)

Revision ID: a2d84c19f3e7
Revises: b9c4e71f52a8
Create Date: 2026-08-18 12:00:00.000000

Попытка верификации получает происхождение: встроенная схема (позы + GLM)
или KYC-провайдер Sumsub. `provider_ref` хранит applicantId Sumsub — по нему
суппорт находит заявку в дашборде провайдера, а сервер сверяет вебхук с
попыткой. Кадры, как и раньше, никуда не пишутся: строка — только метаданные.

Существующие строки — все встроенной проверки, поэтому server_default
'builtin' честно описывает историю, а не просто затыкает NOT NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2d84c19f3e7'
down_revision: Union[str, Sequence[str], None] = 'b9c4e71f52a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dating_verification_attempts',
        sa.Column('provider', sa.String(), nullable=False, server_default='builtin'),
    )
    op.add_column(
        'dating_verification_attempts',
        sa.Column('provider_ref', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('dating_verification_attempts', 'provider_ref')
    op.drop_column('dating_verification_attempts', 'provider')
