#!/usr/bin/env bash
# Database backup: pg_dump → gzip → SCP to Hetzner Storage Box → prune old.
#
# Runs on the VPS host (not inside a deployed container). pg_dump is invoked
# via a one-shot timescale/timescaledb container so the dumper version
# matches the server exactly. The Storage Box is reached purely over SFTP /
# SCP because its shell is restricted (no `find`, etc.).
#
# Intended cron entry (as root):
#   PGPASSWORD=...
#   0 3 * * *  /root/backup-db.sh >> /var/log/iot-backup.log 2>&1

set -euo pipefail

# Cron runs with a minimal PATH; ensure the tools we call are findable.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# --- Configuration --------------------------------------------------------

: "${PGPASSWORD:?PGPASSWORD must be set}"

PG_HOST="${PG_HOST:-hhlzxqk2sbqqxklzcvqdfrl6}"
PG_USER="${PG_USER:-iot}"
PG_DB="${PG_DB:-iot}"
PG_IMAGE="${PG_IMAGE:-timescale/timescaledb:latest-pg16}"
COOLIFY_NETWORK="${COOLIFY_NETWORK:-coolify}"

SB_HOST="${SB_HOST:-u600286.your-storagebox.de}"
SB_USER="${SB_USER:-u600286}"
SB_PORT="${SB_PORT:-23}"
SB_KEY="${SB_KEY:-/root/.ssh/storagebox_key}"
SB_REMOTE_DIR="${SB_REMOTE_DIR:-backups}"

RETENTION_DAYS="${RETENTION_DAYS:-30}"
LOCAL_TMP="${LOCAL_TMP:-/tmp}"
MIN_DUMP_BYTES="${MIN_DUMP_BYTES:-1024}"

TIMESTAMP="$(date -u +%Y-%m-%d-%H%M%S)"
FILENAME="iot-${TIMESTAMP}.sql.gz"
LOCAL_PATH="${LOCAL_TMP}/${FILENAME}"

# --- Helpers --------------------------------------------------------------

log()  { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die()  { log "FAILURE: $*"; exit 1; }

# Clean up the local dump on any exit path (success or failure).
trap 'rm -f "${LOCAL_PATH:-}"' EXIT

ssh_opts=(
    -o StrictHostKeyChecking=accept-new
    -o BatchMode=yes
    -o ConnectTimeout=15
)

run_sftp() {
    # Read sftp batch from stdin. Suppresses sftp's "Connected to ..." banner
    # but lets errors surface.
    sftp -q -P "${SB_PORT}" -i "${SB_KEY}" "${ssh_opts[@]}" -b - \
        "${SB_USER}@${SB_HOST}"
}

# --- 1. Dump and gzip -----------------------------------------------------

log "starting backup: ${FILENAME}"
log "db: ${PG_USER}@${PG_HOST}/${PG_DB} (image ${PG_IMAGE}, network ${COOLIFY_NETWORK})"
log "dest: ${SB_USER}@${SB_HOST}:${SB_PORT}/${SB_REMOTE_DIR}"
log "retention: ${RETENTION_DAYS} days"

log "running pg_dump via one-shot container…"
if ! docker run --rm --network "${COOLIFY_NETWORK}" \
        -e PGPASSWORD="${PGPASSWORD}" \
        "${PG_IMAGE}" \
        pg_dump -h "${PG_HOST}" -U "${PG_USER}" -d "${PG_DB}" \
            --no-owner --no-privileges \
      | gzip > "${LOCAL_PATH}"; then
    die "pg_dump | gzip pipeline failed (pipefail caught a non-zero exit)"
fi

# Portable stat: -c on GNU, -f on BSD.
dump_size="$(stat -c%s "${LOCAL_PATH}" 2>/dev/null || stat -f%z "${LOCAL_PATH}")"
if (( dump_size < MIN_DUMP_BYTES )); then
    die "dump file is empty or suspiciously small (${dump_size} bytes < ${MIN_DUMP_BYTES})"
fi
log "dump ok: ${LOCAL_PATH} (${dump_size} bytes)"

# --- 2. Ensure remote dir, upload -----------------------------------------

log "ensuring remote dir ${SB_REMOTE_DIR}/ exists"
# The leading '-' on '-mkdir' tells sftp's batch mode to keep going on error
# (i.e. when the directory already exists).
run_sftp >/dev/null <<EOF
-mkdir ${SB_REMOTE_DIR}
EOF

log "uploading ${FILENAME} via scp…"
if ! scp -P "${SB_PORT}" -i "${SB_KEY}" "${ssh_opts[@]}" \
        "${LOCAL_PATH}" \
        "${SB_USER}@${SB_HOST}:${SB_REMOTE_DIR}/${FILENAME}"; then
    die "scp upload failed"
fi
log "upload complete"

# Remove the local copy immediately — the trap is a safety net but explicit
# is nicer in the log.
rm -f "${LOCAL_PATH}"
log "local temp file removed"

# --- 3. Prune remote backups older than RETENTION_DAYS --------------------
#
# Storage Box has no `find`; we list filenames over SFTP and parse the date
# out of them ourselves. The script only ever touches files matching
# `iot-YYYY-MM-DD-HHMMSS.sql.gz` so it can't delete unrelated content.

log "pruning remote backups older than ${RETENTION_DAYS} days"

listing="$(
    run_sftp 2>/dev/null <<EOF || true
cd ${SB_REMOTE_DIR}
ls -1 iot-*.sql.gz
EOF
)"

now_epoch="$(date -u +%s)"
delete_cmds=""
considered=0
to_delete=0

while IFS= read -r fname; do
    [[ "${fname}" =~ ^iot-([0-9]{4})-([0-9]{2})-([0-9]{2})-[0-9]{6}\.sql\.gz$ ]] || continue
    considered=$((considered + 1))
    file_date="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
    if ! file_epoch="$(date -u -d "${file_date}" +%s 2>/dev/null)"; then
        log "  skip ${fname}: unparseable date"
        continue
    fi
    age_days=$(( (now_epoch - file_epoch) / 86400 ))
    if (( age_days > RETENTION_DAYS )); then
        log "  delete: ${fname} (age ${age_days}d)"
        delete_cmds+="rm ${fname}"$'\n'
        to_delete=$((to_delete + 1))
    fi
done <<< "${listing}"

if (( to_delete > 0 )); then
    if ! run_sftp >/dev/null <<EOF
cd ${SB_REMOTE_DIR}
${delete_cmds}
EOF
    then
        log "WARNING: prune sftp batch returned non-zero (some old backups may remain)"
    fi
fi

log "prune: considered ${considered}, deleted ${to_delete}"

# --- Done -----------------------------------------------------------------

log "SUCCESS: ${SB_REMOTE_DIR}/${FILENAME} uploaded; pruned ${to_delete} old file(s)"
