# Nombre de archivo: init.sql
# Ubicación de archivo: db/init.sql
# Descripción: Inicialización mínima de BD (schema y tabla de ejemplo)
-- Crear schema lógico para la app
CREATE SCHEMA IF NOT EXISTS app;

-- Tabla de ejemplo (puede eliminarse luego)
CREATE TABLE IF NOT EXISTS app.example (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    note TEXT
);


-- Tabla de conversaciones
CREATE TABLE IF NOT EXISTS app.conversations (
    id SERIAL PRIMARY KEY,
    tg_user_id BIGINT NOT NULL,
    started_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Tabla de mensajes
CREATE TABLE IF NOT EXISTS app.messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES app.conversations(id),
    tg_user_id BIGINT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    normalized_text TEXT,
    intent TEXT,
    confidence NUMERIC,
    provider TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_user ON app.messages(tg_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON app.messages(created_at);

