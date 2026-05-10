# IoT Temperature Platform — Architecture

This document is the canonical design spec. Everything else in the repo (Dockerfiles, configs, future code) should be consistent with what is written here. Update this doc when the design changes.

---

## 1. System overview

The platform ingests telemetry from a fleet of ESP32-based temperature sensors, persists it in a time-series database, and serves it to a web (and later mobile) UI.

```
                                                +--------------------+
                                                |   ESP32 sensor #N  |
                                                |  temp / lux / batt |
                                                +----------+---------+
                                                           |
                                                  MQTT publish (1/min)
                                                           |
                                                           v
                  +----------------------------------------------+
                  |             Eclipse Mosquitto 2.x            |
                  |  topic: devices/{device_key}/telemetry        |
                  +-----------------------+----------------------+
                                          |
                                  MQTT subscribe
                                          |
                                          v
                  +----------------------------------------------+
                  |           Ingestor (Python + aiomqtt)         |
                  |  validates + decodes + writes to readings     |
                  +-----------------------+----------------------+
                                          |
                                       SQL INSERT
                                          |
                                          v
                  +----------------------------------------------+
                  |     PostgreSQL 16 + TimescaleDB extension     |
                  |  hypertable: readings(time, device_id, ...)   |
                  +-----------------------+----------------------+
                                          ^
                                       SQL SELECT
                                          |
                  +-----------------------+----------------------+
                  |        Backend (FastAPI + SQLAlchemy 2)       |
                  |  REST: /devices, /readings, /healthz          |
                  +-----------------------+----------------------+
                                          ^
                                        HTTPS
                                          |
                  +----------------------------------------------+
                  |   Web app (React 18 + Vite + TanStack Query) |
                  |   Mobile app (React Native, future phase)    |
                  +----------------------------------------------+
```

