"""
Génération de documents (section 12 du CDC technique).

Fiche de confirmation d'absence : dernier maillon du circuit congés
("Fiche de confirmation d'absence et mise à jour de l'agenda de l'équipe",
CDC fonctionnel, section 3, tableau des cas d'usage).

Choix retenu : génération à la demande (à chaque téléchargement) plutôt que
stockage persistant. Le document est entièrement reconstructible à partir
des données déjà en base (Demande, Utilisateur, TypeConge) - stocker un
fichier généré n'apporterait rien tant que le stockage de fichiers réel
(NubiS3, section 3.3) n'est pas raccordé (point encore non tranché, voir
le README, section "Points restant à trancher"). Le jour où NubiS3 est
disponible, ce module change de forme interne mais pas de contrat
(toujours des octets PDF en sortie) - aucun autre code n'a besoin de changer.
"""
import base64
from datetime import UTC, date, datetime
from string import Template
from html import escape

import weasyprint

from app.core.config import get_settings
from app.services import devises, facturation
from app.models.demande import Demande
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur

settings = get_settings()

_GABARIT_FICHE_CONFIRMATION = Template("""
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: A4; margin: 0; }
  body { font-family: Helvetica, Arial, sans-serif; color: #1a1f2b; margin: 0; font-size: 12.5px; }
  .bandeau { background: #08665b; color: #ffffff; padding: 26px 48px 22px 48px; }
  .bandeau table { width: 100%; border-collapse: collapse; }
  .bandeau td { padding: 0; vertical-align: middle; }
  .marque { font-size: 15px; font-weight: bold; letter-spacing: 0.3px; }
  .marque-sous { font-size: 10px; color: #bfe9e2; margin-top: 2px; }
  .ref-haut { text-align: right; font-size: 10px; color: #bfe9e2; }
  .ref-haut strong { color: #ffffff; font-size: 11px; }
  .page { padding: 30px 48px 0 48px; }
  .surtitre { font-size: 10.5px; letter-spacing: 1.6px; text-transform: uppercase; color: #0b7f72; font-weight: bold; margin: 0 0 6px 0; }
  h1 { font-size: 27px; margin: 0 0 12px 0; color: #12151c; letter-spacing: -0.3px; }
  .pastille { display: inline-block; background: #e6f5f2; color: #08665b; border: 1px solid #9fd8cf; border-radius: 14px;
              padding: 5px 14px 5px 12px; font-size: 11px; font-weight: bold; letter-spacing: 1px; }
  .pastille .coche { display: inline-block; width: 4px; height: 8px; border-right: 2px solid #08665b; border-bottom: 2px solid #08665b;
                     transform: rotate(45deg); margin: 0 9px 2px 3px; }
  .employe { margin: 24px 0 0 0; border: 1px solid #dfe3ec; border-radius: 12px; background: #fafbfc; width: 100%; border-collapse: separate; }
  .employe td { padding: 16px 18px; vertical-align: middle; }
  .initiales { width: 44px; height: 44px; border-radius: 22px; background: #08665b; color: #fff; text-align: center; line-height: 44px;
               font-size: 16px; font-weight: bold; }
  .employe .nom { font-size: 17px; font-weight: bold; color: #12151c; }
  .employe .service { font-size: 12px; color: #5b6270; margin-top: 2px; }
  h2 { font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase; color: #5b6270; margin: 26px 0 10px 0; }
  .periode { width: 100%; border-collapse: separate; border-spacing: 10px 0; margin: 0 -10px; }
  .periode td { background: #f3f9f8; border: 1px solid #cfe9e5; border-radius: 10px; padding: 14px 16px; vertical-align: top; }
  .periode .petit { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: #5b6270; }
  .periode .grand { font-size: 17px; font-weight: bold; color: #08665b; margin-top: 4px; }
  .periode .jour { font-size: 11.5px; color: #46453F; margin-top: 2px; }
  .periode .duree { background: #08665b; border-color: #08665b; }
  .periode .duree .petit, .periode .duree .jour { color: #bfe9e2; }
  .periode .duree .grand { color: #ffffff; font-size: 24px; }
  table.details { width: 100%; border-collapse: collapse; }
  table.details td { padding: 9px 4px; border-bottom: 1px solid #e6e8ee; font-size: 12.5px; }
  table.details td.label { color: #5b6270; width: 38%; }
  table.details td.valeur { font-weight: bold; color: #12151c; }
  .commentaire { margin-top: 14px; border-left: 4px solid #0b7f72; background: #f3f9f8; padding: 10px 14px; font-size: 12px; color: #2c3340; }
  .commentaire strong { display: block; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: #08665b; margin-bottom: 3px; }
  .attestation { margin-top: 22px; font-size: 12px; line-height: 1.6; color: #2c3340; }
  .signature-zone { width: 100%; margin-top: 30px; border-collapse: collapse; }
  .signature-zone td { vertical-align: bottom; padding: 0; }
  .signature { width: 330px; }
  .signature .ligne { border-top: 1px solid #1a1f2b; margin-bottom: 6px; }
  .signature .nom { font-style: italic; font-size: 15px; font-weight: bold; margin: 0; }
  .signature .role { font-size: 11px; color: #46453F; margin: 3px 0 0 0; }
  .tampon { display: inline-block; border: 3px double #08665b; color: #08665b; border-radius: 8px; padding: 8px 18px; transform: rotate(-7deg);
            text-align: center; }
  .tampon .t1 { font-size: 17px; font-weight: bold; letter-spacing: 3px; }
  .tampon .t2 { font-size: 9px; letter-spacing: 0.5px; margin-top: 2px; }
  .pied { position: fixed; bottom: 0; left: 0; right: 0; padding: 12px 48px 16px 48px; border-top: 1px solid #dfe3ec; background: #fafbfc;
          font-size: 9.5px; color: #5b6270; }
  .pied table { width: 100%; border-collapse: collapse; }
  .pied td { padding: 0; }
  .pied .droite { text-align: right; }
</style>
</head>
<body>
  <div class="bandeau">
    <table><tr>
      <td><div class="marque">Plateforme Workflows</div><div class="marque-sous">Congés · Notes de frais · Achats</div></td>
      <td class="ref-haut">Référence du dossier<br><strong>$ref_courte</strong></td>
    </tr></table>
  </div>

  <div class="page">
    <p class="surtitre">Ressources humaines</p>
    <h1>Fiche de confirmation d'absence</h1>
    <span class="pastille"><span class="coche"></span>CONGÉ APPROUVÉ</span>

    <table class="employe"><tr>
      <td style="width:44px;"><div class="initiales">$initiales</div></td>
      <td><div class="nom">$nom_complet</div><div class="service">Employé · Service $service</div></td>
    </tr></table>

    <h2>Période d'absence</h2>
    <table class="periode"><tr>
      <td><div class="petit">Du</div><div class="grand">$date_debut</div><div class="jour">$jour_debut</div></td>
      <td><div class="petit">Au</div><div class="grand">$date_fin</div><div class="jour">$jour_fin</div></td>
      <td class="duree"><div class="petit">Durée décomptée</div><div class="grand">$nombre_jours</div><div class="jour">jour(s) décompté(s)</div></td>
    </tr></table>

    <h2>Détails de la demande</h2>
    <table class="details">
      <tr><td class="label">Type de congé</td><td class="valeur">$type_conge_nom</td></tr>
      <tr><td class="label">Durée déductible</td><td class="valeur">$nombre_jours jour(s) décompté(s), jours fériés exclus</td></tr>
      <tr><td class="label">Demande déposée le</td><td class="valeur">$date_depot</td></tr>
      <tr><td class="label">Statut</td><td class="valeur">Approuvée</td></tr>
      <tr><td class="label">Référence de la demande</td><td class="valeur">$demande_id</td></tr>
    </table>
    $bloc_commentaire

    <p class="attestation">
      Il est attesté que la demande de congé de <strong>$nom_complet</strong>, pour la période du $date_debut au $date_fin,
      a été examinée et approuvée par son responsable hiérarchique. Cette absence est enregistrée dans le planning de l'équipe
      et portée à la connaissance du service des ressources humaines.
    </p>

    <table class="signature-zone"><tr>
      <td>
        <div class="signature">
          <div class="ligne"></div>
          <p class="nom">$manager_nom</p>
          <p class="role">Manager — Approuvé électroniquement le $date_approbation</p>
        </div>
      </td>
      <td style="text-align:right;">
        <div class="tampon"><div class="t1">VALIDÉ</div><div class="t2">Approbation électronique</div></div>
      </td>
    </tr></table>
  </div>

  <div class="pied">
    <table><tr>
      <td>Document généré automatiquement le $date_generation — Plateforme d'approbation de workflows.</td>
      <td class="droite">Réf. $ref_courte</td>
    </tr></table>
  </div>
</body>
</html>
""")

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def _jour_semaine(iso: str) -> str:
    """Jour de la semaine en français (sans dépendre de la locale du serveur)."""
    try:
        return _JOURS[date.fromisoformat(iso).weekday()]
    except ValueError:
        return ""


