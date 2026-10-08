"""
Synthese des notes de frais validees, transmise a la comptabilite (CDC fonctionnel section 3 :
"Tableau de synthese des frais valides transmis a la comptabilite pour remboursement").

Une seule construction de ligne sert l'e-mail envoye a la validation, l'ecran et l'export CSV : les trois
ne peuvent pas diverger. Les montants sont ceux FIGES a la soumission (devise d'origine, taux applique,
montant converti - decision du 28/09).
"""
from datetime import UTC, date, datetime, time
from html import escape

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demande import Demande
from app.models.enums import StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.schemas.synthese_frais import LigneSynthese, SyntheseFrais, TotalDevise
from app.services import devises, pieces

MAX_LIGNES = 5000
SEPARATEUR_CSV = ";"


def _debut(jour: date) -> datetime:
    return datetime.combine(jour, time.min, tzinfo=UTC)


def _fin(jour: date) -> datetime:
    return datetime.combine(jour, time.max, tzinfo=UTC)


def _sous_requete_validation():
    """Par demande : date de la derniere approbation, et presence d'une etape d'arbitrage (derogation)."""
    return (
        select(
            EtapeWorkflow.demande_id.label("demande_id"),
            func.max(EtapeWorkflow.date_reponse).label("valide_le"),
            func.max(case((EtapeWorkflow.est_derogation.is_(True), 1), else_=0)).label("derogation"),
        )
        .where(EtapeWorkflow.statut == StatutEtape.APPROUVE)
        .group_by(EtapeWorkflow.demande_id)
        .subquery()
    )


async def _validateurs(db: AsyncSession, demande_ids: list) -> dict:
    """Noms des approbateurs ayant valide, dans l'ordre des niveaux (une requete pour tout le lot)."""
    if not demande_ids:
        return {}
    lignes = await db.execute(
        select(EtapeWorkflow.demande_id, Utilisateur.nom_complet)
        .join(Utilisateur, Utilisateur.id == EtapeWorkflow.approbateur_attendu_id)
        .where(EtapeWorkflow.demande_id.in_(demande_ids), EtapeWorkflow.statut == StatutEtape.APPROUVE)
        .order_by(EtapeWorkflow.niveau)
    )
    regroupes: dict = {}
    for demande_id, nom in lignes.all():
        regroupes.setdefault(demande_id, []).append(nom)
    return regroupes