All services run in containers. In production, [Coolify](https://coolify.io) on a Hetzner VPS orchestrates them and Traefik fronts HTTP traffic with TLS.

---

## 2. Technology choices and rationale

| Layer        | Choice                              | Why                                                                                                                                                                                  |
| ------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Sensor       | ESP32                               | Cheap, low-power, Wi-Fi + deep sleep, mature MQTT libraries.                                                                                                                         |
| Transport    | MQTT (Mosquitto 2.x)                | Standard for constrained devices; small framing overhead; pub/sub fits a fan-in topology; Mosquitto is the lightweight reference broker.                                             |
| Time-series  | PostgreSQL 16 + TimescaleDB         | Keeps a single database for both relational (devices, users) and time-series data. Hypertables, continuous aggregates, and compression solve the time-series scaling story natively. |
| Backend lang | Python 3.12                         | Fast iteration, large ecosystem, the team is fluent in it. 3.12 for performance + modern typing.                                                                                     |
| API          | FastAPI                             | Async-native, Pydantic-based validation, OpenAPI for free, low ceremony.                                                                                                             |
| ORM          | SQLAlchemy 2.0 (async) + asyncpg    | Mature, composable, async cursor support; asyncpg is the fastest Postgres driver for Python.                                                                                         |
| Migrations   | Alembic                             | The standard SQLAlchemy companion; reads `DATABASE_URL` from env so it works the same in CI, local, and prod.                                                                        |
| Validation   | Pydantic v2                         | Shared schema between API I/O and ingestor payload validation; v2 is rust-backed and ~10× faster than v1.                                                                            |
| Ingestor     | aiomqtt                             | Async MQTT client built on paho; integrates cleanly with an asyncpg connection pool.                                                                                                 |
| Web build    | Vite + React 18 + TS                | Fast dev server, sensible defaults, native TS support.                                                                                                                               |
| Data fetch   | TanStack Query                      | Caching, background refetch, request dedup — saves writing a lot of glue code for a polling-heavy UI.                                                                                |
| Charts       | Recharts                            | Declarative, React-friendly, sufficient for line/area charts of time-series data.                                                                                                    |
| CSS          | Tailwind                            | Utility-first; avoids a bespoke design system at this scale.                                                                                                                         |
| Containers   | Docker (Compose locally, Coolify in prod) | Same artifact runs everywhere. Coolify handles TLS, deploys, and per-service env vars without us writing Kubernetes manifests.                                              |

---

## 3. Data model

Three tables live in the public schema. `readings` is a TimescaleDB hypertable; the other two are plain Postgres tables.

### Schema (canonical SQL — Phase 2 will land this as the first Alembic migration)

```sql
-- Provided by infra/db/init.sql at first boot.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Users. v1 runs single-user but the table is in place so future auth is non-breaking.
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Devices. device_key is the stable identifier the sensor uses in MQTT topics
-- (e.g. devices/{device_key}/telemetry). It is what the firmware is flashed with.
CREATE TABLE devices (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_key    TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    location      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ
);

CREATE INDEX devices_user_id_idx ON devices(user_id);

-- Telemetry. Stored as a hypertable partitioned on `time`.
-- Raw sensor values are kept verbatim; conversion to physical units (°C, lux, V)
-- happens at read time so we can fix calibration bugs retroactively.
CREATE TABLE readings (
    time         TIMESTAMPTZ      NOT NULL,
    device_id    BIGINT           NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    temperature  REAL             NOT NULL,   -- already-decoded °C from raw uint16 t
    lux          INTEGER          NOT NULL,   -- already-decoded lux from raw uint16 l
    battery_raw  INTEGER          NOT NULL,   -- raw ADC counts (uint16) — decoded at read time
    rssi         SMALLINT
);

SELECT create_hypertable('readings', 'time');

CREATE INDEX readings_device_time_idx ON readings (device_id, time DESC);
```

### Field notes

- `temperature` and `lux` are stored decoded because their decoding is fixed by the sensor hardware and unlikely to change.
- `battery_raw` is kept as the raw ADC count so we can re-derive voltage / percentage if the divider network or reference voltage changes between hardware revisions.
- `rssi` is nullable — older firmware revisions may not include it.
- Phase 6 adds: continuous aggregates for hourly/daily rollups, a compression policy for readings older than 7 days, a retention policy (TBD), and a "device offline" view derived from `last_seen_at`.

---

## 4. MQTT contract

### Topic structure

| Topic                                | Direction         | Purpose                                                       |
| ------------------------------------ | ----------------- | ------------------------------------------------------------- |
| `devices/{device_key}/telemetry`     | sensor → broker   | Periodic readings (Phase 1–3).                                |
| `devices/{device_key}/status`        | sensor → broker   | Reserved. Online/offline + LWT for Phase 6.                   |
| `devices/{device_key}/cmd`           | broker → sensor   | Reserved. Future config or OTA commands.                      |

`{device_key}` is opaque to the broker; it is the same string that appears in `devices.device_key` and is used to authorize the device's MQTT user (see ACL below).

### Telemetry payload

JSON, published with QoS 1, retain=false:

```json
{
  "t": 12345,
  "l": 678,
  "b": 9012
}
```

- `t` — uint16, raw temperature. Conversion to °C is applied by the ingestor.
- `l` — uint16, raw light reading. Conversion to lux is applied by the ingestor.
- `b` — uint16, raw battery ADC reading. Stored as-is (`battery_raw`).

The ingestor adds:
- `time` — broker receive time (`now()` at insert; firmware does not need an RTC).
- `rssi` — pulled from a `r` field if present, otherwise `NULL`.

The exact decoding constants for `t` and `l` are firmware-specific and will be documented in the ingestor source in Phase 3.

### Authentication

Each physical device gets its own MQTT username/password (managed in `mosquitto_passwd`) and an ACL entry restricting it to its own topic prefix. The ingestor uses a separate service account with broad subscribe rights on `devices/+/telemetry`.

---

## 5. REST API (planned for Phase 4)

All endpoints require the `Authorization: Bearer ${API_TOKEN}` header (v1 auth — see §6).

| Method | Path                                  | Purpose                                                    |
| ------ | ------------------------------------- | ---------------------------------------------------------- |
| GET    | `/healthz`                            | Liveness probe. Returns 200 + DB ping status.              |
| GET    | `/devices`                            | List all devices visible to the caller.                    |
| POST   | `/devices`                            | Register a new device. Body: `{ device_key, name, location? }`. |
| GET    | `/devices/{id}/readings/latest`       | Most recent reading for a device.                          |
| GET    | `/devices/{id}/readings?from&to&bucket` | Time-bucketed series; `bucket` is e.g. `1m`, `5m`, `1h`. |

Pagination, error shape, and OpenAPI examples will land alongside the implementation in Phase 4.

---

## 6. Auth strategy

**v1 (this and the next several phases):** a single static bearer token (`API_TOKEN` env var) gates the entire API. The frontend embeds it (or, for true single-user use, it's set in localStorage by the operator). This is appropriate because:

- The deployment is single-tenant initially.
- The API is reached over TLS via Traefik.
- The schema already has a `users` table with `id`, so when real auth is introduced no schema migration is required for existing rows — they get attached to the bootstrap user.

**Future (post-v1):** real JWT auth with hashed passwords (or OAuth via a provider). The `users` table will gain `password_hash` and any other auth fields in a regular Alembic migration. The API token path will be retired or kept only for service-to-service callers (e.g., the ingestor, if it ever talks to the API).

---

## 7. Deployment topology

Each service is a separate Coolify *resource* pointing at this same repo, distinguished by the build context / Dockerfile path:

| Coolify resource | Source                                 | Notes                                                             |
| ---------------- | -------------------------------------- | ----------------------------------------------------------------- |
| `postgres`       | `timescale/timescaledb:latest-pg16` (image, not built) | Mount `infra/db/init.sql`. Persistent volume.   |
| `mosquitto`      | `eclipse-mosquitto:2` (image, not built) | Mount `infra/mosquitto/mosquitto.conf` and the secret files.    |
| `backend`        | Build from `backend/Dockerfile`        | Public via Traefik; TLS terminated there. Reads `DATABASE_URL`, `API_TOKEN`. |
| `ingestor`       | Build from `ingestor/Dockerfile`       | No public route. Reads `DATABASE_URL`, `MQTT_*`.                  |
| `web`            | Build from `web/Dockerfile`            | nginx serving the built SPA. Public via Traefik. Reads `VITE_API_URL` at build time. |

Coolify provides URLs of the form `<resource>.<server>.coolify.app` until a real domain is attached.

`docker-compose.yml` at the repo root is for *local development only* and is not used by Coolify.

---

## 8. Environment variables

Every variable is documented in `.env.example`. Summary:

| Variable            | Set in (compose / Coolify)                               | Consumed by                |
| ------------------- | -------------------------------------------------------- | -------------------------- |
| `POSTGRES_USER`     | `.env` / Coolify postgres resource                       | postgres init              |
| `POSTGRES_PASSWORD` | `.env` / Coolify postgres resource                       | postgres init              |
| `POSTGRES_DB`       | `.env` / Coolify postgres resource                       | postgres init              |
| `DATABASE_URL`      | `.env` / Coolify backend & ingestor resources            | backend, ingestor, alembic |
| `MQTT_HOST`         | `.env` / Coolify ingestor resource                       | ingestor                   |
| `MQTT_PORT`         | `.env` / Coolify ingestor resource                       | ingestor                   |
| `MQTT_USERNAME`     | `.env` / Coolify ingestor resource                       | ingestor                   |
| `MQTT_PASSWORD`     | `.env` / Coolify ingestor resource                       | ingestor                   |
| `API_TOKEN`         | `.env` / Coolify backend resource                        | backend (and any client)   |
| `VITE_API_URL`      | `.env` / Coolify web resource (build-time)               | web (baked into bundle)    |

`VITE_API_URL` is a build-time variable; changing it requires a web rebuild.

---

## 9. Roadmap

The project is delivered in seven phases. Each phase is independently shippable.

1. **Architecture & repo scaffolding** *(this phase)* — directory layout, Dockerfiles, configs, this document. No application code.
2. **Database + MQTT broker deployed on VPS** — Coolify resources for postgres and mosquitto live; first Alembic migration creates `users`, `devices`, `readings`. Manual `mosquitto_passwd` setup for the ingestor and the first sensor.
3. **Ingestor service** — aiomqtt subscriber decodes telemetry and writes to `readings`. Updates `devices.last_seen_at`. Deployed to Coolify.
4. **REST API** — FastAPI app with the endpoints listed in §5. Static bearer-token auth. Deployed to Coolify.
5. **Web frontend** — React app with device list, latest readings, and time-series charts (Recharts). Deployed to Coolify.
6. **Polish** — TimescaleDB continuous aggregates for 1h / 1d buckets, compression policy on `readings` (>7 days), automated DB backups, "device offline" detection (no telemetry in N minutes).
7. **Mobile app** — React Native via Expo, sharing API contracts with the web app.

---

## 10. Open questions / decisions deferred

These will be resolved in the phase noted:

- **Decoding constants for `t` and `l`** — finalized when ingestor lands (Phase 3).
- **Retention policy on `readings`** — Phase 6.
- **Domain / TLS** — using Coolify-provided URLs until a domain is attached.
- **Real auth design** — post-v1; JWT vs OAuth provider TBD.
- **Backup destination** — Phase 6 (likely Hetzner Storage Box).
