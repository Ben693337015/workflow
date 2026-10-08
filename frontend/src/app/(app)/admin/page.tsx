"use client";

import { SqueletteListe } from "@/components/ui/squelette";
import * as React from "react";
import { Users, CalendarClock, Wallet, Landmark, Plus, Coins } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Alert,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { libelleRole } from "@/lib/roles";
import { formaterMontant } from "@/lib/montants";
import {
  ApiError,
  creerCompte,
  creerTypeConge,
  definirEnveloppeBudgetaire,
  definirSoldeConges,
  definirTauxChange,
  desactiverCompte,
  desactiverTypeConge,
  listerEnveloppesBudgetaires,
  listerDevises,
  listerSoldesConges,
  listerTauxChange,
  listerTousLesComptes,
  listerTypesConge,
  modifierCompte,
  reactiverCompte,
  reactiverTypeConge,
} from "@/lib/api";
import type { EnveloppeBudgetaire, RoleUtilisateur, SoldeCongesRead, TauxChange, TypeConge, UtilisateurRead } from "@/types";
import { TableScroll } from "@/components/ui/table";

const onglets = [
  { id: "comptes", label: "Comptes employés", icon: Users },
  { id: "types", label: "Types de congé", icon: CalendarClock },
  { id: "soldes", label: "Soldes de congés", icon: Wallet },
  { id: "budgets", label: "Budgets", icon: Landmark },
  { id: "devises", label: "Devises", icon: Coins },
] as const;

type OngletId = (typeof onglets)[number]["id"];

const rolesDisponibles: RoleUtilisateur[] = [
  "employe",
  "manager",
  "drh",
  "direction_financiere",
  "service_juridique",
  "direction_generale",
  "controleur_de_gestion",
];

export default function AdminPage() {
  const [ongletActif, setOngletActif] = React.useState<OngletId>("comptes");
  const [erreur, setErreur] = React.useState<string | null>(null);

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 titre-page">Administration</h1>
      <p className="mb-6 text-[13.5px] text-ink-dim">
        Comptes employés, types de congé et soldes — réservé au rôle DRH.
      </p>

      {erreur && (
        <div className="mb-4">
          <Alert variant="destructive">{erreur}</Alert>
        </div>
      )}

      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
        {onglets.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setOngletActif(id)}
            className={cn(
              "flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3.5 py-2.5 text-[13.5px] font-medium transition-colors",
              ongletActif === id
                ? "border-accent text-ink"
                : "border-transparent text-ink-dim hover:text-ink"
            )}
          >
            <Icon className="h-4 w-4" strokeWidth={1.8} />
            {label}
          </button>
        ))}
      </div>

      {ongletActif === "comptes" && <OngletComptes onErreur={setErreur} />}
      {ongletActif === "types" && <OngletTypesConge onErreur={setErreur} />}
      {ongletActif === "soldes" && <OngletSoldes onErreur={setErreur} />}
      {ongletActif === "budgets" && <OngletBudgets onErreur={setErreur} />}
      {ongletActif === "devises" && <OngletDevises onErreur={setErreur} />}
    </div>
  );
}

