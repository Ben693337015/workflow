import type { RoleUtilisateur } from "@/types";

/**
 * Ecart trouve via une vraie capture d'ecran (26/09) : la classe CSS
 * Tailwind `capitalize` (majuscule sur la premiere lettre seulement)
 * donnait "Drh" au lieu de "DRH" - un acronyme, pas un mot ordinaire - et
 * aurait affiche les roles a underscore tels quels ("Direction_financiere"
 * au lieu de "Direction financière"). Mapping explicite a la place.
 */
const libellesRoles: Record<RoleUtilisateur, string> = {
  employe: "Employé",
  manager: "Manager",
  drh: "DRH",
  direction_financiere: "Direction financière",
  service_juridique: "Service juridique",
  direction_generale: "Direction générale",
  controleur_de_gestion: "Contrôleur de gestion",
};

export function libelleRole(role: RoleUtilisateur): string {
  return libellesRoles[role] ?? role;
}
