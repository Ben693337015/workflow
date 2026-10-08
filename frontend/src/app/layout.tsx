import type { Metadata } from "next";
import "@fontsource-variable/manrope";
import "./globals.css";
import { AuthProvider } from "@/hooks/useAuth";
import { SCRIPT_THEME } from "@/components/bouton-theme";

// Police Manrope auto-hébergée (paquet @fontsource-variable/manrope) : aucun appel à Google Fonts au build
// ni à l'exécution, donc pas de fuite d'adresse IP des utilisateurs vers un tiers et un build sans accès réseau externe.

export const metadata: Metadata = {
  title: "Plateforme Workflows",
  description: "Plateforme d'approbation de workflows - conges, notes de frais, achats",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: SCRIPT_THEME }} />
      </head>
      <body className="min-h-full font-sans">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
