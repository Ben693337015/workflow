/** Declenche l'enregistrement d'un fichier recu (Blob) sous le nom donne. */
export function enregistrerFichier(blob: Blob, nom: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nom;
  a.click();
  URL.revokeObjectURL(url);
}
