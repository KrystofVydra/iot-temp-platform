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
- **Database:** PostgreSQL 16 + TimescaleDB 2.26 extension (hypertable for
  readings, 14× compression on chunks >7d, configured retention: forever)
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Pydantic v2,
  Alembic migrations, bcrypt for password hashing
- **MQTT broker:** Eclipse Mosquitto 2.0, per-device username/password +
  per-device topic ACL (`devices/<device_key>/#`)
- **Ingestor:** Python service using aiomqtt that subscribes to
  `devices/+/telemetry`, validates, and writes to the readings hypertable.
  Ignores retained messages to avoid stale-data re-ingestion on reconnect.
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
users(id, email, display_name, is_admin, is_active, password_hash, last_login_at, created_at)
devices(id, user_id, device_key, name, location, mqtt_provisioned, created_at, last_seen_at)
readings(time, device_id, temperature REAL, lux INT, battery_raw INT, rssi SMALLINT)
-- TimescaleDB hypertable, compressed >7d
sessions(id, user_id, token_hash, created_at, expires_at, last_used_at, user_agent)
auth_tokens(id, user_id, kind, token_hash, created_at, expires_at, used_at)
-- kind in ('invitation', 'password_reset')

## Authentication model

- **Single-tenant per user.** A user owns one or more devices. Sees only
  their own devices in the regular API.
- **Admin role.** `is_admin = true` exposes a parallel `/admin/*` API
  that can see all users and all devices.
- **Onboarding flow.** Admin creates a user → server issues an invitation
  token (7-day TTL) → admin copies the invitation URL → emails to user
  manually (no SMTP integration yet) → user clicks link, sets password,
  is logged in.
- **Password reset.** User-initiated via `/auth/forgot-password` or
  admin-initiated via `/admin/users/{id}/reset-link`. Both produce a
  reset URL with a 1-hour token. Manual email currently.
- **Sessions.** Server-side `sessions` table, 30-day TTL, opaque random
  tokens (sha256 hashed at rest). Currently delivered as `httpOnly Secure`
  cookies to the web app. **Mobile will need a different carrier — bearer
  token in Authorization header** (same backend table, different envelope).
- **No JWT.** Sessions are stateful by design — lets admin deactivate
  users and have it take effect immediately.

## Existing API endpoints

### Auth (public or session-cookie-protected)

- `POST /auth/login` — body `{ email, password }`, returns user info, sets
  session cookie. **For mobile: extend to also return token in body when
  requested (e.g. via header `X-Client: mobile`).**
- `POST /auth/logout` — invalidates current session
- `GET /auth/me` — current user info
- `POST /auth/forgot-password` — body `{ email }`, returns `{ reset_url }`
  (admin-paste mode active; will switch to email delivery later)
- `POST /auth/reset-password` — body `{ token, new_password }`
- `POST /auth/accept-invitation` — body `{ token, password }`, sets password
  and logs user in
