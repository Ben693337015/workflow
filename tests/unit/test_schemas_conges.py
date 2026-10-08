"""Tests unitaires - validation du formulaire de demande de congés (section 6)."""
import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.conges import DemandeCongesCreate, DemandeCongesModifier

TYPE_CONGE_ID = uuid.uuid4()


def test_schema_accepte_des_dates_coherentes():
    demande = DemandeCongesCreate(
        type_conge_id=TYPE_CONGE_ID,
        date_debut=date(2026, 6, 1),
        date_fin=date(2026, 6, 5),
    )
    assert demande.date_fin >= demande.date_debut


def test_schema_rejette_une_date_de_fin_anterieure_a_la_date_de_debut():
    with pytest.raises(ValidationError, match="posterieure ou egale"):
        DemandeCongesCreate(
            type_conge_id=TYPE_CONGE_ID,
            date_debut=date(2026, 6, 5),
            date_fin=date(2026, 6, 1),
        )


def test_schema_accepte_une_seule_journee():
    demande = DemandeCongesCreate(
        type_conge_id=TYPE_CONGE_ID,
        date_debut=date(2026, 6, 1),
        date_fin=date(2026, 6, 1),
    )
    assert demande.date_debut == demande.date_fin


def test_schema_rejette_un_type_conge_id_invalide():
    with pytest.raises(ValidationError):
        DemandeCongesCreate(
            type_conge_id="pas-un-uuid",
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 1),
        )


def test_schema_modification_accepte_des_champs_partiels():
    modification = DemandeCongesModifier(date_fin=date(2026, 6, 10))
    assert modification.date_debut is None
    assert modification.date_fin == date(2026, 6, 10)


def test_schema_modification_rejette_incoherence_si_les_deux_dates_fournies():
    with pytest.raises(ValidationError, match="posterieure ou egale"):
        DemandeCongesModifier(date_debut=date(2026, 6, 10), date_fin=date(2026, 6, 1))
