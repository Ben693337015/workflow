"""journal_audit_ajout_seul

Revision ID: 20e05f709e2a
Revises: e831c4d76217
Create Date: 2026-09-28 11:40:40.530213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20e05f709e2a'
down_revision: Union[str, None] = 'e831c4d76217'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MESSAGE = "journal_audit est en ajout seul : UPDATE, DELETE et TRUNCATE interdits (CDC 2.4, technique 14.3)"


def upgrade() -> None:
    # Inalterabilite du journal d'audit (CDC fonctionnel 2.4 ; technique 14.3), jusqu'ici
    # seulement annoncee dans une note du modele. SQL fige ici (une migration ne doit pas
    # dependre du code applicatif qui evolue). Les lignes deja presentes sont conservees.
    dialecte = op.get_bind().dialect.name
    if dialecte == "postgresql":
        op.execute(f"""
            CREATE OR REPLACE FUNCTION journal_audit_interdire_modification() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{MESSAGE}' USING ERRCODE = 'insufficient_privilege';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute(
            "CREATE TRIGGER journal_audit_ajout_seul BEFORE UPDATE OR DELETE ON journal_audit "
            "FOR EACH ROW EXECUTE FUNCTION journal_audit_interdire_modification()"
        )
        op.execute(
            "CREATE TRIGGER journal_audit_sans_truncate BEFORE TRUNCATE ON journal_audit "
            "FOR EACH STATEMENT EXECUTE FUNCTION journal_audit_interdire_modification()"
        )
    elif dialecte == "sqlite":
        op.execute(f"CREATE TRIGGER journal_audit_sans_update BEFORE UPDATE ON journal_audit BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END")
        op.execute(f"CREATE TRIGGER journal_audit_sans_delete BEFORE DELETE ON journal_audit BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END")


def downgrade() -> None:
    dialecte = op.get_bind().dialect.name
    if dialecte == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS journal_audit_sans_truncate ON journal_audit")
        op.execute("DROP TRIGGER IF EXISTS journal_audit_ajout_seul ON journal_audit")
        op.execute("DROP FUNCTION IF EXISTS journal_audit_interdire_modification()")
    elif dialecte == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS journal_audit_sans_update")
        op.execute("DROP TRIGGER IF EXISTS journal_audit_sans_delete")
