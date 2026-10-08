"""limitation des connexions, cle etrangere manager, JSONB (R9, R24)

Revision ID: 539e98a78e69
Revises: b5c1d7e2f903
Create Date: 2026-09-29 19:40:00.000000

1. utilisateurs : colonnes `tentatives_echouees`, `verrouille_jusqua`, `dernier_login_le` (CDC 4.2.1 et 5) ;
2. utilisateurs.manager_id : cle etrangere vers utilisateurs.id (CDC 4.2.1). Les valeurs orphelines
   eventuelles (manager inexistant) sont d'abord mises a NULL, sinon la contrainte ne pourrait pas etre
   posee ; leur nombre est ecrit dans le journal de migration ;
3. demandes.donnees : JSON -> JSONB sur PostgreSQL uniquement (CDC 4.1). SQLite (tests) n'a pas de JSONB.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "539e98a78e69"
down_revision: Union[str, None] = "b5c1d7e2f903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

journal = logging.getLogger("alembic.runtime.migration")
NOM_FK_MANAGER = "fk_utilisateurs_manager_id"


def upgrade() -> None:
    op.add_column("utilisateurs", sa.Column("tentatives_echouees", sa.Integer(), server_default="0", nullable=False))
    op.add_column("utilisateurs", sa.Column("verrouille_jusqua", sa.DateTime(timezone=True), nullable=True))
    op.add_column("utilisateurs", sa.Column("dernier_login_le", sa.DateTime(timezone=True), nullable=True))

    connexion = op.get_bind()
    orphelins = connexion.execute(
        sa.text(
            "UPDATE utilisateurs SET manager_id = NULL WHERE manager_id IS NOT NULL "
            "AND manager_id NOT IN (SELECT id FROM (SELECT id FROM utilisateurs) AS existants)"
        )
    ).rowcount
    if orphelins:
        journal.warning("%s rattachement(s) manager_id orphelin(s) remis a NULL avant pose de la contrainte", orphelins)
    with op.batch_alter_table("utilisateurs") as batch_op:
        batch_op.create_foreign_key(NOM_FK_MANAGER, "utilisateurs", ["manager_id"], ["id"])

    if connexion.dialect.name == "postgresql":
        op.execute("ALTER TABLE demandes ALTER COLUMN donnees TYPE JSONB USING donnees::jsonb")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE demandes ALTER COLUMN donnees TYPE JSON USING donnees::json")
    with op.batch_alter_table("utilisateurs") as batch_op:
        batch_op.drop_constraint(NOM_FK_MANAGER, type_="foreignkey")
    op.drop_column("utilisateurs", "dernier_login_le")
    op.drop_column("utilisateurs", "verrouille_jusqua")
    op.drop_column("utilisateurs", "tentatives_echouees")
