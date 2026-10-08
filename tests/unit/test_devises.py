"""Conversion de devises (decision du 28/09) : exactitude monetaire et choix du taux par date."""
from datetime import date

import pytest

from app.models.taux_change import TauxChange
from app.services import devises


async def _taux(db, devise, taux, date_effet):
    db.add(TauxChange(devise=devise, taux=taux, date_effet=date_effet))
    await db.commit()


async def test_la_devise_de_reference_n_exige_aucun_taux(db_session):
    c = await devises.convertir(db_session, 100.0, "EUR", date(2026, 3, 1))
    assert (c.taux, c.montant_reference, c.date_effet) == (1.0, 100.0, None)


async def test_une_devise_absente_est_la_devise_de_reference(db_session):
    assert (await devises.convertir(db_session, 42.5, None, date(2026, 3, 1))).montant_reference == 42.5


async def test_conversion_avec_un_taux(db_session):
    await _taux(db_session, "USD", 0.92, date(2026, 1, 1))
    c = await devises.convertir(db_session, 800.0, "usd", date(2026, 3, 1))  # casse normalisee
    assert (c.devise, c.taux, c.montant_reference, c.date_effet) == ("USD", 0.92, 736.0, date(2026, 1, 1))


async def test_le_taux_retenu_est_le_plus_recent_a_la_date_de_la_depense(db_session):
    await _taux(db_session, "USD", 0.90, date(2026, 1, 1))
    await _taux(db_session, "USD", 0.95, date(2026, 6, 1))

    avant = await devises.convertir(db_session, 100.0, "USD", date(2026, 5, 31))
    le_jour = await devises.convertir(db_session, 100.0, "USD", date(2026, 6, 1))   # date d'effet incluse
    apres = await devises.convertir(db_session, 100.0, "USD", date(2026, 12, 31))

    assert (avant.taux, le_jour.taux, apres.taux) == (0.90, 0.95, 0.95)


async def test_pas_de_taux_avant_le_premier_ou_devise_inconnue_erreur_explicite(db_session):
    await _taux(db_session, "USD", 0.92, date(2026, 6, 1))

    with pytest.raises(devises.TauxIntrouvable, match=r"USD au 01/03/2026"):
        await devises.convertir(db_session, 10.0, "USD", date(2026, 3, 1))
    with pytest.raises(devises.TauxIntrouvable, match="GBP"):
        await devises.convertir(db_session, 10.0, "GBP", date(2026, 7, 1))


async def test_arrondi_commercial_demi_vers_le_haut_sans_derive_de_flottants(db_session):
    # 0.1 + 0.2 != 0.3 en flottants ; et 2.675 s'arrondit a 2.67 en float, 2.68 en arrondi commercial.
    await _taux(db_session, "XAF", 0.00152449, date(2026, 1, 1))
    await _taux(db_session, "AAA", 1.0, date(2026, 1, 1))
    assert (await devises.convertir(db_session, 2.675, "AAA", date(2026, 3, 1))).montant_reference == 2.68
    assert (await devises.convertir(db_session, 500000.0, "XAF", date(2026, 3, 1))).montant_reference == 762.25


async def test_le_taux_est_fige_dans_le_resultat_et_les_montants_sont_coherents(db_session):
    await _taux(db_session, "USD", 0.9, date(2026, 1, 1))
    c = await devises.convertir(db_session, 1000.0, "USD", date(2026, 3, 1))
    assert c.montant == 1000.0 and c.montant_reference == 900.0


def test_lecture_des_donnees_anterieures_sans_devise():
    ancien = {"montant": 120.0, "categorie": "Repas"}
    assert devises.devise_de(ancien) == "EUR"
    assert devises.montant_reference(ancien, "montant") == 120.0  # lu comme deja en devise de reference
    assert devises.libelle_montant(ancien, "montant") == "120.0 €"


def test_lecture_des_donnees_converties_utilise_la_valeur_figee_pas_le_montant():
    converti = {"montant": 800.0, "devise": "USD", "taux_applique": 0.92, "montant_reference": 736.0}
    assert devises.montant_reference(converti, "montant") == 736.0
    assert devises.libelle_montant(converti, "montant") == "800.0 USD (≈ 736.0 €)"


def test_formatage_du_symbole():
    assert devises.formater(10.5, "EUR") == "10.5 €"
    assert devises.formater(10.5, "xaf") == "10.5 XAF"
