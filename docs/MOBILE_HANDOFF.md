# IoT Temperature Platform — Mobile App Handoff

## Overview

A self-hosted IoT temperature monitoring platform for fridge sensors. The
backend, database, MQTT broker, web frontend, and admin panel are all
complete and deployed. This document hands off context for building the
React Native + Expo mobile companion app.

The product is targeted at non-technical end users (a customer support model
where the admin manually provisions accounts and devices). The mobile app
will replace some web-app usage and add BLE-based device provisioning,
which the web cannot do.

## Live URLs

- Web app: `https://app.otti.cz`
- Backend API: `https://api.otti.cz`
- API docs (Swagger UI): `https://api.otti.cz/docs`
- MQTT broker: `mqtt.otti.cz:1883` (plain TCP, no TLS yet)
- GitHub repo: `https://github.com/KrystofVydra/iot-temp-platform`

## Stack

- **VPS:** Hetzner Cloud CPX21 (4 GB RAM, 80 GB SSD, 2 vCPU) in nbg1
- **PaaS:** Coolify (self-hosted) managing all containers
- **Database:** PostgreSQL 16 + TimescaleDB 2.26 extension (two hypertables:
  `node_readings` and `controller_telemetry`, both with 7-day compression
  policy, retention: forever)
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Pydantic v2,
  Alembic migrations, bcrypt for password hashing
- **MQTT broker:** Eclipse Mosquitto 2.0, per-gateway username/password +
  per-gateway topic ACL (`devices/<gateway_key>/#`)
- **Ingestor:** Python service using aiomqtt that subscribes to
  `devices/+/telemetry`, validates, dispatches to node_readings +
  controller_telemetry, and auto-queues unknown controllers/nodes for admin
  acceptance. Ignores retained messages to avoid stale-data re-ingestion on
  reconnect.
- **Web:** React 18 + Vite + TypeScript + TanStack Query + Recharts +
  Tailwind. Static build served by nginx.
- **DNS:** Forpsi (registrar), three A records:
  - `app.otti.cz` → VPS
  - `api.otti.cz` → VPS
  - `mqtt.otti.cz` → VPS
- **HTTPS:** Coolify's built-in Traefik handles Let's Encrypt for app/api.
- **Backups:**
  - Hetzner whole-VPS daily snapshots
  - Daily `pg_dump` cron to Hetzner Storage Box (offsite, 30-day retention),
    restore procedure tested and documented

## Data model

```
users(id, email, display_name, is_admin, is_active,
      password_hash, last_login_at, created_at)
gateways(id, user_id, device_key, name, location,
         mqtt_provisioned, created_at, last_seen_at)
   -- ESP32 (the MQTT auth point). Relays for one or more controllers.
controllers(id, gateway_id, sn, name, location,
            created_at, last_seen_at)
   -- Battery-powered measurement unit (e.g. one per fridge).
nodes(id, controller_id, node_index, name, has_lux,
      created_at, last_seen_at)
   -- Individual sensor inside a controller. 1-5 per controller.
pending_controllers(id, gateway_id, sn, first_seen_at,
                    last_seen_at, message_count)
   -- Auto-populated by ingestor; admin accepts or rejects.
node_readings(time, node_id, temperature, lux, err)
   -- TimescaleDB hypertable, compressed >7d
controller_telemetry(time, controller_id, battery_v, door_open)
   -- TimescaleDB hypertable, compressed >7d
sessions(id, user_id, token_hash, created_at, expires_at,
         last_used_at, user_agent)
auth_tokens(id, user_id, kind, token_hash,
            created_at, expires_at, used_at)
   -- kind in ('invitation', 'password_reset')
```

## Authentication model

- **Single-tenant per user.** A user owns one or more gateways and the
  controllers/nodes under them. Sees only their own controllers in the
  regular API.
- **Admin role.** `is_admin = true` exposes a parallel `/admin/*` API
  that can see all users, gateways, controllers, and nodes.
- **Onboarding flow.** Admin creates a user → server issues an invitation
  token (7-day TTL) → admin copies the invitation URL → emails to user
  manually (no SMTP integration yet) → user clicks link, sets password,
  is logged in.
- **Password reset.** User-initiated via `/auth/forgot-password` or
  admin-initiated via `/admin/users/{id}/reset-link`. Both produce a
  reset URL with a 1-hour token. Manual email currently.
- **Sessions.** Server-side `sessions` table, 30-day TTL, opaque random
  tokens (sha256 hashed at rest). Web app uses `httpOnly Secure` cookies;
  mobile uses bearer tokens in the `Authorization` header. Same backend
  table, different envelope.
- **No JWT.** Sessions are stateful by design — lets admin deactivate
  users and have it take effect immediately.

## Existing API endpoints

### Auth (public or session-protected)

- `POST /auth/login` — body `{ email, password }`, returns user info, sets
  session cookie. For mobile clients, set `X-Client: mobile` to also
  receive the bearer token in the response body.
