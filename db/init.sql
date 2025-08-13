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

