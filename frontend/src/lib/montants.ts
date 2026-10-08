/**
 * Formatage des montants (plusieurs devises, decision du 28/09). `Intl` connait les symboles et les
 * decimales de chaque devise (0 pour XAF, 2 pour EUR...). Un code inconnu ou mal forme ne doit jamais
 * faire planter un ecran : on retombe sur "montant CODE".
 */
export function formaterMontant(valeur: number, devise: string): string {
  try {
    return new Intl.NumberFormat("fr-FR", { style: "currency", currency: devise }).format(valeur);
  } catch {
    return `${valeur} ${devise}`;
  }
}

/** "800,00 $US (≈ 736,00 €)" si la devise differe de la reference, "736,00 €" sinon. */
export function formaterAvecEquivalent(
  valeur: number,
  devise: string,
  valeurReference: number | undefined,
  reference: string
): string {
  if (devise === reference || valeurReference === undefined) return formaterMontant(valeur, devise);
  return `${formaterMontant(valeur, devise)} (≈ ${formaterMontant(valeurReference, reference)})`;
}