- `POST /auth/logout` — invalidates current session
- `GET /auth/me` — current user info
- `POST /auth/forgot-password` — body `{ email }`, returns `{ reset_url }`
  (admin-paste mode active; will switch to email delivery later)
- `POST /auth/reset-password` — body `{ token, new_password }`
- `POST /auth/accept-invitation` — body `{ token, password }`, sets password
  and logs user in
- `GET /auth/validate-token?token=...&kind=invitation|reset` — pre-validate
  a token (public, doesn't consume the token)

### Controllers (session required, scoped to current user)

- `GET /controllers` — list controllers (via the user's gateways) with
  averaged latest reading
- `GET /controllers/{id}` — controller detail with all its nodes and the
  latest telemetry
- `GET /controllers/{id}/readings?from=...&to=...&bucket=...` — averaged
  temperature time-series across all nodes of the controller
- `GET /controllers/{id}/telemetry?from=...&to=...&bucket=...` — battery
  voltage and door state over time

### Admin (session required, admin role required)

- `GET /admin/users` — list users (unchanged)
- `POST /admin/users` — create user, returns `{ user, invitation_url }` (unchanged)
- `GET /admin/users/{id}`, `POST /admin/users/{id}/reset-link`,
  `POST /admin/users/{id}/resend-invitation`, `POST /admin/users/{id}/deactivate`,
  `POST /admin/users/{id}/reactivate`, `DELETE /admin/users/{id}` (unchanged)

- `GET /admin/gateways?q=&status=` — list all gateways across users
- `GET /admin/gateways/{id}` — gateway detail including pending_controllers
- `POST /admin/gateways` — create gateway, returns `{ gateway, mqtt_password, ssh_command }`
- `PATCH /admin/gateways/{id}` — edit name/location/owner/mqtt_provisioned
- `POST /admin/gateways/{id}/rotate-mqtt-password`
- `DELETE /admin/gateways/{id}`

- `POST /admin/pending-controllers/{id}/accept` (body: `{ name, location }`)
- `POST /admin/pending-controllers/{id}/reject`

- `GET /admin/controllers/{id}`, `PATCH /admin/controllers/{id}`,
  `DELETE /admin/controllers/{id}`
- `PATCH /admin/nodes/{id}` (set `name` and `has_lux`),
  `DELETE /admin/nodes/{id}`
- `GET /admin/controllers/{id}/readings`, `/admin/controllers/{id}/telemetry`
  (admin view of any controller's data, same shape as user endpoints)

## Hardware / device protocol

- **Device:** ESP32-based gateway that relays for battery-powered controllers
- **Controllers** wake up every minute, send a reading per node to the gateway,
  gateway forwards to MQTT
- **Wire format:** JSON over MQTT, retain flag ignored by ingestor
- **MQTT topic:** `devices/<gateway_key>/telemetry`
- **Payload (one node per message):**

```json
{
  "source": 0,
  "sn": "4876",
  "b": 200,
  "d": 0,
  "node": {
    "id": 1,
    "t": 5.42,
    "l": 4
  }
}
```

  - `source` — uint8, future cellular/wifi switch
  - `sn` — controller serial number (last 4 chars)
  - `b` — uint8 0..255, battery mapped to 1.4V..3.6V
  - `d` — uint8, door open boolean
  - `node.id` — node_index 1..5
  - `node.t` — float -99.99..99.99 °C, OMITTED on err
  - `node.l` — uint16 0..1310 lux, OMITTED on err or has_lux=false
  - `node.err` — optional, one of `sensor_lux` | `sensor_temp` | `sensor_both` | `comms`

- **Battery conversion:** `volts = 1.4 + (b / 255.0) * 2.2`
- **MQTT auth:** each gateway has a username (= device_key) with password
  registered in Mosquitto; ACL restricts each gateway to publish only on
  `devices/<gateway_key>/#`.

## Provisioning workflow today (for context)

For each new gateway:

1. Admin clicks "Add Gateway" in admin panel → backend creates gateway row
   and generates a random MQTT password
2. Admin copies the displayed SSH command, runs it on VPS
3. `add_device.sh` registers the password with Mosquitto
4. Admin marks `mqtt_provisioned = true`
5. Customer flashes the firmware with wifi credentials + the MQTT
   credentials + the `gateway_key`. Gateway connects to broker.

For new controllers (battery-powered, communicating with the gateway over
radio):

6. Controller starts publishing through the gateway
7. Ingestor sees unknown `sn` for this gateway → queues in
   `pending_controllers`
8. Admin reviews via `/admin/gateways/{id}`, clicks "Accept" → controller
   is created with admin-chosen name
9. Nodes inside the controller are auto-discovered as they appear in
   messages (`has_lux` set from first message)

**The mobile app needs to replace step 5** with a BLE provisioning flow —
the user, with one tap, pairs their phone to the ESP32 over BLE and the
phone pushes wifi + MQTT credentials to the device.

## What the mobile app needs to do

### Required (v1)

- **Login + session management** using bearer tokens
- **Controller dashboard** — list of controllers (not devices) with averaged
  latest temperature, online status, last seen time
- **Controller detail** with node tiles + averaged time-series chart (same
  ranges as web: 1h, 6h, 24h, 7d, 30d)
- **BLE provisioning** — pair with a new ESP32, push wifi SSID + password,
  push MQTT host + username + password + `gateway_key`. ESP32 saves, reboots,
  connects.

### Desirable (later, possibly v1 if scope allows)

- **Push notifications** when a fridge alarm triggers (out-of-range
  temperature, controller offline, low battery). Apple/Google ecosystem
  complexity.
- **Controller/node renaming** from the app (PATCH endpoints already exist
  for admins; future user-scoped equivalents for the controller they own)
- **Account settings** — change password, update display name

### Out of scope for v1

- Multi-account / account switching
- Offline mode (caching controller list when no internet)
- Background MQTT subscription on the phone (not necessary; server
  has the data)

## Phase 3 (June 2026) — Topology rework

The data model expanded from "device = sensor" to a three-level hierarchy:

- **Gateway:** the ESP32 with MQTT identity (one per customer site, typically)
- **Controller:** battery-powered measurement unit (e.g. one per fridge)
- **Node:** individual temperature sensor inside a controller (1-5 per controller)

Reasons: customers want multiple fridges per location and multiple
measurement points per fridge for accuracy. The wire protocol changed
accordingly; see "Hardware / device protocol" above. Auto-discovery for
nodes; explicit admin acceptance for new controllers via the
`pending_controllers` queue.

Implications for the mobile app:

- All `/devices/*` calls now break — replace with `/controllers/*`
- The home screen shifts from "device tiles" to "controller tiles"
- Device detail screen becomes controller detail with node tiles + chart

## Open architecture decisions for the new conversation

1. **Push notifications:** Yes/no for v1. If yes, requires server-side
   FCM/APNS integration plus a per-user alert-rule model on the backend
   (currently absent — Round 4 territory).

2. **Tech stack:** React Native + Expo (with native modules for BLE), or
   React Native bare workflow? Expo's managed workflow may or may not
   support the BLE library we need (`react-native-ble-plx`).

3. **BLE provisioning protocol design** — still being worked out in the
   mobile thread (not in scope for this doc anymore, but kept on the radar).

## Known constraints & deferred work

- **MQTT over TLS** — currently plain TCP on 1883. Adding TLS (port 8883)
  is in Tier 2 hardening. Not blocking the mobile app, but worth noting.
- **No automated email delivery** — currently using admin manual copy/paste
  of invitation/reset URLs. Resend integration deferred.
- **No restricted ingestor MQTT user** — ingestor connects as `admin` user.
  Tier 2 hardening item.
- **No controller offline detection / alerting** — UI shows online/offline
  pill based on `last_seen_at` heuristic. No server-side polling. Tier 2.
- **Single admin model** — `is_admin` boolean, no role hierarchy. Fine for
  current use.

## Operational notes

- **Coolify deploys** auto-trigger on push to `main`. All containers
  redeploy (backend, ingestor, web, mosquitto) regardless of which paths
  changed. Watch-paths config not enabled.
- **Backend env vars** in Coolify (most critical):
  - `DATABASE_URL=postgresql+asyncpg://iot:<password>@<postgres-uuid>:5432/iot`
  - `FRONTEND_ORIGIN=https://app.otti.cz`
  - `EXPOSE_AUTH_LINKS=true` (toggles admin-paste mode for invitation/reset URLs)
  - `CORS_ORIGINS=https://app.otti.cz,http://localhost:5173`
  - `BCRYPT_ROUNDS=12`
  - `MOSQUITTO_RESOURCE_NAME=iot-mosquitto`
- **DB connection** for ad-hoc scripts:
  `docker exec <postgres-container-uuid> psql -U iot -d iot`
- **Postgres container UUID** (current): `hhlzxqk2sbqqxklzcvqdfrl6`
  — this changes if you redeploy the Postgres resource in Coolify.

## Files of interest

- `backend/app/routers/auth.py` — login, sessions, password flow
- `backend/app/routers/controllers.py` — user-scoped controller + readings + telemetry
- `backend/app/routers/admin.py` — admin endpoints (users, gateways,
  controllers, nodes, pending controllers)
- `backend/app/models.py` — SQLAlchemy models for the new hierarchy
- `backend/app/auth.py` — session/token logic, dependencies
- `backend/alembic/versions/` — migration history
  (see `…_topology_rework.py` for the device → gateway/controller/node split)
- `web/src/lib/api.ts` — API client (cookies-based)
- `web/src/lib/hooks.ts` — TanStack Query hooks (reference for mobile equivalents)
- `scripts/backfill.py` — demo-data backfill for the new schema
