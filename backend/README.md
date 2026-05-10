# backend

FastAPI REST API for the IoT temperature platform. Serves device metadata and time-series readings from PostgreSQL + TimescaleDB to the web (and later mobile) frontend; auth is a static bearer token in v1. Migrations are managed with Alembic.

For the full system design, data model, and roadmap, see [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
