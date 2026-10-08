"""rappels automatiques : cree_le, dernier_rappel_le, nombre_rappels sur etapes_workflow

Revision ID: 2fc43a22f0db
Revises: 83280b4e83bc
Create Date: 2026-09-28 11:11:58.683167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2fc43a22f0db'
down_revision: Union[str, None] = '83280b4e83bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Mode batch + func.now() : portable (SQLite refuse ADD COLUMN avec un defaut
    # non constant et ne connait pas now()). Sur PostgreSQL : ALTER TABLE ordinaires.
    # Les etapes deja en attente recoivent la date de la migration comme creation :
    # leur premier rappel interviendra une periode complete apres le deploiement.
    with op.batch_alter_table('etapes_workflow') as batch_op:
        batch_op.add_column(
            sa.Column('cree_le', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
        )
        batch_op.add_column(sa.Column('dernier_rappel_le', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('nombre_rappels', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('etapes_workflow') as batch_op:
        batch_op.drop_column('nombre_rappels')
        batch_op.drop_column('dernier_rappel_le')
        batch_op.drop_column('cree_le')
