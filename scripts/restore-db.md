# Restoring from a backup

`backup-db.sh` produces `iot-YYYY-MM-DD-HHMMSS.sql.gz` files on the Hetzner Storage Box. This document covers restoring one of them into a PostgreSQL + TimescaleDB instance — typically a fresh Coolify-managed Postgres, but any Postgres 16 + TimescaleDB pairing works.

## 1. Download the backup

From a workstation with the Storage Box SSH key:

```bash
scp -P 23 -i ~/.ssh/storagebox_key \
  u600286@u600286.your-storagebox.de:backups/iot-2026-05-10-030000.sql.gz \
  ./iot-restore.sql.gz

gunzip iot-restore.sql.gz
# → iot-restore.sql
```

## 2. Prepare the target database

The target instance must have the TimescaleDB extension installed. Coolify's managed Postgres provisioned with the `timescale/timescaledb:latest-pg16` image satisfies this; for any other host, install the extension package per [TimescaleDB's install docs](https://docs.timescale.com/self-hosted/latest/install/).

Create a fresh database and enable the extension:

```bash
psql -h <host> -U <admin> -d postgres -c 'CREATE DATABASE iot_restore;'
psql -h <host> -U <admin> -d iot_restore -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
```

## 3. Restore

`backup-db.sh` uses `pg_dump --no-owner --no-privileges`, so the dump can be replayed into any role without permission errors.

### Simple path (works in most cases)

```bash
psql -h <host> -U <admin> -d iot_restore < iot-restore.sql
```

### TimescaleDB safe path (use if the simple path errors out)

If you see errors about background workers, chunk catalog, or hypertable metadata during the restore, use the official two-step procedure. `timescaledb_pre_restore()` pauses background jobs and relaxes constraints; `timescaledb_post_restore()` re-enables them.

```bash
# 1. Prepare
psql -h <host> -U <admin> -d iot_restore -c 'SELECT timescaledb_pre_restore();'

# 2. Apply the dump
psql -h <host> -U <admin> -d iot_restore < iot-restore.sql

# 3. Finalize
psql -h <host> -U <admin> -d iot_restore -c 'SELECT timescaledb_post_restore();'
```

Both `pre_restore` / `post_restore` must run **inside the database being restored** (not in `postgres`).

## 4. Verify

```sql
-- Table row counts
SELECT 'users'    AS table, COUNT(*) FROM users
UNION ALL SELECT 'devices',  COUNT(*) FROM devices
UNION ALL SELECT 'readings', COUNT(*) FROM readings;

-- Latest reading per device
SELECT device_id, MAX(time) FROM readings GROUP BY device_id ORDER BY device_id;

-- Hypertable + chunk status
SELECT * FROM timescaledb_information.hypertables;
SELECT chunk_name, is_compressed, range_start
FROM   timescaledb_information.chunks
WHERE  hypertable_name = 'readings'
ORDER  BY range_start
LIMIT  10;
```

Row counts should match the source. The compression policy (if it was applied in the source) is part of the schema and comes across with the dump — `add_compression_policy` is replayed during restore.

## 5. Swap into place

Once the restore is verified, point the backend + ingestor at it.

### Option A — rename databases

```bash
# In Coolify or psql:
psql -h <host> -U <admin> -d postgres -c 'ALTER DATABASE iot         RENAME TO iot_broken;'
psql -h <host> -U <admin> -d postgres -c 'ALTER DATABASE iot_restore RENAME TO iot;'
```

Restart the `backend` and `ingestor` services in Coolify so they reconnect.

### Option B — point the apps at `iot_restore` directly

Update `DATABASE_URL` for the backend and ingestor in Coolify to use `…/iot_restore`. Slightly less invasive but harder to "undo" — option A is recommended.

## 6. Don't forget

- **Test the restore before you need it.** A backup that has never been restored is a hope, not a backup.
- **Snapshot before swap-in.** Take a fresh dump of the live `iot` DB right before renaming, in case the restore turns out to be older than expected.
- **The Storage Box keeps `RETENTION_DAYS` (default 30) of backups.** If you need older history, save older dumps elsewhere before they age out.