def _date_fr(iso: str) -> str:
    """AAAA-MM-JJ -> JJ/MM/AAAA (inchangé si le format est inattendu)."""
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def generer_fiche_confirmation_absence(
    demande: Demande,
    employe: Utilisateur,
    type_conge: TypeConge,
    nombre_jours: int,
    manager: Utilisateur | None = None,
    date_approbation: datetime | None = None,
) -> bytes:
    """
    Génère la fiche de confirmation d'absence (PDF) pour une demande approuvée.

    Écart identifié et corrigé : la fiche ne mentionnait jusqu'ici que
    l'employé, sans trace du manager qui a réellement approuvé la demande -
    alors que c'est une information attendue sur un document RH de ce type.
    Ajout d'un bloc de signature (nom du manager + date d'approbation),
    sous forme de mention imprimée plutôt qu'une signature manuscrite
    capturée : le circuit congés n'a pas de rôle "Signataire" avec capture
    d'écran (contrairement aux achats, section 8 du CDC technique) -
    l'approbation elle-même (jeton + session, option B) fait déjà foi
    d'authentification. Le nom du manager est présenté en italique plutôt
    que dans une police cursive : aucune police de type manuscrit n'est
    garantie disponible sur l'image Docker de production (seules les
    dépendances système de WeasyPrint y sont installées, pas de paquet de
    polices supplémentaire) - vérifié dans ce sandbox avant d'écrire ce
    commentaire (`fc-match cursive` y résout sur une police sans-serif
    générique, même avec un jeu de polices bien plus riche que l'image
    de production).
    """
    manager_nom = escape(manager.nom_complet) if manager else "Manager introuvable"
    date_approbation_str = (
        date_approbation.strftime("%d/%m/%Y à %H:%M UTC") if date_approbation else "date inconnue"
    )

    # Ecart identifie et corrige (revue du 15/09) : nom_complet/service/nom
    # du type de conge sont des champs saisis par l'utilisateur (DRH ou
    # employe) et etaient inseres tels quels dans le HTML rendu par
    # WeasyPrint - une valeur contenant '<', '>' ou '&' pouvait casser la
    # mise en page du document (balise non fermee, structure du tableau
    # rompue). Echappees desormais comme tout contenu utilisateur insere
    # dans du HTML.
    mots = employe.nom_complet.split()
    initiales = "".join(m[0] for m in mots[:2]).upper() or "?"
    commentaire = (demande.donnees.get("commentaire") or "").strip()
    bloc_commentaire = (
        f'<div class="commentaire"><strong>Commentaire du demandeur</strong>{escape(commentaire)}</div>' if commentaire else ""
    )
    depot = getattr(demande, "creee_le", None)
    html = _GABARIT_FICHE_CONFIRMATION.substitute(
        nom_complet=escape(employe.nom_complet),
        initiales=escape(initiales),
        service=escape(employe.service),
        type_conge_nom=escape(type_conge.nom),
        date_debut=_date_fr(demande.donnees["date_debut"]),
        date_fin=_date_fr(demande.donnees["date_fin"]),
        jour_debut=_jour_semaine(demande.donnees["date_debut"]),
        jour_fin=_jour_semaine(demande.donnees["date_fin"]),
        nombre_jours=nombre_jours,
        demande_id=str(demande.id),
        ref_courte=str(demande.id).split("-")[0].upper(),
        date_depot=depot.strftime("%d/%m/%Y") if depot else "date inconnue",
        bloc_commentaire=bloc_commentaire,
        manager_nom=manager_nom,
        date_approbation=date_approbation_str,
        date_generation=datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC"),
    )
    return weasyprint.HTML(string=html).write_pdf()


