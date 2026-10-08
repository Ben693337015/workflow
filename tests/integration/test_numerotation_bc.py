"""
Correction R21 : le numero de bon de commande venait d'un comptage des achats termines de l'annee,
sans garantie d'unicite. Il vient maintenant d'un compteur par exercice verrouille, avec contraintes
d'unicite en base.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bon_commande import BonCommande, CompteurBonCommande
from app.models.demande import Demande
from app.models.enums import RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.user import Utilisateur
from app.services import numerotation_bc


async def _demande_achat(db_session, utilisateur) -> Demande:
    demande = Demande(
        processus=TypeProcessus.ACHATS, demandeur_id=utilisateur.id, initiee_par_id=utilisateur.id,
        donnees={"tiers": "X", "objet": "Y", "budget_engage": 100}, statut_global=StatutDemande.TERMINEE,
    )
    db_session.add(demande)
    await db_session.flush()
    return demande


@pytest.fixture
async def utilisateur(db_session):
    u = Utilisateur(
        email="a@example.com", mot_de_passe_hash="h", nom_complet="A", service="S", role=RoleUtilisateur.EMPLOYE
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def test_les_numeros_sont_sequentiels_et_uniques(db_session, utilisateur):
    numeros = [
        await numerotation_bc.attribuer_numero(db_session, await _demande_achat(db_session, utilisateur), 2026)
        for _ in range(3)
    ]
    assert numeros == ["BC-2026-0001", "BC-2026-0002", "BC-2026-0003"]


async def test_attribuer_deux_fois_a_la_meme_demande_renvoie_le_meme_numero(db_session, utilisateur):
    demande = await _demande_achat(db_session, utilisateur)
    premier = await numerotation_bc.attribuer_numero(db_session, demande, 2026)
    second = await numerotation_bc.attribuer_numero(db_session, demande, 2026)
    assert premier == second == "BC-2026-0001"
    bons = (await db_session.execute(select(BonCommande))).scalars().all()
    assert len(bons) == 1  # aucun rang consomme pour rien


async def test_chaque_exercice_a_son_propre_compteur(db_session, utilisateur):
    n2026 = await numerotation_bc.attribuer_numero(db_session, await _demande_achat(db_session, utilisateur), 2026)
    n2027 = await numerotation_bc.attribuer_numero(db_session, await _demande_achat(db_session, utilisateur), 2027)
    assert (n2026, n2027) == ("BC-2026-0001", "BC-2027-0001")


async def test_le_compteur_repart_apres_les_numeros_deja_attribues(db_session, utilisateur):
    """Cas de la reprise apres migration : le compteur est amorce au plus haut rang existant."""
    db_session.add(CompteurBonCommande(exercice=2026, dernier_rang=41))
    await db_session.commit()
    numero = await numerotation_bc.attribuer_numero(db_session, await _demande_achat(db_session, utilisateur), 2026)
    assert numero == "BC-2026-0042"


async def test_la_base_refuse_un_doublon_meme_sans_le_verrou(db_session, utilisateur):
    """Garde-fou : meme si le compteur etait contourne, la contrainte d'unicite l'interdit."""
    d1 = await _demande_achat(db_session, utilisateur)
    d2 = await _demande_achat(db_session, utilisateur)
    db_session.add(BonCommande(demande_id=d1.id, exercice=2026, rang=1, numero_sequentiel="BC-2026-0001"))
    await db_session.flush()
    db_session.add(BonCommande(demande_id=d2.id, exercice=2026, rang=1, numero_sequentiel="BC-2026-0001"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
