#!/bin/sh
# Provision a new device user in Mosquitto.
#
# Generates a random 24-character password, adds the user to the password
# file, appends an ACL block restricting the user to its own topic prefix
# (devices/<device_key>/#), and reloads Mosquitto via SIGHUP. Idempotent:
# aborts if the device_key already exists.
#
# Usage:
#   docker exec -it mosquitto sh /mosquitto/config/scripts/add_device.sh esp32-kitchen-01

set -eu

PASSWORD_FILE="/mosquitto/data/passwords"
ACL_FILE="/mosquitto/data/acl"

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    echo "Usage: $0 <device_key>" >&2
    exit 1
fi

DEVICE_KEY="$1"

if [ ! -f "$PASSWORD_FILE" ]; then
    echo "Error: $PASSWORD_FILE does not exist. Run init_admin.sh first." >&2
    exit 1
fi

if grep -q "^${DEVICE_KEY}:" "$PASSWORD_FILE"; then
    echo "Error: device '${DEVICE_KEY}' already exists in $PASSWORD_FILE." >&2
    echo "Aborting to avoid duplicates. Remove the existing entry manually if rotating." >&2
    exit 1
fi

# 24 alphanumeric characters from /dev/urandom. tr + head are in BusyBox.
PASSWORD="$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24)"

mosquitto_passwd -b "$PASSWORD_FILE" "$DEVICE_KEY" "$PASSWORD"
chown root:root "$PASSWORD_FILE" && chmod 0700 "$PASSWORD_FILE"

# Append a per-device ACL block confining this user to its own topic tree.
{
    echo ""
    echo "# Device ${DEVICE_KEY}"
    echo "user ${DEVICE_KEY}"
    echo "topic readwrite devices/${DEVICE_KEY}/#"
} >> "$ACL_FILE"
chown root:root "$ACL_FILE" && chmod 0700 "$ACL_FILE"

# SIGHUP makes Mosquitto re-read passwords + ACL without dropping connections.
# In the official image Mosquitto runs as PID 1.
kill -HUP 1

cat <<EOF

Device provisioned.

  device_key: ${DEVICE_KEY}
  password:   ${PASSWORD}

Test publish from another shell:
  mosquitto_pub -h <broker-host> -p 1883 \\
      -u "${DEVICE_KEY}" -P "${PASSWORD}" \\
      -t "devices/${DEVICE_KEY}/telemetry" \\
      -m '{"t":12345,"l":678,"b":9012}'

Save the password somewhere safe — it cannot be recovered.
EOF
