"""Tests unitaires - hachage des mots de passe (section 5)."""
from app.core.security import hash_password, verify_password


def test_hash_password_produit_un_hachage_different_du_mot_de_passe():
    hache = hash_password("MonMotDePasse123!")
    assert hache != "MonMotDePasse123!"


def test_verify_password_accepte_le_bon_mot_de_passe():
    hache = hash_password("MonMotDePasse123!")
    assert verify_password("MonMotDePasse123!", hache) is True


def test_verify_password_rejette_un_mauvais_mot_de_passe():
    hache = hash_password("MonMotDePasse123!")
    assert verify_password("AutreChose", hache) is False
