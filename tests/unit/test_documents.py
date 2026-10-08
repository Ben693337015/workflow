"""
Tests unitaires - génération de la fiche de confirmation d'absence
(dernier maillon du circuit congés, CDC fonctionnel section 3).
"""
import uuid

from app.models.demande import Demande
from app.models.enums import RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.services.documents import generer_fiche_confirmation_absence


def test_generer_fiche_confirmation_produit_un_pdf_valide():
    employe = Utilisateur(
        id=uuid.uuid4(), email="x@example.com", mot_de_passe_hash="h",
        nom_complet="Karim Fofana", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    type_conge = TypeConge(id=uuid.uuid4(), code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    demande = Demande(
        id=uuid.uuid4(), processus=TypeProcessus.CONGES, demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"date_debut": "2026-06-01", "date_fin": "2026-06-03", "type_conge_id": str(type_conge.id)},
        statut_global=StatutDemande.TERMINEE,
    )

    pdf = generer_fiche_confirmation_absence(demande, employe, type_conge, 3)

    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


def test_generer_fiche_confirmation_inclut_les_informations_cles(tmp_path):
    import subprocess
    from datetime import UTC, datetime

    employe = Utilisateur(
        id=uuid.uuid4(), email="x@example.com", mot_de_passe_hash="h",
        nom_complet="Awa Ndiaye", service="Comptabilité", role=RoleUtilisateur.EMPLOYE,
    )
    manager = Utilisateur(
        id=uuid.uuid4(), email="m@example.com", mot_de_passe_hash="h",
        nom_complet="Karim Fofana", service="Comptabilité", role=RoleUtilisateur.MANAGER,
    )
    type_conge = TypeConge(id=uuid.uuid4(), code="maladie", nom="Congé maladie", taux_acquisition_jours_mois=0)
    demande = Demande(
        id=uuid.uuid4(), processus=TypeProcessus.CONGES, demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"date_debut": "2026-09-01", "date_fin": "2026-09-05", "type_conge_id": str(type_conge.id)},
        statut_global=StatutDemande.TERMINEE,
    )
    date_approbation = datetime(2026, 9, 6, 14, 30, tzinfo=UTC)

    pdf = generer_fiche_confirmation_absence(
        demande, employe, type_conge, 5, manager=manager, date_approbation=date_approbation
    )

    fichier_pdf = tmp_path / "fiche.pdf"
    fichier_pdf.write_bytes(pdf)
    # Le contenu du PDF est compressé (FlateDecode) : une recherche sur les
    # octets bruts échoue systématiquement. On extrait le texte réellement
    # rendu via pdftotext (poppler-utils, déjà une dépendance de l'outillage
    # PDF du projet) plutôt que d'écrire une assertion qui ne teste rien.
    texte = subprocess.run(
        ["pdftotext", str(fichier_pdf), "-"], capture_output=True, text=True, check=True
    ).stdout

    assert "Awa Ndiaye" in texte
    assert "Comptabilité" in texte
    assert "Congé maladie" in texte
    assert "5 jour" in texte
    assert str(demande.id) in texte
    # Ecart intégré : bloc de signature avec le nom du manager approbateur
    # et la date d'approbation.
    assert "Karim Fofana" in texte
    assert "06/09/2026" in texte


def test_generer_fiche_confirmation_sans_manager_utilise_un_libelle_de_repli(tmp_path):
    """Cas défensif : ne doit jamais planter si le manager n'a pas pu être résolu."""
    import subprocess

    employe = Utilisateur(
        id=uuid.uuid4(), email="x@example.com", mot_de_passe_hash="h",
        nom_complet="Sans Manager", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    type_conge = TypeConge(id=uuid.uuid4(), code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    demande = Demande(
        id=uuid.uuid4(), processus=TypeProcessus.CONGES, demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"date_debut": "2026-06-01", "date_fin": "2026-06-01", "type_conge_id": str(type_conge.id)},
        statut_global=StatutDemande.TERMINEE,
    )

    pdf = generer_fiche_confirmation_absence(demande, employe, type_conge, 1)

    fichier_pdf = tmp_path / "fiche.pdf"
    fichier_pdf.write_bytes(pdf)
    texte = subprocess.run(
        ["pdftotext", str(fichier_pdf), "-"], capture_output=True, text=True, check=True
    ).stdout

    assert "Manager introuvable" in texte
    assert "date inconnue" in texte
