"""categorie sur pieces_jointes (contrat, reçu, justificatif, complement, discussion)

Revision ID: e831c4d76217
Revises: 2fc43a22f0db
Create Date: 2026-09-28 11:24:17.361831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e831c4d76217'
down_revision: Union[str, None] = '2fc43a22f0db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # L'autogeneration produisait une colonne NOT NULL sans defaut, qui echouerait sur une
    # table deja peuplee. Avant cette migration, toute piece sans message etait le contrat
    # d'un achat (seul depot possible) et toute piece liee a un message une piece de
    # discussion : on reclasse les lignes existantes en consequence, puis on retire le
    # defaut serveur (la categorie est toujours fournie explicitement par l'application).
    with op.batch_alter_table('pieces_jointes') as batch_op:
        batch_op.add_column(sa.Column('categorie', sa.String(length=30), nullable=False, server_default='contrat'))
    op.execute("UPDATE pieces_jointes SET categorie = 'discussion' WHERE message_id IS NOT NULL")
    with op.batch_alter_table('pieces_jointes') as batch_op:
        batch_op.alter_column('categorie', existing_type=sa.String(length=30), existing_nullable=False, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('pieces_jointes') as batch_op:
        batch_op.drop_column('categorie')
