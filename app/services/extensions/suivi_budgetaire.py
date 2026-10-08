"""
Extension native ecart n3 : suivi budgetaire (section 4 / 11 du CDC
technique).

Meme principe que verrou_rh.py pour les conges (section 13.2, etape 4) :
verification synchrone avant toute creation d'enregistrement, aucune
exception personnalisee - la fonction retourne un booleen et les
montants, a charge de l'appelant (le routeur) de decider la reponse HTTP
(422) en cas de solde insuffisant.
"""
from html import escape

from app.services.devises import SYMBOLES, devise_reference
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enveloppe_budgetaire import EnveloppeBudgetaire


async def obtenir_enveloppe(
    db: AsyncSession, service: str, exercice: int
) -> EnveloppeBudgetaire | None:
    """Recupere l'enveloppe budgetaire du service pour cet exercice, si elle existe."""
    resultat = await db.execute(
        select(EnveloppeBudgetaire).where(
            EnveloppeBudgetaire.service == service,
            EnveloppeBudgetaire.exercice == exercice,
        )
    )
    return resultat.scalar_one_or_none()


async def calculer_solde_disponible(db: AsyncSession, service: str, exercice: int) -> float:
    """
    Solde disponible = budget_alloue - budget_consomme pour ce service et
    cet exercice. Aucune enveloppe definie est traite comme 0 EUR
    disponible (defaut securise : une depense ne peut jamais s'imputer sur
    un budget qui n'a pas ete explicitement alloue par la DRH/le
    controleur de gestion).
    """
    enveloppe = await obtenir_enveloppe(db, service, exercice)
    if enveloppe is None:
        return 0.0
    return float(enveloppe.budget_alloue) - float(enveloppe.budget_consomme)


async def budget_suffisant(
    db: AsyncSession, service: str, exercice: int, montant: float
) -> tuple[bool, float]:
    """
    Verifie si le solde disponible du service couvre le montant de la
    depense. Retourne (budget_ok, solde_disponible).
    """
    solde_disponible = await calculer_solde_disponible(db, service, exercice)
    return solde_disponible >= montant, solde_disponible


async def consommer_budget(db: AsyncSession, service: str, exercice: int, montant: float) -> None:
    """
    Incremente budget_consomme a l'approbation finale de la depense
    (section 13.3, etape 16 - meme moment que consommer_solde pour les
    conges). Ne commit pas : a la charge de l'appelant, meme transaction
    que la mise a jour de l'etape de workflow.

    Ne devrait etre appele qu'apres un budget_suffisant() positif ; si
    l'enveloppe a disparu entre-temps (cas limite), la depense est quand
    meme finalisee plutot que de faire echouer une decision deja actee -
    coherent avec le choix retenu pour consommer_solde (verrou_rh.py).
    """
    enveloppe = await obtenir_enveloppe(db, service, exercice)
    if enveloppe is None:
        return
    # Incrementation ATOMIQUE cote base (`budget_consomme = budget_consomme + :montant`) : lire puis
    # reecrire la valeur en Python pouvait perdre une ecriture quand deux decisions concernant la
    # meme enveloppe se terminaient en meme temps.
    await db.execute(
        update(EnveloppeBudgetaire)
        .where(EnveloppeBudgetaire.id == enveloppe.id)
        .values(budget_consomme=EnveloppeBudgetaire.budget_consomme + montant)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(enveloppe)


async def resume_budgetaire_demande(db: AsyncSession, demande, demandeur) -> dict | None:
    """
    Resume budgetaire d'une demande, avec le meme exercice et le meme montant
    que ceux utilises a la finalisation du circuit (consommation du budget) :
    ce que le decideur voit est exactement ce qui sera debite. None pour les
    conges (pas d'enveloppe budgetaire).
    """
    from datetime import UTC, date, datetime

    from app.models.enums import TypeProcessus

    if demandeur is None:
        return None
    from app.services import devises

    # Montant CONVERTI (devise de reference) : c'est lui que l'enveloppe verra debiter.
    if demande.processus == TypeProcessus.NOTES_FRAIS:
        exercice = date.fromisoformat(demande.donnees["date_depense"]).year
        montant = devises.montant_reference(demande.donnees, "montant")
    elif demande.processus == TypeProcessus.ACHATS:
        exercice = demande.creee_le.year if demande.creee_le else datetime.now(UTC).year
        montant = devises.montant_reference(demande.donnees, "budget_engage")
    else:
        return None
    return await resume_budgetaire(db, demandeur.service, exercice, montant)


async def resume_budgetaire(db: AsyncSession, service: str, exercice: int, montant: float) -> dict:
    """
    Situation budgetaire a presenter au decideur (CDC section 4.3 : le "solde
    budgetaire disponible" doit etre "obligatoirement affiche de maniere
    visuelle au decideur dans sa notification de vote"). Le budget n'est
    consomme qu'a la finalisation du circuit : `solde_disponible` est donc le
    solde AVANT cette demande, `solde_apres_validation` celui qui en resulterait.
    """
    solde = await calculer_solde_disponible(db, service, exercice)
    return {
        "service": service,
        "exercice": exercice,
        "solde_disponible": round(solde, 2),
        "montant_demande": round(montant, 2),
        "solde_apres_validation": round(solde - montant, 2),
        "devise": devise_reference(),
    }


def bloc_html_budget(resume: dict) -> str:
    """Bloc visuel (vert si l'enveloppe suffit, rouge en cas de depassement) pour les e-mails aux decideurs."""
    devise = SYMBOLES.get(resume.get("devise", devise_reference()), resume.get("devise", devise_reference()))
    depassement = resume["solde_apres_validation"] < 0
    couleur, fond = ("#B42318", "#FEF3F2") if depassement else ("#067647", "#ECFDF3")
    verdict = "Dépassement de l'enveloppe ⚠️" if depassement else "Enveloppe suffisante ✅"
    return (
        f'<div style="border-left:4px solid {couleur};background:{fond};border-radius:6px;padding:12px 14px;margin:4px 0 16px 0;'
        f'font-size:14px;line-height:1.6;color:#1f2430;">'
        f'<strong style="color:{couleur};">💰 Budget du service « {escape(resume["service"])} » '
        f'({resume["exercice"]}) — {verdict}</strong><br>'
        f'Solde disponible : {resume["solde_disponible"]} {devise} · Montant demandé : {resume["montant_demande"]} {devise} · '
        f'Solde après validation : {resume["solde_apres_validation"]} {devise}</div>'
    )
