"""
Verifie le stockage des pieces jointes configure dans l'environnement (.env) : ecrit, relit puis supprime un objet de
test. A lancer apres avoir renseigne les variables S3_* (jamais de secret affiche).

    docker compose exec api python -m scripts.verifier_stockage
    # ou, hors Docker :  PYTHONPATH=. python -m scripts.verifier_stockage
Code de sortie 0 si tout fonctionne, 1 sinon.
"""
import sys

from app.services import stockage_fichiers


def main() -> int:
    try:
        print(f"Stockage configure : {stockage_fichiers.description_stockage()}")
        print(stockage_fichiers.verifier_acces_s3())
        return 0
    except Exception as erreur:  # noqa: BLE001 - on veut afficher la cause quelle qu'elle soit
        print(f"ECHEC : {type(erreur).__name__} : {erreur}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
