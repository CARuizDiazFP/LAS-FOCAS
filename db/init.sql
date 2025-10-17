-- Nombre de archivo: init.sql
-- Ubicación de archivo: db/init.sql
-- Descripción: Inicialización mínima de BD (schema y tabla de ejemplo)
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

-- Chat del panel web (MCP)
CREATE TABLE IF NOT EXISTS app.chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id_last_activity
    ON app.chat_sessions (user_id, last_activity);

CREATE TABLE IF NOT EXISTS app.chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES app.chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    tool_args JSONB,
    attachments JSONB,
    error_code TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_chat_messages_session_created
    ON app.chat_messages (session_id, created_at);

-- Usuarios del panel web
CREATE TABLE IF NOT EXISTS app.web_users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Usuario inicial opcional (admin/admin) — se recomienda cambiar en producción
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app.web_users WHERE username = 'admin') THEN
        INSERT INTO app.web_users (username, password_hash, role)
        VALUES (
            'admin',
            '$2b$12$FzYm7mA3xJm2A3lVf2A1nO7cS26o8u2H7m2UvRnl8F3Pj4eQq9fZK', -- bcrypt("admin")
            'admin'
        );
    END IF;
END$$;

