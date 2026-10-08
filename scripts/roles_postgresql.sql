-- Role applicatif PostgreSQL SANS droit de modifier le journal d'audit.
--
-- Pourquoi : le journal d'audit est protege par des declencheurs (UPDATE, DELETE et TRUNCATE
-- refuses), mais le proprietaire d'une table peut les retirer par DDL (ALTER TABLE ... DISABLE
-- TRIGGER) - verifie en reel. L'application ne doit donc PAS se connecter avec le proprietaire
-- des tables : celui-ci ne sert qu'aux migrations (alembic). Un role limite a SELECT + INSERT
-- sur journal_audit ne peut ni modifier, ni supprimer, ni retirer les declencheurs.
--
-- Usage : a executer une fois, APRES `alembic upgrade head`, avec le role proprietaire des
-- tables (celui des migrations), qui doit pouvoir creer un role :
--     psql -d <base> -f scripts/roles_postgresql.sql
-- puis faire pointer DATABASE_URL de l'application sur workflows_app (et non sur le proprietaire).
-- Remplacer le mot de passe ci-dessous avant execution.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'workflows_app') THEN
        CREATE ROLE workflows_app LOGIN PASSWORD 'A_REMPLACER';
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO workflows_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO workflows_app;

-- Droits ordinaires sur toutes les tables de l'application...
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO workflows_app;

-- ...sauf le journal d'audit : ajout et lecture seulement.
REVOKE UPDATE, DELETE, TRUNCATE ON journal_audit FROM workflows_app;

-- Journal des mouvements du solde de conges (CDC 11.1, R17) : lui aussi en ajout seul. Le solde
-- disponible n'est que la somme de ces mouvements ; pouvoir en effacer un rendrait un solde errone
-- impossible a reconstituer. L'application ne fait jamais qu'y INSERER.
REVOKE UPDATE, DELETE, TRUNCATE ON mouvements_conges FROM workflows_app;

-- Tables creees plus tard par les migrations : memes droits ordinaires par defaut. (Toute future
-- table de type journal devra retirer explicitement UPDATE/DELETE, comme ci-dessus.)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO workflows_app;
