/** Date et heure lisibles (fuseau du navigateur) pour un horodatage ISO du backend. */
export function formaterHorodatage(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });
}
