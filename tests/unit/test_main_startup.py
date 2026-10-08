"""
Verifie l'avertissement de demarrage sur RESEND_API_KEY vide (revue du
27/09) - le README affirmait a tort qu'un demarrage sans cette variable
plantait ; ce n'est pas le cas (valeur par defaut vide, deliberee), d'ou
l'ajout de cet avertissement explicite plutot qu'un crash silencieusement
absent.
"""
import importlib

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _nettoyer_apres(monkeypatch):
    yield
    get_settings.cache_clear()


def _recharger_main():
    import app.main as main_module

    get_settings.cache_clear()
    importlib.reload(main_module)
    return main_module


async def test_avertissement_emis_si_resend_api_key_vide(monkeypatch, caplog):
    # Chaine vide (et non delenv) : une variable d'environnement vide l'emporte sur le fichier .env, alors qu'une
    # variable absente laisserait la valeur du .env copie depuis .env.example (test dependant de l'installation).
    monkeypatch.setenv("RESEND_API_KEY", "")
    with caplog.at_level("WARNING", logger="app.main"):
        _recharger_main()

    messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("RESEND_API_KEY" in m for m in messages)


async def test_aucun_avertissement_si_resend_api_key_definie(monkeypatch, caplog):
    monkeypatch.setenv("RESEND_API_KEY", "re_une_vraie_cle")
    with caplog.at_level("WARNING", logger="app.main"):
        _recharger_main()

    messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert not any("RESEND_API_KEY" in m for m in messages)