_GABARIT_BON_DE_COMMANDE = """
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Helvetica, Arial, sans-serif; color: #201F1D; margin: 48px; }}
  h1 {{ font-size: 20px; border-bottom: 2px solid #3E7C74; padding-bottom: 8px; }}
  h2 {{ font-size: 15px; margin-top: 32px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  td {{ padding: 8px 4px; border-bottom: 1px solid #D3D1CB; font-size: 13px; }}
  td.label {{ color: #46453F; width: 40%; }}
  td.valeur {{ font-weight: bold; }}
  table.montants td {{ text-align: right; }}
  table.montants td.libelle {{ text-align: left; color: #46453F; }}
  table.montants tr.total td {{ font-weight: bold; border-top: 2px solid #201F1D; font-size: 14px; }}
  table.lignes td {{ text-align: right; }}
  table.lignes td.description {{ text-align: left; color: #201F1D; }}
  table.lignes thead td {{ font-weight: bold; color: #46453F; border-bottom: 2px solid #201F1D; }}
  .signatures {{ display: flex; justify-content: space-between; margin-top: 48px; }}
  .signature {{ width: 45%; }}
  .signature .ligne {{ border-top: 1px solid #201F1D; margin-bottom: 6px; }}
  .signature img.trace {{ max-width: 220px; max-height: 70px; display: block; margin-bottom: 4px; }}
  .signature .nom {{ font-style: italic; font-size: 13px; font-weight: bold; margin: 0; }}
  .signature .role {{ font-size: 11px; color: #46453F; margin: 2px 0 0 0; }}
  .certificat {{ margin-top: 32px; padding: 12px; background: #F4F3F0; font-size: 11px; color: #46453F; }}
  .page2 {{ page-break-before: always; font-size: 11px; color: #46453F; }}
  .pied {{ margin-top: 32px; font-size: 11px; color: #46453F; }}
</style>
</head>
<body>
  <h1>Bon de commande {numero_bc}</h1>
  <table>
    <tr><td class="label">Fournisseur / Tiers</td><td class="valeur">{tiers}</td></tr>
    <tr><td class="label">Objet</td><td class="valeur">{objet}</td></tr>
    <tr><td class="label">Référence de la demande</td><td class="valeur">{demande_id}</td></tr>
  </table>

  <h2>{titre_montants}</h2>
  {tableau_lignes}
  <table class="montants">
    <tr class="total"><td class="libelle">Total HT</td><td>{total_ht} {devise}</td></tr>
    {lignes_tva_par_taux}
    <tr class="total"><td class="libelle">Total TTC</td><td>{total_ttc} {devise}</td></tr>
  </table>
  {ligne_conversion}

  {bloc_signatures}

  <div class="certificat">
    {texte_certificat}
  </div>

  <div class="page2">
    <h2>Conditions générales d'achat</h2>
    <p>Le présent bon de commande engage l'organisation dans les conditions générales
    d'achat en vigueur à la date de signature. Toute modification (quantité, délai,
    montant) fait l'objet d'un avenant signé selon le même circuit d'approbation.</p>
  </div>

  <p class="pied">Document généré automatiquement le {date_generation} - Plateforme d'approbation de workflows.</p>
</body>
</html>
"""