function OngletComptes({ onErreur }: { onErreur: (m: string | null) => void }) {
  const [comptes, setComptes] = React.useState<UtilisateurRead[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [formulaireOuvert, setFormulaireOuvert] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [nomComplet, setNomComplet] = React.useState("");
  const [service, setService] = React.useState("");
  const [role, setRole] = React.useState<RoleUtilisateur>("employe");
  const [managerNouveau, setManagerNouveau] = React.useState("");
  const [enCours, setEnCours] = React.useState(false);
  // Changement de manager (DRH) : un seul compte en edition a la fois.
  const [compteEnEdition, setCompteEnEdition] = React.useState<string | null>(null);
  const [managerChoisi, setManagerChoisi] = React.useState("");
  const [info, setInfo] = React.useState<string | null>(null);

  const charger = React.useCallback(() => {
    setChargement(true);
    listerTousLesComptes()
      .then(setComptes)
      .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les comptes."))
      .finally(() => setChargement(false));
  }, [onErreur]);

  React.useEffect(() => {
    charger();
  }, [charger]);

  async function onCreerCompte(e: React.FormEvent) {
    e.preventDefault();
    onErreur(null);
    setEnCours(true);
    try {
      await creerCompte({
        email,
        nom_complet: nomComplet,
        service,
        role,
        ...(managerNouveau ? { manager_id: managerNouveau } : {}),
      });
      setEmail("");
      setNomComplet("");
      setService("");
      setRole("employe");
      setManagerNouveau("");
      setFormulaireOuvert(false);
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible de créer le compte.");
    } finally {
      setEnCours(false);
    }
  }

  async function onBasculerActif(compte: UtilisateurRead) {
    onErreur(null);
    try {
      if (compte.actif) await desactiverCompte(compte.id);
      else await reactiverCompte(compte.id);
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Action impossible.");
    }
  }

  const nomDe = (id: string | null) => comptes.find((c) => c.id === id)?.nom_complet ?? null;
  // Managers possibles : comptes actifs au role superieur a « employe » (meme regle que le serveur).
  const managersPossibles = (exclure?: string) =>
    comptes.filter((c) => c.actif && c.role !== "employe" && c.id !== exclure);

  function ouvrirEdition(c: UtilisateurRead) {
    setInfo(null);
    onErreur(null);
    setCompteEnEdition(c.id);
    setManagerChoisi(c.manager_id ?? "");
  }

  async function onEnregistrerManager(c: UtilisateurRead) {
    onErreur(null);
    setInfo(null);
    if ((c.manager_id ?? "") === managerChoisi) {
      setCompteEnEdition(null);
      return;
    }
    try {
      const resultat = await modifierCompte(c.id, { manager_id: managerChoisi || null });
      const nom = nomDe(resultat.manager_id) ?? "aucun manager";
      const n = resultat.demandes_reaffectees;
      setInfo(
        `Manager de ${c.nom_complet} : ${nom}.` +
          (n > 0 ? ` ${n} demande${n > 1 ? "s" : ""} en cours transmise${n > 1 ? "s" : ""} au nouveau manager.` : "")
      );
      setCompteEnEdition(null);
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible de modifier le manager.");
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Comptes employés</CardTitle>
          <CardDescription>Création, désactivation, réactivation, rattachement au manager.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setFormulaireOuvert((o) => !o)}>
          <Plus className="h-4 w-4" />
          Nouveau compte
        </Button>
      </CardHeader>

      {formulaireOuvert && (
        <div className="border-b border-line px-6 py-5">
          <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={onCreerCompte}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nouveau-nom">Nom complet</Label>
              <Input id="nouveau-nom" value={nomComplet} onChange={(e) => setNomComplet(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nouveau-email">E-mail</Label>
              <Input id="nouveau-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nouveau-service">Service</Label>
              <Input id="nouveau-service" value={service} onChange={(e) => setService(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nouveau-role">Rôle</Label>
              <Select id="nouveau-role" value={role} onChange={(e) => setRole(e.target.value as RoleUtilisateur)}>
                {rolesDisponibles.map((r) => (
                  <option key={r} value={r}>
                    {libelleRole(r)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nouveau-manager">Manager (facultatif)</Label>
              <Select id="nouveau-manager" value={managerNouveau} onChange={(e) => setManagerNouveau(e.target.value)}>
                <option value="">Aucun manager pour l'instant</option>
                {managersPossibles().map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nom_complet} — {m.service}
                  </option>
                ))}
              </Select>
            </div>
            <div className="col-span-2">
              <Button type="submit" disabled={enCours} className="h-10 w-full">
                {enCours ? "Création…" : "Créer le compte"}
              </Button>
            </div>
          </form>
        </div>
      )}

      <CardContent className="p-0">
        {info && (
          <div className="border-b border-line px-6 py-3">
            <Alert variant="success">{info}</Alert>
          </div>
        )}
        {chargement ? (
          <SqueletteListe className="px-6 py-5" />
        ) : (
          <TableScroll>
          <table className="tableau-cartes w-full text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                <th className="px-6 py-3 font-medium">Compte</th>
                <th className="px-6 py-3 font-medium">Rôle</th>
                <th className="px-6 py-3 font-medium">Manager</th>
                <th className="px-6 py-3 font-medium">Statut</th>
                <th className="px-6 py-3 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {comptes.map((c) => (
                <tr key={c.id} className="border-b border-line last:border-0 hover:bg-canvas">
                  <td data-label="Compte" className="cell-texte px-6 py-3.5">
                    <div>
                      <div className="font-medium text-ink">{c.nom_complet}</div>
                      <div className="text-[12.5px] text-ink-dim [overflow-wrap:anywhere]">{c.email}</div>
                    </div>
                  </td>
                  <td data-label="Rôle" className="cell-fixe px-6 py-3.5 text-ink-dim">{libelleRole(c.role)}</td>
                  <td data-label="Manager" className="px-6 py-3.5">
                    {compteEnEdition === c.id ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Select
                          aria-label={`Manager de ${c.nom_complet}`}
                          value={managerChoisi}
                          onChange={(e) => setManagerChoisi(e.target.value)}
                          className="h-9 max-w-[16rem]"
                        >
                          <option value="">Aucun manager</option>
                          {managersPossibles(c.id).map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.nom_complet} — {m.service}
                            </option>
                          ))}
                        </Select>
                        <Button size="sm" onClick={() => onEnregistrerManager(c)}>
                          Enregistrer
                        </Button>
                        <button onClick={() => setCompteEnEdition(null)} className="text-[12.5px] text-ink-dim hover:underline">
                          Annuler
                        </button>
                      </div>
                    ) : nomDe(c.manager_id) ? (
                      <span className="text-ink-dim">{nomDe(c.manager_id)}</span>
                    ) : (
                      <Badge className="bg-warn-soft text-warn">Aucun manager</Badge>
                    )}
                  </td>
                  <td data-label="Statut" className="px-6 py-3.5">
                    <Badge className={c.actif ? "" : "bg-danger-soft text-danger"}>
                      {c.actif ? "Actif" : "Désactivé"}
                    </Badge>
                  </td>
                  <td data-label="Action" className="px-6 py-3.5">
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      {compteEnEdition !== c.id && (
                        <button
                          onClick={() => ouvrirEdition(c)}
                          aria-label={`${c.manager_id ? "Changer" : "Attribuer"} le manager de ${c.nom_complet}`}
                          className="text-[12.5px] text-accent-text hover:underline"
                        >
                          {c.manager_id ? "Changer le manager" : "Attribuer un manager"}
                        </button>
                      )}
                      <button
                        onClick={() => onBasculerActif(c)}
                        className="text-[12.5px] text-accent-text hover:underline"
                      >
                        {c.actif ? "Désactiver" : "Réactiver"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        )}
      </CardContent>
    </Card>
  );
}

function OngletTypesConge({ onErreur }: { onErreur: (m: string | null) => void }) {
  const [types, setTypes] = React.useState<TypeConge[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [formulaireOuvert, setFormulaireOuvert] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [nom, setNom] = React.useState("");
  const [taux, setTaux] = React.useState("2.08");
  const [enCours, setEnCours] = React.useState(false);

  const charger = React.useCallback(() => {
    setChargement(true);
    listerTypesConge(true)
      .then(setTypes)
      .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les types de congé."))
      .finally(() => setChargement(false));
  }, [onErreur]);

  React.useEffect(() => {
    charger();
  }, [charger]);

  async function onCreerType(e: React.FormEvent) {
    e.preventDefault();
    onErreur(null);
    setEnCours(true);
    try {
      await creerTypeConge({ code, nom, taux_acquisition_jours_mois: parseFloat(taux) });
      setCode("");
      setNom("");
      setTaux("2.08");
      setFormulaireOuvert(false);
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible de créer ce type de congé.");
    } finally {
      setEnCours(false);
    }
  }

  async function onBasculerActif(type: TypeConge) {
    onErreur(null);
    try {
      if (type.actif) await desactiverTypeConge(type.id);
      else await reactiverTypeConge(type.id);
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Action impossible.");
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Types de congé</CardTitle>
          <CardDescription>Désactiver un type le retire du formulaire de demande.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setFormulaireOuvert((o) => !o)}>
          <Plus className="h-4 w-4" />
          Nouveau type
        </Button>
      </CardHeader>

      {formulaireOuvert && (
        <div className="border-b border-line px-6 py-5">
          <form className="grid grid-cols-1 gap-3 sm:grid-cols-3" onSubmit={onCreerType}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="type-code">Code</Label>
              <Input id="type-code" value={code} onChange={(e) => setCode(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="type-nom">Nom</Label>
              <Input id="type-nom" value={nom} onChange={(e) => setNom(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="type-taux">Jours/mois</Label>
              <Input
                id="type-taux"
                type="number"
                step="0.01"
                value={taux}
                onChange={(e) => setTaux(e.target.value)}
                required
              />
            </div>
            <div className="col-span-3">
              <Button type="submit" disabled={enCours} className="h-10 w-full">
                {enCours ? "Création…" : "Créer le type"}
              </Button>
            </div>
          </form>
        </div>
      )}

      <CardContent className="p-0">
        {chargement ? (
          <SqueletteListe className="px-6 py-5" />
        ) : (
          <TableScroll>
          <table className="w-full text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                <th className="px-6 py-3 font-medium">Code</th>
                <th className="px-6 py-3 font-medium">Nom</th>
                <th className="px-6 py-3 font-medium">Statut</th>
                <th className="px-6 py-3 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {types.map((t) => (
                <tr key={t.id} className="border-b border-line last:border-0 hover:bg-canvas">
                  <td className="cell-texte px-6 py-3.5 font-medium text-ink">{t.code}</td>
                  <td className="cell-texte px-6 py-3.5 text-ink-dim">{t.nom}</td>
                  <td className="px-6 py-3.5">
                    <Badge className={t.actif ? "" : "bg-danger-soft text-danger"}>
                      {t.actif ? "Actif" : "Désactivé"}
                    </Badge>
                  </td>
                  <td className="px-6 py-3.5">
                    <button
                      onClick={() => onBasculerActif(t)}
                      className="text-[12.5px] text-accent-text hover:underline"
                    >
                      {t.actif ? "Désactiver" : "Réactiver"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        )}
      </CardContent>
    </Card>
  );
}

function OngletSoldes({ onErreur }: { onErreur: (m: string | null) => void }) {
  const [comptes, setComptes] = React.useState<UtilisateurRead[]>([]);
  const [types, setTypes] = React.useState<TypeConge[]>([]);
  const [employeId, setEmployeId] = React.useState("");
  const [soldes, setSoldes] = React.useState<SoldeCongesRead[]>([]);
  const [typeCongeId, setTypeCongeId] = React.useState("");
  const [joursAcquis, setJoursAcquis] = React.useState("25");
  const [chargement, setChargement] = React.useState(true);
  const [enCours, setEnCours] = React.useState(false);

  React.useEffect(() => {
    Promise.all([listerTousLesComptes(), listerTypesConge()])
      .then(([c, t]) => {
        setComptes(c);
        setTypes(t);
        if (c.length > 0) setEmployeId(c[0].id);
        if (t.length > 0) setTypeCongeId(t[0].id);
      })
      .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les données."))
      .finally(() => setChargement(false));
  }, [onErreur]);

  const chargerSoldes = React.useCallback(
    (id: string) => {
      if (!id) return;
      listerSoldesConges(id)
        .then(setSoldes)
        .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les soldes."));
    },
    [onErreur]
  );

  React.useEffect(() => {
    if (employeId) chargerSoldes(employeId);
  }, [employeId, chargerSoldes]);

  async function onDefinirSolde(e: React.FormEvent) {
    e.preventDefault();
    onErreur(null);
    setEnCours(true);
    try {
      await definirSoldeConges(employeId, {
        type_conge_id: typeCongeId,
        exercice: new Date().getFullYear(),
        jours_acquis: parseFloat(joursAcquis),
      });
      chargerSoldes(employeId);
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible d'enregistrer ce solde.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Soldes de congés</CardTitle>
        <CardDescription>Modifier un solde préserve les jours déjà consommés.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 pt-2">
        {chargement ? (
          <SqueletteListe />
        ) : (
          <>
            <form className="grid grid-cols-1 gap-3 rounded-lg bg-canvas p-4 sm:grid-cols-3" onSubmit={onDefinirSolde}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="solde-employe">Employé</Label>
                <Select id="solde-employe" value={employeId} onChange={(e) => setEmployeId(e.target.value)}>
                  {comptes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nom_complet}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="solde-type">Type de congé</Label>
                <Select id="solde-type" value={typeCongeId} onChange={(e) => setTypeCongeId(e.target.value)}>
                  {types.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.nom}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="solde-jours">Jours acquis</Label>
                <Input
                  id="solde-jours"
                  type="number"
                  min={0}
                  value={joursAcquis}
                  onChange={(e) => setJoursAcquis(e.target.value)}
                />
              </div>
              <div className="col-span-3">
                <Button type="submit" disabled={enCours} className="h-10 w-full">
                  {enCours ? "Enregistrement…" : "Enregistrer"}
                </Button>
              </div>
            </form>

            <TableScroll>
            <table className="w-full text-left text-[13.5px]">
              <thead>
                <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                  <th className="py-2.5 font-medium">Exercice</th>
                  <th className="py-2.5 font-medium">Acquis</th>
                  <th className="py-2.5 font-medium">Pris</th>
                  <th className="py-2.5 font-medium">Disponible</th>
                </tr>
              </thead>
              <tbody>
                {soldes.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-3 text-ink-faint">
                      Aucun solde défini pour cet employé.
                    </td>
                  </tr>
                )}
                {soldes.map((s) => (
                  <tr key={s.id} className="border-b border-line last:border-0">
                    <td className="py-3 text-ink-dim">{s.exercice}</td>
                    <td className="py-3 text-ink-dim">{s.jours_acquis}</td>
                    <td className="py-3 text-ink-dim">{s.jours_pris}</td>
                    <td className="py-3 font-medium text-accent-ink">{s.solde_jours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          </>
        )}
      </CardContent>
    </Card>
  );
}


function OngletBudgets({ onErreur }: { onErreur: (m: string | null) => void }) {
  const [enveloppes, setEnveloppes] = React.useState<EnveloppeBudgetaire[]>([]);
  const [services, setServices] = React.useState<string[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [service, setService] = React.useState("");
  const [exercice, setExercice] = React.useState(String(new Date().getFullYear()));
  const [budget, setBudget] = React.useState("");
  const [enCours, setEnCours] = React.useState(false);
  // Devise de référence des enveloppes (configurable côté serveur) : jamais « € » en dur.
  const [reference, setReference] = React.useState("EUR");
  React.useEffect(() => {
    (async () => {
      try {
        setReference((await listerDevises()).reference);
      } catch {
        /* on garde EUR : l'affichage ne doit jamais dépendre de cet appel */
      }
    })();
  }, []);

  const charger = React.useCallback(() => {
    setChargement(true);
    Promise.all([listerEnveloppesBudgetaires(), listerTousLesComptes()])
      .then(([env, comptes]) => {
        setEnveloppes(env);
        // Le suivi budgetaire retrouve l'enveloppe par correspondance EXACTE
        // du service du demandeur : proposer les services reellement
        // presents dans les comptes evite une faute de frappe silencieuse
        // (enveloppe creee mais jamais retrouvee, donc 0 EUR disponible).
        setServices(Array.from(new Set(comptes.map((c) => c.service))).sort());
      })
      .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les budgets."))
      .finally(() => setChargement(false));
  }, [onErreur]);

  React.useEffect(() => {
    charger();
  }, [charger]);

  async function onDefinir(e: React.FormEvent) {
    e.preventDefault();
    onErreur(null);
    setEnCours(true);
    try {
      await definirEnveloppeBudgetaire({
        service: service.trim(),
        exercice: parseInt(exercice, 10),
        budget_alloue: parseFloat(budget),
      });
      setBudget("");
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible d'enregistrer ce budget.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Enveloppes budgétaires</CardTitle>
        <CardDescription>
          Sans enveloppe, un service dispose de 0 : toute note de frais ou demande d&apos;achat part en
          dérogation. Redéfinir un budget ne touche jamais au montant déjà consommé.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 pt-2">
        <form className="grid grid-cols-1 gap-3 rounded-lg bg-canvas p-4 sm:grid-cols-3" onSubmit={onDefinir}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="budget-service">Service</Label>
            <Input
              id="budget-service"
              list="budget-services"
              value={service}
              onChange={(e) => setService(e.target.value)}
              required
            />
            <datalist id="budget-services">
              {services.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="budget-exercice">Exercice</Label>
            <Input
              id="budget-exercice"
              type="number"
              min={2000}
              max={2100}
              value={exercice}
              onChange={(e) => setExercice(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="budget-alloue">Budget alloué ({reference})</Label>
            <Input
              id="budget-alloue"
              type="number"
              min={0}
              step="0.01"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              required
            />
          </div>
          <div className="sm:col-span-3">
            <Button type="submit" disabled={enCours} className="h-10 w-full">
              {enCours ? "Enregistrement…" : "Enregistrer l'enveloppe"}
            </Button>
          </div>
        </form>

        {chargement ? (
          <SqueletteListe />
        ) : (
          <TableScroll>
          <table className="w-full text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                <th className="py-2.5 font-medium">Service</th>
                <th className="py-2.5 font-medium">Exercice</th>
                <th className="py-2.5 font-medium">Alloué</th>
                <th className="py-2.5 font-medium">Consommé</th>
                <th className="py-2.5 font-medium">Disponible</th>
              </tr>
            </thead>
            <tbody>
              {enveloppes.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-3 text-ink-faint">
                    Aucune enveloppe définie.
                  </td>
                </tr>
              )}
              {enveloppes.map((e) => (
                <tr key={e.id} className="border-b border-line last:border-0">
                  <td className="cell-texte py-3 font-medium text-ink">{e.service}</td>
                  <td className="py-3 text-ink-dim">{e.exercice}</td>
                  <td className="py-3 text-ink-dim">{formaterMontant(Number(e.budget_alloue), reference)}</td>
                  <td className="py-3 text-ink-dim">{formaterMontant(Number(e.budget_consomme), reference)}</td>
                  <td className={`py-3 font-medium ${e.solde_disponible < 0 ? "text-danger" : "text-accent-ink"}`}>
                    {formaterMontant(Number(e.solde_disponible), reference)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        )}
      </CardContent>
    </Card>
  );
}


/**
 * Taux de change (decision du 28/09 : plusieurs devises avec conversion). Un taux exprime combien
 * d'unites de la devise de reference (EUR) valent 1 unite de la devise saisie. Le mettre a jour ne
 * change jamais un engagement deja pris : le taux est fige sur chaque demande a sa soumission.
 */
function OngletDevises({ onErreur }: { onErreur: (m: string | null) => void }) {
  const [taux, setTaux] = React.useState<TauxChange[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [devise, setDevise] = React.useState("");
  const [valeurTaux, setValeurTaux] = React.useState("");
  const [dateEffet, setDateEffet] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [enCours, setEnCours] = React.useState(false);

  const charger = React.useCallback(() => {
    setChargement(true);
    listerTauxChange()
      .then(setTaux)
      .catch((err) => onErreur(err instanceof ApiError ? err.message : "Impossible de charger les taux de change."))
      .finally(() => setChargement(false));
  }, [onErreur]);

  React.useEffect(() => {
    charger();
  }, [charger]);

  async function onDefinir(e: React.FormEvent) {
    e.preventDefault();
    onErreur(null);
    setEnCours(true);
    try {
      await definirTauxChange({ devise: devise.trim().toUpperCase(), taux: parseFloat(valeurTaux), date_effet: dateEffet });
      setDevise("");
      setValeurTaux("");
      charger();
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : "Impossible d'enregistrer ce taux.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Taux de change</CardTitle>
        <CardDescription>
          1 unité de la devise saisie = ce nombre d&apos;euros. Le taux appliqué à une dépense est le plus récent
          dont la date d&apos;effet n&apos;est pas postérieure à la date de la dépense, et il est figé à la
          soumission : le modifier ici ne change jamais un engagement déjà pris.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 pt-2">
        <form className="grid grid-cols-1 gap-3 rounded-lg bg-canvas p-4 sm:grid-cols-4" onSubmit={onDefinir}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="taux-devise">Devise (code ISO)</Label>
            <Input
              id="taux-devise"
              value={devise}
              onChange={(e) => setDevise(e.target.value)}
              placeholder="USD"
              maxLength={3}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="taux-valeur">1 devise = X €</Label>
            <Input
              id="taux-valeur"
              type="number"
              step="0.00000001"
              min="0"
              value={valeurTaux}
              onChange={(e) => setValeurTaux(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="taux-date">Date d&apos;effet</Label>
            <Input id="taux-date" type="date" value={dateEffet} onChange={(e) => setDateEffet(e.target.value)} required />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={enCours} className="w-full gap-1.5">
              <Plus className="h-4 w-4" />
              Enregistrer
            </Button>
          </div>
        </form>

        <div className="overflow-x-auto">
          <TableScroll>
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                <th className="py-2.5 pr-3 font-medium">Devise</th>
                <th className="py-2.5 pr-3 font-medium">Taux (1 devise = X €)</th>
                <th className="py-2.5 font-medium">Date d&apos;effet</th>
              </tr>
            </thead>
            <tbody>
              {!chargement && taux.length === 0 && (
                <tr>
                  <td colSpan={3} className="py-4 text-ink-faint">
                    Aucun taux défini : seul l&apos;euro est utilisable pour l&apos;instant.
                  </td>
                </tr>
              )}
              {taux.map((t) => (
                <tr key={t.id} className="border-b border-line last:border-0">
                  <td className="py-2.5 pr-3 font-medium text-ink">{t.devise}</td>
                  <td className="py-2.5 pr-3 text-ink-dim">{t.taux}</td>
                  <td className="py-2.5 text-ink-dim">{new Date(t.date_effet).toLocaleDateString("fr-FR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        </div>
      </CardContent>
    </Card>
  );
}