- `GET /auth/validate-token?token=...&kind=invitation|reset` — pre-validate
  a token (public, doesn't consume the token)

### Devices (session required, scoped to current user)

- `GET /devices` — list user's devices with latest reading
- `GET /devices/{id}` — single device
- `GET /devices/{id}/readings/latest` — most recent reading
- `GET /devices/{id}/readings?from=...&to=...&bucket=1m|5m|15m|1h|6h|1d&limit=N`
  — historical readings; bucket triggers TimescaleDB time_bucket aggregation

### Admin (session required, admin role required)

- `GET /admin/users` — list users
- `POST /admin/users` — create user, returns `{ user, invitation_url }`
- `GET /admin/users/{id}` — user detail with devices
- `POST /admin/users/{id}/reset-link` — issue password reset URL
- `POST /admin/users/{id}/resend-invitation`
- `POST /admin/users/{id}/deactivate` (invalidates sessions)
- `POST /admin/users/{id}/reactivate`
- `DELETE /admin/users/{id}`
- `GET /admin/devices?q=...&status=online|offline` — search across all
  devices
- `GET /admin/devices/{id}` — device detail
- `POST /admin/devices` — create device, returns `{ device, mqtt_password,
  ssh_command }` (admin then runs the SSH command to register the
  password with Mosquitto, backend never persists the password)
- `PATCH /admin/devices/{id}` — edit name/location/owner/mqtt_provisioned
- `POST /admin/devices/{id}/rotate-mqtt-password`
- `DELETE /admin/devices/{id}`
- `GET /admin/devices/{id}/readings/latest`
- `GET /admin/devices/{id}/readings?...`

## Hardware / device protocol

- **Device:** ESP32-based fridge sensor
- **Telemetry interval:** 1 minute
- **Wire format:** JSON over MQTT, retain flag NOT used (or ignored if used)
- **MQTT topic:** `devices/<device_key>/telemetry`
- **Payload:**
```json
  {"t": <uint16>, "l": <uint16>, "b": <uint16>}
```
  Where:
  - `t` = raw temperature. Conversion: `temp_c = (t - 9999) / 100.0`,
    giving a range of −99.99°C to +99.99°C
  - `l` = lux, raw, stored as-is
  - `b` = battery voltage in millivolts, raw

- **MQTT auth:** each device has a username matching its `device_key` and
  a password registered with Mosquitto via `add_device.sh`. ACL restricts
  each device to publishing/subscribing only on its own topic prefix.

## Provisioning workflow today (for context)

For each new device:
1. Admin clicks "Add device" in admin panel → backend creates row and
   generates a random MQTT password
2. Admin copies the displayed SSH command, runs it on VPS
3. `add_device.sh` registers the password with Mosquitto
4. Admin marks `mqtt_provisioned = true` in the UI
5. Customer receives the password (currently by manual email) and flashes
   it into the ESP32 firmware along with wifi credentials

**The mobile app needs to replace step 5** with a BLE provisioning flow —
the user, with one tap, pairs their phone to the ESP32 over BLE and the
phone pushes wifi + MQTT credentials to the device.

## What the mobile app needs to do

### Required (v1)

- **Login + session management** using bearer tokens (mobile-friendly)
- **Device dashboard** — list of devices with current temperature, online
  status, last seen time
- **Device detail** with time-series chart (same ranges as web: 1h, 6h,
  24h, 7d, 30d)
- **BLE provisioning** — pair with a new ESP32, push wifi SSID + password,
  push MQTT host + username + password + device_key. ESP32 saves, reboots,
  connects.

### Desirable (later, possibly v1 if scope allows)

- **Push notifications** when a fridge alarm triggers (out-of-range
  temperature, device offline). Apple/Google ecosystem complexity.
- **Device renaming** from the app (PATCH to `/admin/devices/{id}` if
  admin; future endpoint for users to rename their own device)
- **Account settings** — change password, update display name

### Out of scope for v1

- Multi-account / account switching
- Offline mode (caching device list when no internet)
- Background MQTT subscription on the phone (not necessary; server
  has the data)

## Open architecture decisions for the new conversation

1. **Mobile auth carrier:** Confirm bearer-token approach. Backend needs
   a small change to `POST /auth/login` to return the token in the body
   when requested.

2. **BLE provisioning protocol design:**
   - GATT service with characteristics for wifi_ssid, wifi_password,
     mqtt_host, mqtt_username, mqtt_password, device_key, status?
   - Or a single JSON-over-BLE blob the app writes once?
   - How does the ESP32 advertise? (Device name format, manufacturer data)
   - How does the app know provisioning succeeded? (Read-back of status)
   - Should the ESP32 firmware be developed in parallel or already
     have a known BLE profile?

3. **Push notifications:** Yes/no for v1. If yes, requires server-side
   FCM/APNS integration.

4. **Tech stack:** React Native + Expo (with native modules for BLE), or
   React Native bare workflow? Expo's managed workflow may or may not
   support the BLE library we need (`react-native-ble-plx`).

## Known constraints & deferred work

- **MQTT over TLS** — currently plain TCP on 1883. Adding TLS (port 8883)
  is in Tier 2 hardening. Not blocking the mobile app, but worth noting.
- **No automated email delivery** — currently using admin manual copy/paste
  of invitation/reset URLs. Resend integration deferred.
- **No restricted ingestor MQTT user** — ingestor connects as `admin` user.
  Tier 2 hardening item.
- **No device offline detection / alerting** — UI shows online/offline pill
  based on `last_seen_at` heuristic. No server-side polling. Tier 2.
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
- `backend/app/routers/devices.py` — user-scoped device + reading endpoints
- `backend/app/routers/admin.py` — admin endpoints
- `backend/app/models.py` — SQLAlchemy models
- `backend/app/auth.py` — session/token logic, dependencies
- `backend/alembic/versions/` — migration history
- `web/src/lib/api.ts` — API client (cookies-based)
- `web/src/lib/hooks.ts` — TanStack Query hooks (reference for mobile equivalents)