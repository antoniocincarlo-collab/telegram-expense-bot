-- =============================================================
-- Schema PostgreSQL — Telegram Expense Bot
-- Creazione tabelle, indici e dati di default
-- =============================================================

-- Estensione per UUID (opzionale, usiamo SERIAL per semplicità)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----- TABELLA GRUPPI -----
CREATE TABLE IF NOT EXISTS gruppi (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(128) NOT NULL,
    owner_id    BIGINT NOT NULL,               -- Telegram user_id del proprietario
    invite_token VARCHAR(64) UNIQUE NOT NULL,   -- Token univoco per inviti
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_gruppi_owner ON gruppi(owner_id);
CREATE INDEX idx_gruppi_invite ON gruppi(invite_token);

-- ----- TABELLA MEMBRI GRUPPO -----
CREATE TABLE IF NOT EXISTS membri_gruppo (
    id          SERIAL PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL,               -- Telegram user_id
    joined_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id, user_id)
);

CREATE INDEX idx_membri_group ON membri_gruppo(group_id);
CREATE INDEX idx_membri_user  ON membri_gruppo(user_id);

-- ----- TABELLA CATEGORIE -----
CREATE TABLE IF NOT EXISTS categorie (
    id          SERIAL PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    nome        VARCHAR(64) NOT NULL,
    UNIQUE(group_id, nome)
);

CREATE INDEX idx_categorie_group ON categorie(group_id);

-- ----- TABELLA SPESE -----
CREATE TABLE IF NOT EXISTS spese (
    id          SERIAL PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL,
    data        DATE NOT NULL DEFAULT CURRENT_DATE,
    importo     NUMERIC(12,2) NOT NULL CHECK (importo > 0),
    descrizione TEXT NOT NULL,
    categoria   VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_spese_group      ON spese(group_id);
CREATE INDEX idx_spese_user       ON spese(user_id);
CREATE INDEX idx_spese_data       ON spese(data);
CREATE INDEX idx_spese_categoria  ON spese(categoria);
CREATE INDEX idx_spese_group_data ON spese(group_id, data);

-- ----- TABELLA BUDGETS -----
CREATE TABLE IF NOT EXISTS budgets (
    id              SERIAL PRIMARY KEY,
    group_id        INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    categoria       VARCHAR(64) NOT NULL,
    limite_mensile  NUMERIC(12,2) NOT NULL CHECK (limite_mensile > 0),
    UNIQUE(group_id, categoria)
);

CREATE INDEX idx_budgets_group ON budgets(group_id);

-- ----- TABELLA ML_DATA (storico per training) -----
CREATE TABLE IF NOT EXISTS ml_data (
    id          SERIAL PRIMARY KEY,
    descrizione TEXT NOT NULL,
    categoria   VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ml_data_categoria ON ml_data(categoria);

-- ----- TABELLA UTENTI (mapping telegram_id → gruppo attivo) -----
CREATE TABLE IF NOT EXISTS utenti (
    user_id         BIGINT PRIMARY KEY,          -- Telegram user_id
    active_group_id INTEGER REFERENCES gruppi(id) ON DELETE SET NULL,
    username        VARCHAR(128),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- Funzione helper: inserisce categorie di default per un gruppo
-- =============================================================
CREATE OR REPLACE FUNCTION insert_default_categories(p_group_id INTEGER)
RETURNS VOID AS $$
BEGIN
    INSERT INTO categorie (group_id, nome) VALUES
        (p_group_id, 'Cibo'),
        (p_group_id, 'Trasporti'),
        (p_group_id, 'Casa'),
        (p_group_id, 'Salute'),
        (p_group_id, 'Intrattenimento'),
        (p_group_id, 'Altro')
    ON CONFLICT (group_id, nome) DO NOTHING;
END;
$$ LANGUAGE plpgsql;
