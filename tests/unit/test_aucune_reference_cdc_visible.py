"""
Garde-fou : aucun texte AFFICHE a l'utilisateur (PDF du bon de commande, e-mails, messages d'erreur, descriptions
de l'API, interface) ne doit citer le cahier des charges ou un numero de section interne (« section 9 du CDC
technique », « R22 »...). Les commentaires et docstrings, destines aux developpeurs, ne sont pas concernes.
"""
import ast
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
MOTIF = re.compile(r"(\bCDC\b|cahier des charges|\bsection\s*\d|§\s*\d|\bR\d{1,2}\b|Option [AB]\b)", re.I)


def _chaines_visibles_python():
    for chemin in (RACINE / "app").rglob("*.py"):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        docstrings = set()
        for n in ast.walk(arbre):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
                premier = n.body[0]
                if isinstance(premier, ast.Expr) and isinstance(getattr(premier, "value", None), ast.Constant):
                    docstrings.add(id(premier.value))
        for n in ast.walk(arbre):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                yield chemin, n.lineno, n.value


def test_aucune_reference_au_cdc_dans_les_textes_python_visibles():
    trouves = [f"{c.relative_to(RACINE)}:{l}: {t[:80]!r}" for c, l, t in _chaines_visibles_python() if MOTIF.search(t)]
    assert not trouves, "Reference interne visible par l'utilisateur :\n" + "\n".join(trouves)


def test_aucune_reference_au_cdc_dans_l_interface():
    trouves = []
    for chemin in (RACINE / "frontend" / "src").rglob("*.tsx"):
        if chemin.name.endswith(".test.tsx"):
            continue
        for i, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
            nue = ligne.strip()
            if nue.startswith(("//", "*", "/*", "{/*")):
                continue
            if MOTIF.search(nue) and re.search(r"[A-Za-zÀ-ÿ]{3,} [A-Za-zÀ-ÿ&;']{2,}", nue):
                trouves.append(f"{chemin.relative_to(RACINE)}:{i}: {nue[:80]}")
    assert not trouves, "Reference interne visible dans l'interface :\n" + "\n".join(trouves)
