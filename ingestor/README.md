# ingestor

MQTT subscriber that consumes ESP32 telemetry from Mosquitto, decodes raw sensor values, and writes them to the `readings` hypertable in PostgreSQL + TimescaleDB. Also updates `devices.last_seen_at` so the API can surface online/offline state. Runs as a long-lived async service; no HTTP surface.

For the full system design, MQTT contract, and roadmap, see [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
