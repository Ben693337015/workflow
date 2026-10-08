"""message_id sur pieces_jointes (pieces de la discussion, ecart n5)

Revision ID: 83280b4e83bc
Revises: 01c3c7004910
Create Date: 2026-09-28 10:47:57.753543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '83280b4e83bc'
down_revision: Union[str, None] = '01c3c7004910'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Mode batch : SQLite (developpement local, verifications de bout en bout) ne
    # sait pas ALTER une contrainte ; sur PostgreSQL, batch_alter_table emet les
    # memes ALTER TABLE ordinaires. Nom de contrainte explicite : l'autogeneration
    # laissait None, ce qui faisait echouer le downgrade (drop_constraint exige un nom).
    with op.batch_alter_table('pieces_jointes') as batch_op:
        batch_op.add_column(sa.Column('message_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_pieces_jointes_message_id', 'messages_clarification', ['message_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('pieces_jointes') as batch_op:
        batch_op.drop_constraint('fk_pieces_jointes_message_id', type_='foreignkey')
        batch_op.drop_column('message_id')
