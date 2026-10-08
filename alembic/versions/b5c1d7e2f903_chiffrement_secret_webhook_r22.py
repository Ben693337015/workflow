"""chiffrement au repos du secret des abonnements webhook (R22)

Revision ID: b5c1d7e2f903
Revises: a47ac6bac2da
Create Date: 2026-09-29 19:10:00.000000

Deux operations :
1. elargit `abonnements_webhook.secret_hmac` (255 -> 512) : une valeur chiffree est ~1,8 fois plus
   longue que le secret en clair ;
2. chiffre les secrets DEJA stockes en clair (ceux qui portent deja le prefixe `fernet:` sont
   laisses tels quels : la migration est rejouable).

Prerequis a l'execution : la cle de chiffrement (WEBHOOK_ENCRYPTION_KEY, ou a defaut SECRET_KEY) doit
etre celle que l'application utilisera ensuite. La changer apres cette migration rendrait les
secrets illisibles.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.chiffrement import chiffrer_secret, dechiffrer_secret

revision: str = "b5c1d7e2f903"
down_revision: Union[str, None] = "a47ac6bac2da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_abonnements = sa.table(
    "abonnements_webhook",
    sa.column("id", sa.Uuid()),
    sa.column("secret_hmac", sa.String()),
)


def upgrade() -> None:
    with op.batch_alter_table("abonnements_webhook") as batch_op:
        batch_op.alter_column(
            "secret_hmac", existing_type=sa.String(length=255), type_=sa.String(length=512), existing_nullable=False
        )
    connexion = op.get_bind()
    for ligne in connexion.execute(sa.select(_abonnements)).fetchall():
        chiffre = chiffrer_secret(ligne.secret_hmac)  # idempotent
        if chiffre != ligne.secret_hmac:
            connexion.execute(
                sa.update(_abonnements).where(_abonnements.c.id == ligne.id).values(secret_hmac=chiffre)
            )


def downgrade() -> None:
    connexion = op.get_bind()
    for ligne in connexion.execute(sa.select(_abonnements)).fetchall():
        clair = dechiffrer_secret(ligne.secret_hmac)
        if clair != ligne.secret_hmac:
            connexion.execute(sa.update(_abonnements).where(_abonnements.c.id == ligne.id).values(secret_hmac=clair))
    with op.batch_alter_table("abonnements_webhook") as batch_op:
        batch_op.alter_column(
            "secret_hmac", existing_type=sa.String(length=512), type_=sa.String(length=255), existing_nullable=False
        )