def _iso(valeur: datetime | None) -> str:
    if valeur is None:
        return ""
    return (valeur if valeur.tzinfo else valeur.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


async def _construire(db: AsyncSession, rangees: list) -> list[LigneSynthese]:
    ids = [d.id for d, _u, _v, _g in rangees]
    validateurs = await _validateurs(db, ids)
    nb_pieces = {i: len(p) for i, p in (await pieces.pieces_par_demande(db, ids)).items()}
    lignes = []
    for demande, demandeur, valide_le, derogation in rangees:
        d = demande.donnees
        lignes.append(
            LigneSynthese(
                id=str(demande.id),
                valide_le=_iso(valide_le),
                demandeur_nom=demandeur.nom_complet,
                service=demandeur.service,
                categorie=d.get("categorie", ""),
                date_depense=date.fromisoformat(d["date_depense"]),
                description=d.get("description", ""),
                montant=float(d["montant"]),
                devise=devises.devise_de(d),
                taux_applique=float(d.get("taux_applique") or 1.0),
                montant_reference=devises.montant_reference(d, "montant"),
                valide_par=validateurs.get(demande.id, []),
                derogation=bool(derogation),
                nb_pieces=nb_pieces.get(demande.id, 0),
            )
        )
    return lignes


async def _rangees(db, *, depuis, jusqu_a, service, demande_id=None) -> list:
    valide = _sous_requete_validation()
    requete = (
        select(Demande, Utilisateur, valide.c.valide_le, valide.c.derogation)
        .join(Utilisateur, Utilisateur.id == Demande.demandeur_id)
        .join(valide, valide.c.demande_id == Demande.id)
        .where(Demande.processus == TypeProcessus.NOTES_FRAIS, Demande.statut_global == StatutDemande.TERMINEE)
        .order_by(valide.c.valide_le.desc(), Demande.id)
        .limit(MAX_LIGNES + 1)
    )
    if depuis:
        requete = requete.where(valide.c.valide_le >= _debut(depuis))
    if jusqu_a:
        requete = requete.where(valide.c.valide_le <= _fin(jusqu_a))
    if service:
        requete = requete.where(Utilisateur.service == service)
    if demande_id:
        requete = requete.where(Demande.id == demande_id)
    return (await db.execute(requete)).all()


async def ligne_de(db: AsyncSession, demande: Demande) -> LigneSynthese | None:
    """Ligne de synthese d'UNE note validee (e-mail envoye a la validation) ; None si elle n'est pas validee."""
    rangees = await _rangees(db, depuis=None, jusqu_a=None, service=None, demande_id=demande.id)
    return (await _construire(db, rangees))[0] if rangees else None


async def toutes_les_lignes(db, *, depuis=None, jusqu_a=None, service=None) -> tuple[list[LigneSynthese], bool]:
    """Toutes les lignes correspondant aux criteres (plafonnees a MAX_LIGNES) et l'indicateur de troncature."""
    rangees = await _rangees(db, depuis=depuis, jusqu_a=jusqu_a, service=service)
    return await _construire(db, rangees[:MAX_LIGNES]), len(rangees) > MAX_LIGNES


async def rechercher(db, *, depuis=None, jusqu_a=None, service=None, limit=50, offset=0) -> SyntheseFrais:
    lignes, tronque = await toutes_les_lignes(db, depuis=depuis, jusqu_a=jusqu_a, service=service)

    par_devise: dict[str, list[LigneSynthese]] = {}
    for l in lignes:
        par_devise.setdefault(l.devise, []).append(l)
    totaux = [
        TotalDevise(devise=code, nombre=len(ls), total=round(sum(l.montant for l in ls), 2),
                    total_reference=round(sum(l.montant_reference for l in ls), 2))
        for code, ls in sorted(par_devise.items())
    ]
    return SyntheseFrais(
        devise_reference=devises.devise_reference(),
        nombre=len(lignes),
        total_reference=round(sum(l.montant_reference for l in lignes), 2),
        par_devise=totaux,
        total_lignes=len(lignes),
        limit=limit,
        offset=offset,
        tronque=tronque,
        elements=lignes[offset : offset + limit],
    )


# --- e-mail a la comptabilite -----------------------------------------------------------------

def corps_email_html(l: LigneSynthese) -> str:
    ref = devises.devise_reference()
    montant = devises.formater(l.montant, l.devise)
    conversion = ""
    if l.devise != ref:
        conversion = (f" (≈ {devises.formater(l.montant_reference, ref)}, taux appliqué : "
                      f"1 {escape(l.devise)} = {l.taux_applique} {devises.SYMBOLES.get(ref, ref)}, figé à la soumission)")
    lignes = [
        ("Demandeur", f"{escape(l.demandeur_nom)} ({escape(l.service)})"),
        ("Catégorie", escape(l.categorie)),
        ("Date de la dépense", l.date_depense.strftime("%d/%m/%Y")),
        ("Description", escape(l.description)),
        ("Montant à rembourser", f"<strong>{escape(montant)}</strong>{conversion}"),
        ("Validé par", escape(", ".join(l.valide_par)) or "—"),
        ("Arbitrage exceptionnel", "Oui (dérogation)" if l.derogation else "Non"),
        ("Pièces jointes", f"{l.nb_pieces} — consultables dans l'écran « Synthèse des frais »" if l.nb_pieces else "Aucune"),
        ("Référence du dossier", l.id),
    ]
    from app.services import email_gabarit as g

    cellules = "".join(
        f"<tr><td style=\"padding:9px 14px;font-size:13px;color:#5b6270;width:38%;border-bottom:1px solid #eceef3;\">{k}</td>"
        f"<td style=\"padding:9px 14px;font-size:14px;color:#1f2430;border-bottom:1px solid #eceef3;\">{v}</td></tr>"
        for k, v in lignes
    )
    tableau = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e1e4ea;'
        f'border-radius:10px;border-collapse:separate;margin:4px 0 18px 0;background:#fafbfc;">{cellules}</table>'
    )
    return (
        g.paragraphe("Bonjour,")
        + g.paragraphe("Une note de frais vient d'être validée par toute la chaîne d'approbation 🎯 Elle est prête à être remboursée.")
        + tableau
    )


# --- export CSV ----------------------------------------------------------------------------------

def neutraliser(valeur: str) -> str:
    """
    Neutralise l'injection de formule (CSV injection) : un tableur interprete comme une FORMULE toute
    cellule commencant par = + - @ (ou tabulation / retour chariot). Or description, categorie et noms
    sont saisis par des utilisateurs et ouverts par la comptabilite : on prefixe d'une apostrophe.
    """
    return "'" + valeur if valeur and valeur[0] in ("=", "+", "-", "@", "\t", "\r") else valeur


def _cellule(valeur) -> str:
    texte = neutraliser(str(valeur))
    if SEPARATEUR_CSV in texte or '"' in texte or "\n" in texte or "\r" in texte:
        texte = '"' + texte.replace('"', '""') + '"'
    return texte


def _decimal(valeur: float) -> str:
    return f"{valeur:.2f}".replace(".", ",")  # tableur francophone


def contenu_csv(lignes: list[LigneSynthese]) -> bytes:
    """CSV UTF-8 avec BOM (accents corrects sous Excel), separateur ';', decimales a virgule."""
    ref = devises.devise_reference()
    entetes = ["Date de validation", "Demandeur", "Service", "Categorie", "Date de la depense", "Description", "Montant",
               "Devise", "Taux applique", f"Montant en {ref}", "Valide par", "Derogation", "Pieces jointes", "Reference du dossier"]
    rangees = [SEPARATEUR_CSV.join(_cellule(e) for e in entetes)]
    for l in lignes:
        rangees.append(SEPARATEUR_CSV.join(_cellule(v) for v in (
            l.valide_le[:10], l.demandeur_nom, l.service, l.categorie, l.date_depense.strftime("%d/%m/%Y"), l.description,
            _decimal(l.montant), l.devise, str(l.taux_applique).replace(".", ","), _decimal(l.montant_reference),
            ", ".join(l.valide_par), "Oui" if l.derogation else "Non", l.nb_pieces, l.id,
        )))
    return ("\ufeff" + "\r\n".join(rangees) + "\r\n").encode("utf-8")
