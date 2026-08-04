"""групповые чаты по городу и интересам

Revision ID: b7e14c630f92
Revises: a4d90e28b165
Create Date: 2026-08-04 17:40:00.000000

Способ познакомиться до мэтча: написать в общий чат проще, чем первым в личку.

Комнаты заводим мы, а не пользователи: пользовательские комнаты — отдельный
продукт с модерацией названий, владельцами и правами, а здесь нужен только
повод для разговора. Стартовый набор добавлен этой же миграцией, иначе на
первом же открытии экран был бы пуст.

Сообщения в отдельной таблице, а не в `dating_messages`: там всё привязано к
мэтчу и есть отметка прочтения на двоих, которая в групповом чате бессмысленна.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e14c630f92'
down_revision: Union[str, Sequence[str], None] = 'a4d90e28b165'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Стартовые комнаты. Без городов: город появится, когда наберётся аудитория,
#: а пустой чат «Москва» отталкивает сильнее, чем его отсутствие.
_КОМНАТЫ = [
    ("smalltalk", "Просто поболтать", "Ни о чём и обо всём"),
    ("music", "Музыка", "Что слушаете и на какие концерты идёте"),
    ("games", "Игры", "От сессионок до одиночных"),
    ("movies", "Кино и сериалы", "Что посмотреть и что не стоит"),
    ("sport", "Спорт", "Зал, бег, единоборства и всё остальное"),
    ("art", "Творчество", "Рисуете, пишете, снимаете — расскажите"),
]


def upgrade() -> None:
    rooms = op.create_table(
        'dating_rooms',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False, server_default=''),
        sa.Column('city', sa.String(), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_room_slug'),
    )

    op.create_table(
        'dating_room_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('room_id', sa.String(), nullable=False),
        sa.Column('sender_id', sa.String(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['room_id'], ['dating_rooms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['dating_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_room_message_created', 'dating_room_messages', ['room_id', 'created_at']
    )

    # id берём равным slug: он уже уникален, а генерировать uuid в миграции
    # значило бы импортировать модели — те меняются, а миграция обязана
    # работать на своей версии схемы
    op.bulk_insert(
        rooms,
        [
            {
                'id': slug,
                'slug': slug,
                'title': title,
                'description': description,
                'city': '',
                'is_active': True,
            }
            for slug, title, description in _КОМНАТЫ
        ],
    )


def downgrade() -> None:
    op.drop_index('ix_room_message_created', table_name='dating_room_messages')
    op.drop_table('dating_room_messages')
    op.drop_table('dating_rooms')
