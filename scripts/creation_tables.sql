BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 056431780b2c

CREATE TABLE abonnements_webhook (
    id UUID NOT NULL, 
    url_destination VARCHAR(2048) NOT NULL, 
    secret_hmac VARCHAR(255) NOT NULL, 
    processus VARCHAR(11) NOT NULL, 
    evenements JSON NOT NULL, 
    actif BOOLEAN NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE enveloppes_budgetaires (
    id UUID NOT NULL, 
    service VARCHAR(120) NOT NULL, 
    exercice INTEGER NOT NULL, 
    budget_alloue NUMERIC(12, 2) NOT NULL, 
    budget_consomme NUMERIC(12, 2) NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_enveloppe_service_exercice UNIQUE (service, exercice)
);

CREATE TABLE jours_feries (
    id UUID NOT NULL, 
    nom VARCHAR(120) NOT NULL, 
    date DATE NOT NULL, 
    recurrent BOOLEAN NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE types_conge (
    id UUID NOT NULL, 
    code VARCHAR(40) NOT NULL, 
    nom VARCHAR(120) NOT NULL, 
    taux_acquisition_jours_mois NUMERIC(4, 2) NOT NULL, 
    actif BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (code)
);

CREATE TABLE types_demande (
    id UUID NOT NULL, 
    processus VARCHAR(11) NOT NULL, 
    nom VARCHAR(120) NOT NULL, 
    schema_champs JSON NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (processus)
);

CREATE TABLE utilisateurs (
    id UUID NOT NULL, 
    email VARCHAR(255) NOT NULL, 
    mot_de_passe_hash VARCHAR(255) NOT NULL, 
    nom_complet VARCHAR(255) NOT NULL, 
    service VARCHAR(120) NOT NULL, 
    role VARCHAR(21) NOT NULL, 
    manager_id UUID, 
    actif BOOLEAN NOT NULL, 
    cree_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_utilisateurs_email ON utilisateurs (email);

CREATE TABLE demandes (
    id UUID NOT NULL, 
    processus VARCHAR(11) NOT NULL, 
    demandeur_id UUID NOT NULL, 
    initiee_par_id UUID NOT NULL, 
    donnees JSON NOT NULL, 
    statut_global VARCHAR(18) NOT NULL, 
    creee_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(demandeur_id) REFERENCES utilisateurs (id), 
    FOREIGN KEY(initiee_par_id) REFERENCES utilisateurs (id)
);

CREATE TABLE journal_audit (
    id UUID NOT NULL, 
    action VARCHAR(80) NOT NULL, 
    acteur_id UUID, 
    cible_type VARCHAR(80) NOT NULL, 
    cible_id UUID NOT NULL, 
    details JSON NOT NULL, 
    horodate_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(acteur_id) REFERENCES utilisateurs (id)
);

CREATE TABLE soldes_conges (
    id UUID NOT NULL, 
    utilisateur_id UUID NOT NULL, 
    type_conge_id UUID NOT NULL, 
    exercice INTEGER NOT NULL, 
    jours_acquis NUMERIC(6, 1) NOT NULL, 
    jours_pris NUMERIC(6, 1) NOT NULL, 
    solde_jours NUMERIC(6, 1) NOT NULL, 
    mis_a_jour_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(type_conge_id) REFERENCES types_conge (id), 
    FOREIGN KEY(utilisateur_id) REFERENCES utilisateurs (id), 
    CONSTRAINT uq_solde_utilisateur_type_exercice UNIQUE (utilisateur_id, type_conge_id, exercice)
);

CREATE TABLE etapes_workflow (
    id UUID NOT NULL, 
    demande_id UUID NOT NULL, 
    niveau INTEGER NOT NULL, 
    role VARCHAR(18) NOT NULL, 
    approbateur_attendu_id UUID NOT NULL, 
    statut VARCHAR(10) NOT NULL, 
    jeton_decision VARCHAR(512), 
    jeton_utilise BOOLEAN NOT NULL, 
    date_reponse TIMESTAMP WITH TIME ZONE, 
    commentaire TEXT, 
    PRIMARY KEY (id), 
    FOREIGN KEY(approbateur_attendu_id) REFERENCES utilisateurs (id), 
    FOREIGN KEY(demande_id) REFERENCES demandes (id)
);

CREATE TABLE pieces_jointes (
    id UUID NOT NULL, 
    demande_id UUID NOT NULL, 
    nom_original VARCHAR(255) NOT NULL, 
    cle_stockage VARCHAR(512) NOT NULL, 
    deposee_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(demande_id) REFERENCES demandes (id)
);

INSERT INTO alembic_version (version_num) VALUES ('056431780b2c') RETURNING alembic_version.version_num;

-- Running upgrade 056431780b2c -> 51ef1470577f

CREATE TABLE jetons_decision (
    id UUID NOT NULL, 
    etape_workflow_id UUID NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    action_autorisee VARCHAR(30) NOT NULL, 
    approbateur_attendu_id UUID NOT NULL, 
    expire_a TIMESTAMP WITH TIME ZONE NOT NULL, 
    utilise_a TIMESTAMP WITH TIME ZONE, 
    revoque BOOLEAN NOT NULL, 
    cree_a TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(approbateur_attendu_id) REFERENCES utilisateurs (id), 
    FOREIGN KEY(etape_workflow_id) REFERENCES etapes_workflow (id)
);

CREATE UNIQUE INDEX ix_jetons_decision_token_hash ON jetons_decision (token_hash);

ALTER TABLE etapes_workflow DROP COLUMN jeton_utilise;

ALTER TABLE etapes_workflow DROP COLUMN jeton_decision;

ALTER TABLE journal_audit ALTER COLUMN cible_id DROP NOT NULL;

UPDATE alembic_version SET version_num='51ef1470577f' WHERE alembic_version.version_num = '056431780b2c';

-- Running upgrade 51ef1470577f -> 8b72607684ff

CREATE TABLE jetons_compte (
    id UUID NOT NULL, 
    utilisateur_id UUID NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    type_jeton VARCHAR(16) NOT NULL, 
    expire_a TIMESTAMP WITH TIME ZONE NOT NULL, 
    utilise_a TIMESTAMP WITH TIME ZONE, 
    cree_a TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(utilisateur_id) REFERENCES utilisateurs (id)
);

CREATE UNIQUE INDEX ix_jetons_compte_token_hash ON jetons_compte (token_hash);

ALTER TABLE utilisateurs ALTER COLUMN mot_de_passe_hash DROP NOT NULL;

UPDATE alembic_version SET version_num='8b72607684ff' WHERE alembic_version.version_num = '51ef1470577f';

-- Running upgrade 8b72607684ff -> a9e52d92e9a5

ALTER TABLE jetons_compte ADD COLUMN revoque BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='a9e52d92e9a5' WHERE alembic_version.version_num = '8b72607684ff';

-- Running upgrade a9e52d92e9a5 -> ad70367392a7

ALTER TABLE etapes_workflow ADD COLUMN signature_cle_stockage TEXT;

UPDATE alembic_version SET version_num='ad70367392a7' WHERE alembic_version.version_num = 'a9e52d92e9a5';

-- Running upgrade ad70367392a7 -> 6e3fd32c1f6e

CREATE TABLE messages_clarification (
    id UUID NOT NULL, 
    demande_id UUID NOT NULL, 
    auteur_id UUID NOT NULL, 
    contenu TEXT NOT NULL, 
    cree_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(auteur_id) REFERENCES utilisateurs (id), 
    FOREIGN KEY(demande_id) REFERENCES demandes (id)
);

UPDATE alembic_version SET version_num='6e3fd32c1f6e' WHERE alembic_version.version_num = 'ad70367392a7';

-- Running upgrade 6e3fd32c1f6e -> 01c3c7004910

ALTER TABLE etapes_workflow ADD COLUMN est_derogation BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='01c3c7004910' WHERE alembic_version.version_num = '6e3fd32c1f6e';

-- Running upgrade 01c3c7004910 -> 83280b4e83bc

ALTER TABLE pieces_jointes ADD COLUMN message_id UUID;

ALTER TABLE pieces_jointes ADD CONSTRAINT fk_pieces_jointes_message_id FOREIGN KEY(message_id) REFERENCES messages_clarification (id);

UPDATE alembic_version SET version_num='83280b4e83bc' WHERE alembic_version.version_num = '01c3c7004910';

-- Running upgrade 83280b4e83bc -> 2fc43a22f0db

ALTER TABLE etapes_workflow ADD COLUMN cree_le TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE etapes_workflow ADD COLUMN dernier_rappel_le TIMESTAMP WITH TIME ZONE;

ALTER TABLE etapes_workflow ADD COLUMN nombre_rappels INTEGER DEFAULT '0' NOT NULL;

UPDATE alembic_version SET version_num='2fc43a22f0db' WHERE alembic_version.version_num = '83280b4e83bc';

-- Running upgrade 2fc43a22f0db -> e831c4d76217

ALTER TABLE pieces_jointes ADD COLUMN categorie VARCHAR(30) DEFAULT 'contrat' NOT NULL;

UPDATE pieces_jointes SET categorie = 'discussion' WHERE message_id IS NOT NULL;

ALTER TABLE pieces_jointes ALTER COLUMN categorie DROP DEFAULT;

UPDATE alembic_version SET version_num='e831c4d76217' WHERE alembic_version.version_num = '2fc43a22f0db';

-- Running upgrade e831c4d76217 -> 20e05f709e2a

CREATE OR REPLACE FUNCTION journal_audit_interdire_modification() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'journal_audit est en ajout seul : UPDATE, DELETE et TRUNCATE interdits (CDC 2.4, technique 14.3)' USING ERRCODE = 'insufficient_privilege';
            END;
            $$ LANGUAGE plpgsql;

CREATE TRIGGER journal_audit_ajout_seul BEFORE UPDATE OR DELETE ON journal_audit FOR EACH ROW EXECUTE FUNCTION journal_audit_interdire_modification();

CREATE TRIGGER journal_audit_sans_truncate BEFORE TRUNCATE ON journal_audit FOR EACH STATEMENT EXECUTE FUNCTION journal_audit_interdire_modification();

UPDATE alembic_version SET version_num='20e05f709e2a' WHERE alembic_version.version_num = 'e831c4d76217';

-- Running upgrade 20e05f709e2a -> 398b7b242b1f

CREATE TABLE taux_change (
    id UUID NOT NULL, 
    devise VARCHAR(3) NOT NULL, 
    taux NUMERIC(18, 8) NOT NULL, 
    date_effet DATE NOT NULL, 
    defini_par_id UUID, 
    cree_le TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(defini_par_id) REFERENCES utilisateurs (id), 
    CONSTRAINT uq_taux_change_devise_date UNIQUE (devise, date_effet)
);

UPDATE alembic_version SET version_num='398b7b242b1f' WHERE alembic_version.version_num = '20e05f709e2a';

COMMIT;

