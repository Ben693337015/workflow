"""Calcul des montants d'un bon de commande (TVA par ligne et par taux, decision du 28/09)."""
from app.services import facturation


def test_une_ligne_simple():
    lignes = [{"description": "Licence", "montant_ht": 100.0, "taux_tva": 20.0}]
    r = facturation.totaux_depuis_lignes(lignes)
    assert r.detail_par_ligne is True
    assert (r.lignes[0].montant_tva, r.lignes[0].montant_ttc) == (20.0, 120.0)
    assert (r.total_ht, r.total_tva, r.total_ttc) == (100.0, 20.0, 120.0)


def test_plusieurs_lignes_taux_differents_regroupees_par_taux():
    lignes = [
        {"description": "Materiel", "montant_ht": 1000.0, "taux_tva": 20.0},
        {"description": "Livre technique", "montant_ht": 50.0, "taux_tva": 5.5},
        {"description": "Presse", "montant_ht": 30.0, "taux_tva": 2.1},
        {"description": "Autre materiel", "montant_ht": 200.0, "taux_tva": 20.0},  # meme taux que la 1ere : regroupe
    ]
    r = facturation.totaux_depuis_lignes(lignes)

    assert len(r.lignes) == 4  # le detail par ligne reste intact
    assert [(s.taux_tva, s.montant_ht) for s in r.par_taux] == [(2.1, 30.0), (5.5, 50.0), (20.0, 1200.0)]  # regroupe et trie
    assert r.total_ht == 1280.0
    assert r.total_tva == round(1200 * 0.20 + 50 * 0.055 + 30 * 0.021, 2)
    assert r.total_ttc == round(r.total_ht + r.total_tva, 2)


def test_taux_zero_tva_nulle_sans_erreur():
    r = facturation.totaux_depuis_lignes([{"description": "Export hors UE", "montant_ht": 500.0, "taux_tva": 0.0}])
    assert (r.total_tva, r.total_ttc) == (0.0, 500.0)


def test_arrondi_commercial_sans_derive_de_flottants():
    # 33.335 * 0.20 = 6.667 -> arrondi commercial 6.67 ; un calcul en float pur derive facilement ici.
    r = facturation.totaux_depuis_lignes([{"description": "x", "montant_ht": 33.335, "taux_tva": 20.0}])
    assert r.lignes[0].montant_tva == 6.67
    assert r.lignes[0].montant_ttc == 40.0


def test_somme_ttc_pour_deriver_le_budget_engage():
    lignes = [
        {"description": "A", "montant_ht": 100.0, "taux_tva": 20.0},
        {"description": "B", "montant_ht": 50.0, "taux_tva": 5.5},
    ]
    assert facturation.somme_ttc(lignes) == round(100 * 1.20 + 50 * 1.055, 2)


def test_mode_legacy_identique_au_calcul_precedent():
    r = facturation.totaux_depuis_montant_global(120.0, 20.0)
    assert r.detail_par_ligne is False and r.lignes == []
    assert (r.total_ht, r.total_tva, r.total_ttc) == (100.0, 20.0, 120.0)
    assert r.par_taux == [facturation.SousTotalTaux(taux_tva=20.0, montant_ht=100.0, montant_tva=20.0, montant_ttc=120.0)]


def test_mode_legacy_taux_non_entier():
    r = facturation.totaux_depuis_montant_global(105.5, 5.5)
    assert r.total_ht == 100.0 and r.total_tva == 5.5
