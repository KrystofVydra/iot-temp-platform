# scripts/

One-off operational scripts. **Not** deployed as part of any service — run manually as one-shot containers.

## backfill.py — demo data generator

Populates the production database with ~6 months of realistic fake sensor readings for visualising the dashboard before real devices exist.

### What it creates

- A demo `users` row: `email = 'demo@example.com'` (upserted on conflict).
- A demo `devices` row: `device_key = 'demo-backfill'`, `name = 'Demo Sensor'`, `location = 'Demo Lab'` (upserted on conflict, owned by the demo user).
- ~259,200 `readings` rows for that device — one per minute over the past 6 months — with:
  - **temperature**: fridge sawtooth around 5°C (compressor cycle 30–60 min, sweeping 3.5°C → 6.5°C), plus 3–8 door-opening spikes per day during 07:00–23:00 UTC, plus N(0, 0.2) noise. Clamped to [2°C, 10°C].
  - **lux**: peaked sin² curve during 06:00–20:00 UTC (max ~800 at noon), zero at night, small noise.
  - **battery_raw**: linear drain from ~4100 mV to ~3600 mV with ±1 mV noise and rare upward bumps. Stored as millivolts.
  - **rssi**: `NULL` (our hardware doesn't report it).

### Running on the VPS

```bash
# Build (do this once on the VPS, or push the image to a registry):
docker build -t backfill scripts/

# Run against the Coolify-managed Postgres.
# Replace <password> and the container host with your Coolify resource details.
docker run --rm --network coolify \
  -e DATABASE_URL="postgresql+asyncpg://iot:<password>@hhlzxqk2sbqqxklzcvqdfrl6:5432/iot" \
  backfill
```

Notes:

- `--network coolify` is required because Coolify isolates the managed Postgres on the `coolify` network. The container needs to be on that network to resolve the Postgres host.
- The script accepts `DATABASE_URL` in SQLAlchemy form (`postgresql+asyncpg://…`) for consistency with the rest of the platform; it strips the `+asyncpg` dialect suffix internally before handing the URL to `asyncpg.connect()`.
- The script is **idempotent within its time window**: it deletes any existing readings for the demo device in `[start, end)` before inserting, so re-running replaces rather than duplicates. Other devices are untouched.

### Expected runtime

Generation is pure Python over ~260k iterations — runs in a few seconds. The bulk insert via `copy_records_to_table` in 50k-row batches takes another few seconds on local network. End-to-end ~30 seconds against a Hetzner VPS Postgres.

### Cleanup

To remove all backfilled data later:

```sql
DELETE FROM readings WHERE device_id = (SELECT id FROM devices WHERE device_key = 'demo-backfill');
DELETE FROM devices  WHERE device_key = 'demo-backfill';
DELETE FROM users    WHERE email = 'demo@example.com';
```

(Foreign keys cascade, so deleting the user would cascade-delete the device and its readings — but the per-table form above is more explicit.)
