"use client";

import * as React from "react";
import {
  EVENEMENT_SESSION_EXPIREE,
  deconnecter,
  effacerSession,
  login as apiLogin,
  quiSuisJe,
  sessionProbable,
} from "@/lib/api";
import type { UtilisateurRead } from "@/types";

interface AuthContextValue {
  utilisateur: UtilisateurRead | null;
  chargement: boolean;
  connecte: boolean;
  seConnecter: (email: string, motDePasse: string) => Promise<void>;
  /** Charge l'utilisateur apres une ouverture de session faite ailleurs (activation de compte). */
  ouvrirSession: () => Promise<void>;
  seDeconnecter: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [utilisateur, setUtilisateur] = React.useState<UtilisateurRead | null>(null);
  const [chargement, setChargement] = React.useState(true);

  const chargerSession = React.useCallback(async () => {
    if (!sessionProbable()) {
      setUtilisateur(null);
      setChargement(false);
      return;
    }
    try {
      const moi = await quiSuisJe();
      setUtilisateur(moi);
    } catch {
      // Session invalide ou expiree - on efface l'indicateur plutot que de garder une
      // session fantome qui ferait echouer chaque appel suivant.
      effacerSession();
      setUtilisateur(null);
    } finally {
      setChargement(false);
    }
  }, []);

  React.useEffect(() => {
    chargerSession();
  }, [chargerSession]);

  // Session non renouvelable en cours d'usage (jeton de rafraichissement
  // invalide ou expire, voir fetchAuthentifie dans lib/api.ts) : on
  // "deconnecte" l'etat React, ce qui renvoie vers /login via AppLayout -
  // au lieu de laisser chaque page afficher des erreurs 401.
  React.useEffect(() => {
    const surExpiration = () => setUtilisateur(null);
    window.addEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
    return () => window.removeEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
  }, []);

  const seConnecter = React.useCallback(
    async (email: string, motDePasse: string) => {
      await apiLogin(email, motDePasse); // les cookies de session sont poses par le proxy
      await chargerSession();
    },
    [chargerSession]
  );

  const ouvrirSession = React.useCallback(() => chargerSession(), [chargerSession]);

  const seDeconnecter = React.useCallback(() => {
    setUtilisateur(null);
    // La redirection attend que le proxy ait efface les cookies, sinon la page de connexion pourrait
    // retrouver une session encore valide. Meme en cas d'echec reseau, on quitte l'application.
    void deconnecter().finally(() => {
      window.location.href = "/login";
    });
  }, []);

  const value = React.useMemo(
    () => ({
      utilisateur,
      chargement,
      connecte: utilisateur !== null,
      seConnecter,
      ouvrirSession,
      seDeconnecter,
    }),
    [utilisateur, chargement, seConnecter, ouvrirSession, seDeconnecter]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth doit etre utilise a l'interieur d'un AuthProvider.");
  return ctx;
}
