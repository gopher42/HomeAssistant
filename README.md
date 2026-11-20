# Home Assistant configuration

A sanitized snapshot of the `/config` directory, taken from the full backup
**Full Backup 2026-11-18 21:06:54** (slug `e6083c7c`, Home Assistant 2026.11.1).

> This repository is **public**. Credentials are never stored here: every
> password and key is a `!secret` reference, and the real values live only in
> `secrets.yaml` on the Home Assistant host. The full backups (`.tar`) stay in
> Home Assistant and Google Drive and are not committed.

## Layout

| Path | Contents |
|---|---|
| `configuration.yaml` | Core config: template sensor and garage door cover, MQTT sensors (Blue Iris motion, plates) |
| `automations.yaml`, `scenes.yaml`, `scripts.yaml` | UI-managed automations (47), scenes, scripts |
| `blueprints/` | Automation, script and template blueprints |
| `themes/` | Mushroom themes |
| `dashboards/` | UI dashboards exported from `.storage/lovelace.*` as YAML (reference copies) |
| `esphome/` | ESPHome device configs; secrets listed in `esphome/secrets.example.yaml` |
| `zigbee2mqtt/configuration.yaml` | Zigbee2MQTT config (ConBee II); MQTT password lives in Z2M's `secret.yaml` |

## Deliberately excluded

`secrets.yaml`, `.storage/` (auth tokens, integration credentials, entity and device registries),
`home-assistant_v2.db` (history), Lutron Caseta certificates and keys (`*.pem`), the Zigbee coordinator
backup (contains the network key), logs, `custom_components/` and `www/community/` (reinstall through HACS).

## Restoring the ESPHome configs

The ESPHome files reference these secrets. Add any that are missing to `esphome/secrets.yaml`
on the host, taking the values from the device's current config, before you compile:
see `esphome/secrets.example.yaml`.

## Not in this repo, for reference

Custom integrations (HACS): `sonoff`, `meross_lan`, `meross_cloud`, `reolink_dev`, `blueiris`, `falcon_pi_player`.
Frontend (HACS): `mushroom`, `mini-graph-card`.
Add-ons: Samba share, Zigbee2MQTT, Mosquitto broker, Terminal & SSH, File editor, Google Drive Backup,
ESPHome Device Builder, AirSonos, AirCast, Matter Server.
