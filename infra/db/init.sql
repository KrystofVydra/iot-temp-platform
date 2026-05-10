-- Runs once, the first time the postgres container initializes its data dir.
-- Anything beyond enabling the extension is handled by Alembic migrations
-- (see backend/alembic/versions/) so it lives under version control with the
-- rest of the schema.

CREATE EXTENSION IF NOT EXISTS timescaledb;
