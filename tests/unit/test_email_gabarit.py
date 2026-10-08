"""Gabarit commun des e-mails : habillage, echappement, boutons exploitables, contraintes des clients de messagerie."""
import re

from app.services import email_gabarit as g


def test_envelopper_produit_un_document_complet_avec_le_sujet_pour_titre():
    html = g.envelopper("🎉 Votre demande est approuvée", g.paragraphe("Bonjour,"))
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert "<title>🎉 Votre demande est approuvée</title>" in html and "<h1" in html
    assert "Plateforme Workflows" in html and "ne pas y répondre" in html


def test_aucune_feuille_de_style_ni_script_ni_accolade_pour_les_clients_de_messagerie():
    html = g.envelopper("Titre", g.carte([("A", "b")]) + g.boutons(("Ok", "http://x/decisions/t", "primaire")))
    assert "<style" not in html and "<script" not in html and "{" not in html and "}" not in html
    assert "var(--" not in html


def test_les_textes_utilisateur_sont_echappes():
    piege = "<i>x</i> & \"y\""
    html = g.envelopper(piege, g.encart(piege, piege) + g.carte([(piege, piege)]) + g.boutons((piege, "http://x/y", "danger")))
    assert "<i>" not in html and "&lt;i&gt;" in html


def test_les_boutons_gardent_le_motif_href_puis_libelle_et_trois_styles():
    corps = g.boutons(("Approuver", "http://h/decisions/abc", "primaire"), ("Refuser", "http://h/decisions/def", "danger"),
                      ("Voir", "http://h/z", "secondaire"))
    assert re.findall(r"href='[^']*/decisions/([A-Za-z0-9_\-]+)'>([^<]+)</a>", corps) == [("abc", "Approuver"), ("def", "Refuser")]
    assert corps.count("<a ") == 3 and "#b42318" in corps and "#0b7f72" in corps


def test_carte_omet_les_valeurs_vides_et_encart_choisit_son_ton():
    assert "Vide" not in g.carte([("Vide", ""), ("Plein", "1")]) and "Plein" in g.carte([("Plein", "1")])
    assert "#b42318" in g.encart("motif", "Motif", "refus") and "#067647" in g.encart("ok", "", "succes")
