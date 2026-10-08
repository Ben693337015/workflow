"""
Gabarit commun des e-mails de la plateforme.

Un seul habillage pour tous les messages (demande, notification, rappel, invitation...) : en-tête de marque, titre,
contenu, boutons d'action, pied de page. Il est appliqué par `email_service.envoyer_email` : les appelants ne
fournissent que le CONTENU (paragraphes, `carte`, `encart`, `boutons`) et un sujet qui sert aussi de titre.

Contraintes des clients de messagerie (Gmail, Outlook, applications mobiles) :
- mise en page en tableaux, styles UNIQUEMENT en ligne (pas de <style>, pas de variables CSS, pas de JavaScript) ;
- largeur 600 px maximum, lisible sur téléphone ; couleurs a fort contraste ; emojis en texte (aucune image
  distante : rien a bloquer, rien a pister) ;
- tout texte saisi par un utilisateur est echappe ici (`carte`, `encart`) ou par l'appelant (`paragraphe` recoit du HTML).
"""
from html import escape

COULEUR_MARQUE = "#0b7f72"
COULEUR_MARQUE_SOMBRE = "#08665b"

# ton -> (couleur d'accent, fond doux) : succes, attention, refus, information.
_TONS = {
    "info": ("#0b7f72", "#e6f5f2"),
    "succes": ("#067647", "#ecfdf3"),
    "attention": ("#8a5a12", "#fbf1de"),
    "refus": ("#b42318", "#fef3f2"),
}

_POLICE = "'Segoe UI',Helvetica,Arial,sans-serif"


def paragraphe(contenu_html: str) -> str:
    """Paragraphe courant. `contenu_html` est du HTML DEJA echappe par l'appelant."""
    return f'<p style="margin:0 0 14px 0;font-size:15px;line-height:1.6;color:#1f2430;">{contenu_html}</p>'


def encart(texte: str, titre: str = "", ton: str = "info", emoji: str = "") -> str:
    """Bloc mis en valeur (motif d'un refus, commentaire, note). `texte` et `titre` sont du texte brut : echappes ici."""
    accent, fond = _TONS.get(ton, _TONS["info"])
    entete = (
        f'<div style="font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:{accent};'
        f'margin-bottom:4px;">{emoji + " " if emoji else ""}{escape(titre)}</div>'
        if titre
        else ""
    )
    return (
        f'<div style="border-left:4px solid {accent};background:{fond};border-radius:6px;padding:12px 14px;'
        f'margin:4px 0 16px 0;font-size:14.5px;line-height:1.55;color:#1f2430;">{entete}{escape(texte)}</div>'
    )


def carte(lignes: list[tuple[str, str]]) -> str:
    """Fiche « libelle : valeur ». Libelles et valeurs sont du texte brut : echappes ici. Les valeurs vides sont omises."""
    corps = "".join(
        f'<tr><td style="padding:9px 14px;font-size:13px;color:#5b6270;width:38%;border-bottom:1px solid #eceef3;">'
        f'{escape(libelle)}</td><td style="padding:9px 14px;font-size:14px;font-weight:600;color:#1f2430;'
        f'border-bottom:1px solid #eceef3;">{escape(str(valeur))}</td></tr>'
        for libelle, valeur in lignes
        if valeur not in (None, "")
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e1e4ea;'
        f'border-radius:10px;border-collapse:separate;margin:4px 0 18px 0;background:#fafbfc;">{corps}</table>'
    )


def bouton(libelle: str, url: str, style: str = "primaire") -> str:
    """
    Bouton d'action. L'attribut href est place EN DERNIER, juste avant le libelle : le motif
    `href='...'>Libelle</a>` reste exploitable tel quel (tests, lecteurs de liens). Le libelle ne contient jamais
    d'emoji pour la meme raison.
    """
    if style == "danger":
        couleurs = "background:#ffffff;color:#b42318;border:2px solid #b42318;"
    elif style == "secondaire":
        couleurs = "background:#ffffff;color:#0b6b61;border:2px solid #0b7f72;"
    else:
        couleurs = f"background:{COULEUR_MARQUE};color:#ffffff;border:2px solid {COULEUR_MARQUE};"
    return (
        f'<a style="display:inline-block;{couleurs}padding:11px 26px;margin:0 8px 8px 0;border-radius:10px;'
        f'font-size:15px;font-weight:700;text-decoration:none;" href=\'{url}\'>{escape(libelle)}</a>'
    )


def boutons(*liens: tuple[str, str, str]) -> str:
    """Rangee de boutons : chaque element est (libelle, url, style)."""
    return f'<div style="margin:6px 0 14px 0;">{"".join(bouton(*lien) for lien in liens)}</div>'


def note(texte_html: str) -> str:
    """Remarque discrete sous les boutons."""
    return f'<p style="margin:0 0 6px 0;font-size:12.5px;line-height:1.5;color:#6b7180;">{texte_html}</p>'


def envelopper(sujet: str, contenu_html: str) -> str:
    """Document HTML complet : le `sujet` devient le titre du message, `contenu_html` le corps."""
    titre = escape(sujet)
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{titre}</title></head>"
        f'<body style="margin:0;padding:0;background:#eef1f6;font-family:{_POLICE};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f6;">'
        '<tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e1e4ea;">'
        # en-tete de marque
        f'<tr><td style="background:{COULEUR_MARQUE_SOMBRE};padding:18px 28px;">'
        f'<span style="font-size:15px;font-weight:700;color:#ffffff;letter-spacing:.01em;">'
        "&#10003;&nbsp; Plateforme Workflows</span>"
        '<span style="display:block;font-size:12px;color:#bfe9e2;margin-top:2px;">'
        "Congés · Notes de frais · Achats</span></td></tr>"
        # titre
        '<tr><td style="padding:26px 28px 6px 28px;">'
        f'<h1 style="margin:0;font-size:21px;line-height:1.35;color:#12151c;font-weight:700;">{titre}</h1></td></tr>'
        # contenu
        f'<tr><td style="padding:14px 28px 12px 28px;">{contenu_html}</td></tr>'
        # pied
        '<tr><td style="padding:18px 28px 24px 28px;border-top:1px solid #eceef3;background:#fafbfc;">'
        '<p style="margin:0;font-size:12px;line-height:1.55;color:#6b7180;">'
        "Ce message est envoyé automatiquement par la Plateforme Workflows, merci de ne pas y répondre. "
        "Une question ? Contactez directement votre manager ou le service RH."
        "</p></td></tr>"
        "</table>"
        '<p style="margin:14px 0 0 0;font-size:11.5px;color:#8a90a0;">'
        "Vous recevez ce message car votre adresse est associée à un compte de la plateforme.</p>"
        "</td></tr></table></body></html>"
    )
