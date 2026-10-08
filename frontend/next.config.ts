import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Sortie "standalone" : Next.js copie uniquement les fichiers et
  // dependances reellement necessaires a l'execution dans
  // .next/standalone - permet une image Docker finale bien plus legere
  // qu'avec node_modules complet, sans rien perdre du serveur Node requis
  // par le proxy /api/backend (route dynamique, pas un site statique).
  output: "standalone",

  // Ecart trouve en testant le proxy de bout en bout (27/09) : par defaut,
  // Next.js repond 308 a toute URL terminee par "/" pour la rediriger vers
  // la meme sans slash. Or les routes FastAPI sont declarees AVEC slash
  // final (@router.post("/") sous un prefixe : /api/v1/conges/,
  // /api/v1/notes-frais/, /api/v1/achats/...) - chaque appel de liste ou de
  // creation passait donc par une redirection supplementaire, et un client
  // qui ne suit pas les redirections (curl, un outil tiers) echouait. Le
  // proxy relaie desormais le chemin exactement tel que recu (voir
  // src/app/api/backend/[...path]/route.ts).
  skipTrailingSlashRedirect: true,
};

export default nextConfig;
