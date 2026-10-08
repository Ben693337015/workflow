"""
Copie les pieces jointes DEJA presentes dans le dossier local (STOCKAGE_FICHIERS_DOSSIER) vers le bucket S3, avec les
MEMES cles : la base de donnees ne change pas. Les fichiers locaux ne sont JAMAIS supprimes (faites-le a la main apres
verification). Relancable sans risque : un fichier deja present avec la meme taille est ignore.

    PYTHONPATH=. python -m scripts.migrer_fichiers_vers_s3 --dry-run     # montre ce qui serait copie
    PYTHONPATH=. python -m scripts.migrer_fichiers_vers_s3               # copie
    PYTHONPATH=. python -m scripts.migrer_fichiers_vers_s3 --verifier-base   # + controle que chaque piece/signature
                                                                              # referencee en base existe dans le bucket
Les variables S3_* doivent etre renseignees (sinon : erreur). Code de sortie non nul en cas d'echec ou de reference manquante.
"""
import argparse
import asyncio
import sys
from pathlib import Path

from botocore.exceptions import ClientError

from app.services import stockage_fichiers as st


def _taille_distante(cle: str) -> int | None:
    try:
        return st._s3().head_object(Bucket=st.settings.s3_bucket, Key=st._cle_objet(cle))["ContentLength"]
    except ClientError as erreur:
        if erreur.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def migrer(dry_run: bool) -> tuple[int, int, int]:
    if not st.utilise_s3():
        raise st.StockageMalConfigure("S3 non configure : renseignez les 4 variables S3_* avant de migrer.")
    dossier = Path(st.settings.stockage_fichiers_dossier)
    copies = ignores = echecs = 0
    for chemin in sorted(p for p in dossier.glob("*") if p.is_file()) if dossier.exists() else []:
        cle, taille = chemin.name, chemin.stat().st_size
        try:
            if _taille_distante(cle) == taille:
                ignores += 1
                continue
            print(f"{'[dry-run] ' if dry_run else ''}copie {cle} ({taille} octets)")
            if not dry_run:
                st._s3().put_object(Bucket=st.settings.s3_bucket, Key=st._cle_objet(cle), Body=chemin.read_bytes())
                if _taille_distante(cle) != taille:
                    raise RuntimeError("taille distante differente apres envoi")
            copies += 1
        except Exception as erreur:  # noqa: BLE001
            echecs += 1
            print(f"ECHEC {cle} : {erreur}")
    return copies, ignores, echecs


async def _cles_referencees() -> set[str]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, engine
    from app.models.etape_workflow import EtapeWorkflow
    from app.models.piece_jointe import PieceJointe

    async with AsyncSessionLocal() as db:
        pieces = (await db.execute(select(PieceJointe.cle_stockage))).scalars().all()
        signatures = (await db.execute(
            select(EtapeWorkflow.signature_cle_stockage).where(EtapeWorkflow.signature_cle_stockage.is_not(None))
        )).scalars().all()
    await engine.dispose()  # la boucle asyncio se ferme avec asyncio.run : ne pas laisser de connexions liees a elle
    return {c for c in [*pieces, *signatures] if c}


def verifier_base() -> int:
    manquantes = [c for c in sorted(asyncio.run(_cles_referencees())) if _taille_distante(c) is None]
    for cle in manquantes:
        print(f"MANQUANT dans le bucket : {cle}")
    print(f"Controle base -> bucket : {len(manquantes)} reference(s) manquante(s).")
    return len(manquantes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="ne copie rien, affiche ce qui serait copie")
    parser.add_argument("--verifier-base", action="store_true", help="controle que les cles de la base existent dans le bucket")
    args = parser.parse_args()
    try:
        print(f"Destination : {st.description_stockage()}")
        copies, ignores, echecs = migrer(args.dry_run)
        print(f"Termine : {copies} copie(s), {ignores} deja present(s), {echecs} echec(s).")
        manquantes = verifier_base() if args.verifier_base else 0
        return 1 if echecs or manquantes else 0
    except Exception as erreur:  # noqa: BLE001
        print(f"ECHEC : {type(erreur).__name__} : {erreur}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
