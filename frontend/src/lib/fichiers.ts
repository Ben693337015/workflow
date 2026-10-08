/**
 * Taille maximale d'un fichier depose (contrat des achats, recus, justificatifs, pieces de la discussion).
 * Passee de 10 a 30 Mo (05/10/2026), puis a 40 Mo (07/10/2026). DOIT rester identique a `TAILLE_MAX_MO` cote serveur
 * (app/services/stockage_fichiers.py) - le serveur reste l'autorite, ce controle ne fait qu'eviter d'envoyer
 * en vain un fichier de plusieurs centaines de Mo.
 */
export const TAILLE_MAX_FICHIER_MO = 40;
export const TAILLE_MAX_FICHIER_OCTETS = TAILLE_MAX_FICHIER_MO * 1024 * 1024;

/** Message d'erreur identique a celui du serveur, ou null si le fichier (ou l'absence de fichier) convient. */
export function messageTailleFichier(fichier: File | null | undefined): string | null {
  if (fichier && fichier.size > TAILLE_MAX_FICHIER_OCTETS) {
    return `Le fichier dépasse la taille maximale autorisée (${TAILLE_MAX_FICHIER_MO} Mo).`;
  }
  return null;
}