def generer_bon_de_commande(
    demande: Demande,
    juriste: Utilisateur | None,
    signataire: Utilisateur | None,
    date_signature: datetime | None,
    signature_image: bytes | None = None,
    arbitre: Utilisateur | None = None,
    date_arbitrage: datetime | None = None,
) -> bytes:
    """
    Génère le bon de commande final (PDF) d'une demande d'achat terminée -
    livrable attendu par le CDC fonctionnel (section 3 : "Document
    contractuel revêtu des signatures électroniques avec son certificat de
    validation") et écart n°1 du CDC technique (section 4.1 : numéro
    chronologique, calculs de TVA, pavé de signatures, conditions
    contractuelles en page 2).

    Hypothèse assumée (non précisée par le CDC) : le montant saisi
    (`budget_engage`) est un montant TTC ; le taux de TVA appliqué pour la
    ventilation HT/TVA est `Settings.taux_tva_bon_de_commande` (20% par
    défaut, taux normal français le plus courant).

    Écart identifié et corrigé (revue du 27/09) : la signature de la
    Direction générale était jusqu'ici une simple mention imprimée, sans
    aucun tracé réellement capturé (voir app/routers/decisions.py :
    l'action "signer" capture désormais une image PNG dessinée à l'écran,
    section 8 du CDC technique). `signature_image` (octets PNG) l'intègre
    réellement dans le document ; le paramètre reste optionnel pour ne pas
    faire échouer la génération d'un ancien bon de commande signé avant ce
    changement (aucune image alors disponible).

    Le certificat de validation reste une mention imprimée (identités des
    deux décideurs, horodatage, référence au mécanisme de jetons à usage
    unique) plutôt qu'un certificat cryptographique distinct - seule la
    signature elle-même est désormais réellement capturée, pas encore le
    certificat qui l'accompagne.

    Achat en DEROGATION (07/10) : le circuit standard (avis juridique puis signature de la Direction
    generale) a ete contourne au profit d'un arbitre unique. Le bon ne doit donc surtout pas pretendre
    le contraire : `arbitre` (non None) remplace le pave « juriste + DG » par la mention de l'arbitrage
    exceptionnel et le motif de la derogation.
    """
    donnees = demande.donnees
    # Les montants du bon sont dans la devise du CONTRAT ; si elle differe de la devise de reference,
    # l'equivalent budgetaire et le taux figes a la soumission sont rappeles (decision du 28/09).
    code_devise = devises.devise_de(donnees)
    devise = devises.SYMBOLES.get(code_devise, code_devise)
    ligne_conversion = ""
    if code_devise != devises.devise_reference():
        ref = devises.devise_reference()
        ligne_conversion = (
            '<p class="pied">Équivalent budgétaire : '
            f'{devises.montant_reference(donnees, "budget_engage"):.2f} {devises.SYMBOLES.get(ref, ref)} '
            f'(taux appliqué : 1 {escape(code_devise)} = {donnees.get("taux_applique")} {devises.SYMBOLES.get(ref, ref)}, '
            "fixé à la soumission).</p>"
        )

    # CDC technique 4.1 : "calculs de taxes differencies par ligne", "TVA par taux". Une demande
    # detaillee en lignes (decision du 28/09) donne le detail complet ; une demande anterieure a
    # cette extension (aucune ligne enregistree) retombe sur l'ancien calcul a taux global unique.
    if donnees.get("lignes"):
        totaux = facturation.totaux_depuis_lignes(donnees["lignes"])
    else:
        totaux = facturation.totaux_depuis_montant_global(
            float(donnees["budget_engage"]), settings.taux_tva_bon_de_commande * 100
        )

    if totaux.detail_par_ligne:
        titre_montants = "Détail des lignes et montants"
        lignes_html = "".join(
            f'<tr><td class="description">{escape(l.description)}</td>'
            f'<td>{l.montant_ht:.2f} {escape(devise)}</td>'
            f'<td>{l.taux_tva:g} %</td>'
            f'<td>{l.montant_ttc:.2f} {escape(devise)}</td></tr>'
            for l in totaux.lignes
        )
        tableau_lignes = (
            '<table class="lignes"><thead><tr>'
            '<td class="description">Description</td><td>Montant HT</td><td>Taux TVA</td><td>Montant TTC</td>'
            f"</tr></thead><tbody>{lignes_html}</tbody></table>"
        )
    else:
        titre_montants = "Montants"
        tableau_lignes = ""

    lignes_tva_par_taux = "".join(
        f'<tr><td class="libelle">TVA ({sous_total.taux_tva:g} %)</td><td>{sous_total.montant_tva:.2f} {escape(devise)}</td></tr>'
        for sous_total in totaux.par_taux
    )

    if signature_image:
        image_b64 = base64.b64encode(signature_image).decode("ascii")
        trace_signature_html = f'<img class="trace" src="data:image/png;base64,{image_b64}" alt="Signature">'
    else:
        trace_signature_html = '<div class="ligne"></div>'

    if arbitre is not None:
        date_arbitrage_txt = date_arbitrage.strftime("%d/%m/%Y à %H:%M UTC") if date_arbitrage else "date inconnue"
        motif = donnees.get("motif_derogation") or ""
        bloc_motif = f'<p class="role">Motif de la dérogation : {escape(motif)}</p>' if motif else ""
        bloc_signatures = (
            '<div class="signatures"><div class="signature">'
            '<div class="ligne"></div>'
            f'<p class="nom">{escape(arbitre.nom_complet)}</p>'
            f'<p class="role">Arbitrage exceptionnel (dérogation) — Accepté électroniquement le {date_arbitrage_txt}</p>'
            f"{bloc_motif}</div></div>"
        )
        texte_certificat = (
            "Certificat de validation : cette demande a été traitée en <strong>arbitrage exceptionnel "
            "(dérogation)</strong> ; le circuit standard (avis juridique, signature de la Direction générale) "
            "n'a pas été suivi. Elle a été acceptée électroniquement par l'arbitre ci-dessus via la plateforme "
            "d'approbation de workflows, jeton de décision à usage unique. "
            f"Généré le {datetime.now(UTC).strftime('%d/%m/%Y %H:%M UTC')}."
        )
    else:
        bloc_signatures = (
            '<div class="signatures"><div class="signature">'
            '<div class="ligne"></div>'
            f'<p class="nom">{escape(juriste.nom_complet) if juriste else "Juriste introuvable"}</p>'
            '<p class="role">Service juridique — Avis favorable</p></div>'
            f'<div class="signature">{trace_signature_html}'
            f'<p class="nom">{escape(signataire.nom_complet) if signataire else "Signataire introuvable"}</p>'
            '<p class="role">Direction générale — Signé électroniquement le '
            f'{date_signature.strftime("%d/%m/%Y à %H:%M UTC") if date_signature else "date inconnue"}</p></div></div>'
        )
        texte_certificat = (
            "Certificat de validation : ce document a été approuvé électroniquement par les deux "
            "signataires ci-dessus via la plateforme d'approbation de workflows, jetons de décision "
            "à usage unique. "
            f"Généré le {datetime.now(UTC).strftime('%d/%m/%Y %H:%M UTC')}."
        )

    html = _GABARIT_BON_DE_COMMANDE.format(
        numero_bc=donnees["numero_bc"],
        tiers=escape(donnees.get("tiers", "")),
        objet=escape(donnees.get("objet", "")),
        demande_id=str(demande.id),
        titre_montants=titre_montants,
        tableau_lignes=tableau_lignes,
        lignes_tva_par_taux=lignes_tva_par_taux,
        total_ht=f"{totaux.total_ht:.2f}",
        total_ttc=f"{totaux.total_ttc:.2f}",
        devise=escape(devise),
        ligne_conversion=ligne_conversion,
        bloc_signatures=bloc_signatures,
        texte_certificat=texte_certificat,
        date_generation=datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC"),
    )
    return weasyprint.HTML(string=html).write_pdf()
