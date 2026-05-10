# IoT Temperature Platform

A self-hosted IoT platform for collecting and visualizing temperature, light, and battery readings from ESP32-based sensors. Sensors publish telemetry to MQTT every minute; data is stored in PostgreSQL + TimescaleDB and exposed via a FastAPI REST API consumed by a React web app (and later a React Native mobile app).

Designed for small deployments (≤10 users, ≤50 sensors) on a Hetzner VPS managed by [Coolify](https://coolify.io).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design, data model, MQTT contracts, deployment topology, and roadmap.

```
ESP32 sensor --MQTT--> mosquitto --MQTT--> ingestor --SQL--> postgres+timescaledb
                                                                     |
                                                                     v
                                                          FastAPI <--+
                                                             |
                                                             v
                                                         React web app
```

## Services

| Path        | Purpose                                                              |
| ----------- | -------------------------------------------------------------------- |
| `backend/`  | FastAPI REST API (devices, readings, aggregates) — Python 3.12       |
| `ingestor/` | MQTT subscriber that writes telemetry to the database — Python 3.12  |
| `web/`      | React 18 + Vite + TypeScript SPA                                     |
| `infra/`    | Mosquitto config and Postgres init SQL                               |
| `docs/`     | Architecture and design docs                                         |

## Local development quickstart

Prerequisites: Docker Desktop (or Docker Engine + Compose v2).

```bash
cp .env.example .env
# edit .env and fill in passwords / tokens
docker compose up
```

This brings up:

- `postgres` on `localhost:5432` (TimescaleDB image, `pg16`)
- `mosquitto` on `localhost:1883` (MQTT) and `localhost:9001` (WebSockets)
- `backend` on `localhost:8000` (FastAPI)
- `ingestor` (no exposed port — subscribes to MQTT)
- `web` on `localhost:5173` (Vite dev server with HMR)

Before MQTT will accept connections you must create a `passwords` and `acl` file in `infra/mosquitto/`. See [`infra/mosquitto/README.md`](infra/mosquitto/README.md).

## Deployment

Each service is deployed as a separate resource in Coolify pointing at this monorepo. See the deployment section of [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#deployment-topology).

## Status

This is **Phase 1** of a 7-phase roadmap. The current commit contains scaffolding only — no application code. See the roadmap section in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#roadmap) for what comes next.
