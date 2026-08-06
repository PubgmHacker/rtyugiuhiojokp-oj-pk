"""индекс на автора жалобы

Revision ID: a3d5f27b91c4
Revises: f1c2e83a5d47
Create Date: 2026-08-06 03:20:00.000000

Дедуп жалобы («не жаловался ли я на него уже») и антифлуд («сколько жалоб за
час») фильтруют `dating_reports` по `reporter_id`, а индекса на нём не было —
только на `reported_id`. Каждая новая жалоба сканировала таблицу целиком, и с
её ростом тормозил самый чувствительный путь: человек жалуется, когда ему уже
плохо, и ждать он не должен.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d5f27b91c4'
down_revision: Union[str, Sequence[str], None] = 'f1c2e83a5d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_report_reporter', 'dating_reports', ['reporter_id'])


def downgrade() -> None:
    op.drop_index('ix_report_reporter', table_name='dating_reports')
