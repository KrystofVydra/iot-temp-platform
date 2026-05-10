# Mosquitto setup

This directory holds the Mosquitto broker configuration for both local development and production. The broker image is `eclipse-mosquitto:2`.

## Files

| File             | In git? | Purpose                                            |
| ---------------- | ------- | -------------------------------------------------- |
| `mosquitto.conf` | yes     | Broker configuration (listeners, auth, persistence). |
| `passwords`      | **no**  | Hashed credentials. Generated locally / per env.   |
| `acl`            | **no**  | Per-user topic permissions. Per env.               |

`passwords` and `acl` contain secrets and per-deployment data, so they are git-ignored. You must generate them before the broker will accept connections.

## Generating `passwords`

The `mosquitto_passwd` utility ships in the official broker image. Run it inside a one-off container so you don't need it installed on the host.

### Create the file with the first user (the ingestor service account)

```bash
docker run --rm -it \
  -v "$(pwd)/infra/mosquitto:/mosquitto/config" \
  eclipse-mosquitto:2 \
  mosquitto_passwd -c /mosquitto/config/passwords ingestor
```

You will be prompted for the password twice. Use the same value as `MQTT_PASSWORD` in your `.env` file.

### Add a device user

```bash
docker run --rm -it \
  -v "$(pwd)/infra/mosquitto:/mosquitto/config" \
  eclipse-mosquitto:2 \
  mosquitto_passwd /mosquitto/config/passwords sensor-kitchen-01
```

Convention: the device username is the same as its `device_key` in the `devices` table. That makes ACL rules easy to write (one pattern per device).

## Writing the `acl` file

Create `infra/mosquitto/acl` (no extension) with the following structure:

```
# Service account used by the ingestor — can subscribe to all telemetry.
user ingestor
topic read devices/+/telemetry
topic read devices/+/status

# One block per device. The username must match the device_key.
user sensor-kitchen-01
topic write devices/sensor-kitchen-01/telemetry
topic write devices/sensor-kitchen-01/status
topic read  devices/sensor-kitchen-01/cmd
```

Each new device gets its own three-line block. Keep this file in a password manager / secrets backend per environment; do **not** commit it.

## Reloading after edits

Mosquitto re-reads the password file when it receives `SIGHUP`:

```bash
docker compose kill -s HUP mosquitto
```

The ACL file is reloaded the same way.

## Production note

In Coolify, mount these files into the broker container's `/mosquitto/config` via a persistent volume (or use Coolify's secret mounts) instead of bind-mounting from the repo. Treat the production `passwords` and `acl` as you would any other secret.
