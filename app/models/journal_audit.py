"""Entite Journal d'audit : append-only, horodate et attribue (section 4 / 14.3)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DDL, DateTime, ForeignKey, JSON, String, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JournalAudit(Base):
    __tablename__ = "journal_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    acteur_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=True
    )
    cible_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # Ecart corrige (revue du 15/09) : nullable desormais - une action systeme
    # (ex. tentative d'utilisation d'un jeton de decision inconnu/falsifie,
    # section 9 "Securite du lien de decision") peut ne se rattacher a aucune
    # entite resolue. Le CDC (section 4.3) est explicite sur ce point pour
    # les trois FK equivalentes de journal_audit.
    cible_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    horodate_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class JournalImmuable(Exception):
    """Toute tentative de modifier ou supprimer une entree du journal d'audit."""


# --- Inalterabilite (CDC fonctionnel 2.4 : "consignee de facon inalterable" ; CDC technique
# 14.3 : "append-only en base, sans possibilite de modification ou de suppression a
# posteriori par un compte applicatif standard"). Ecart trouve par l'audit de conformite du
# 28/09 : cette table portait seulement une note "a mettre en oeuvre" - rien ne l'imposait.
#
# Trois niveaux de defense :
#  1. declencheurs en base (ci-dessous) : refusent UPDATE, DELETE et TRUNCATE quel que soit le
#     compte, proprietaire de la table compris - seul un DDL explicite (DISABLE TRIGGER, DROP
#     TRIGGER) les retire, ce qu'un compte applicatif ordinaire ne doit jamais pouvoir faire :
#     l'application ne doit PAS se connecter avec le proprietaire de la table (voir README) ;
#  2. garde cote ORM : echoue avant meme d'atteindre la base ;
#  3. creation automatique lors d'un create_all (tests, developpement) ; en production, la
#     migration Alembic 'journal_audit_ajout_seul' cree les memes declencheurs.
_MESSAGE = "journal_audit est en ajout seul : UPDATE, DELETE et TRUNCATE interdits"

_PG_FONCTION = f"""
CREATE OR REPLACE FUNCTION journal_audit_interdire_modification() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '{_MESSAGE}' USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql
"""
_PG_LIGNES = (
    "CREATE TRIGGER journal_audit_ajout_seul BEFORE UPDATE OR DELETE ON journal_audit "
    "FOR EACH ROW EXECUTE FUNCTION journal_audit_interdire_modification()"
)
_PG_TRUNCATE = (
    "CREATE TRIGGER journal_audit_sans_truncate BEFORE TRUNCATE ON journal_audit "
    "FOR EACH STATEMENT EXECUTE FUNCTION journal_audit_interdire_modification()"
)
_SQLITE_UPDATE = (
    f"CREATE TRIGGER journal_audit_sans_update BEFORE UPDATE ON journal_audit "
    f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END"
)
_SQLITE_DELETE = (
    f"CREATE TRIGGER journal_audit_sans_delete BEFORE DELETE ON journal_audit "
    f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END"
)

_table = JournalAudit.__table__
for _sql in (_PG_FONCTION, _PG_LIGNES, _PG_TRUNCATE):
    event.listen(_table, "after_create", DDL(_sql.replace("%", "%%")).execute_if(dialect="postgresql"))
for _sql in (_SQLITE_UPDATE, _SQLITE_DELETE):
    event.listen(_table, "after_create", DDL(_sql).execute_if(dialect="sqlite"))


@event.listens_for(JournalAudit, "before_update")
def _refuser_update(_mapper, _connection, _cible):
    raise JournalImmuable(_MESSAGE)


@event.listens_for(JournalAudit, "before_delete")
def _refuser_delete(_mapper, _connection, _cible):
    raise JournalImmuable(_MESSAGE)
