#!/usr/bin/env python3
"""Pull the live Home Assistant config into this repo, with secrets removed.

Creates a small partial backup (Home Assistant config only, no history
database, ~3 MB) named "git-sync (temporary)" through the HA API, downloads
it, and
copies a sanitized subset of /config into the repo:

  configuration.yaml, automations/scripts/scenes, blueprints, themes,
  UI dashboards (from .storage, as YAML), ESPHome and Zigbee2MQTT configs.

Inline ESPHome credentials and the Zigbee2MQTT MQTT password become
!secret references. As a final guard, every value from the backup's
secrets files and every redacted value is searched for in the output, and
the run aborts (exit 2) without touching the repo if any is found.

Usage:  HA_URL=https://<instance>.ui.nabu.casa python3 tools/sync_config.py
Auth:   sends "Authorization: Bearer $HA_TOKEN". In a Claude cloud session the
        proxy injects the real token, so HA_TOKEN can stay unset.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
HA_URL = os.environ["HA_URL"].rstrip("/")
TOKEN = os.environ.get("HA_TOKEN", "proxy-injected")

TOP_FILES = ["configuration.yaml", "automations.yaml", "scripts.yaml", "scenes.yaml", ".HA_VERSION"]
TOP_DIRS = ["blueprints", "themes"]
MANAGED = TOP_FILES + TOP_DIRS + ["dashboards", "esphome", "zigbee2mqtt"]


def curl(*args):
    cmd = ["curl", "-sS", "-f", "-H", f"Authorization: Bearer {TOKEN}", *args]
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def create_backup():
    body = json.dumps({"homeassistant": True, "homeassistant_exclude_database": True,
                       "name": "git-sync (temporary)", "compressed": True})
    out = json.loads(curl("-X", "POST", "-H", "Content-Type: application/json",
                          f"{HA_URL}/api/services/hassio/backup_partial?return_response", "-d", body))
    slug = out["service_response"]["backup"]
    if not re.fullmatch(r"[a-f0-9]{8}", slug):
        raise SystemExit(f"unexpected backup id {slug!r}")
    return slug


def extract_config(slug, work):
    tar_path = work / "backup.tar"
    curl("-o", str(tar_path), f"{HA_URL}/api/hassio/backups/{slug}/download")
    with tarfile.open(tar_path) as outer:
        member = next(m for m in outer.getmembers() if m.name.lstrip("./") == "homeassistant.tar.gz")
        inner = outer.extractfile(member)
        with tarfile.open(fileobj=inner, mode="r:gz") as ha:
            ha.extractall(work / "ha", filter="data")
    return work / "ha" / "data"


def secret_values(src):
    vals = []
    for f in [src / "secrets.yaml", src / "esphome/secrets.yaml", src / "zigbee2mqtt/secret.yaml"]:
        if f.exists():
            data = yaml.safe_load(f.read_text()) or {}
            vals += [str(v) for v in data.values() if v is not None]
    return vals


def sanitize(src, dst, leaked):
    for f in TOP_FILES:
        if (src / f).exists():
            shutil.copy2(src / f, dst / f)
    for d in TOP_DIRS:
        if (src / d).is_dir():
            shutil.copytree(src / d, dst / d)

    # ESPHome: inline credentials -> !secret references
    names = []
    line_re = re.compile(r"^(\s*)(key|password|ssid):\s*(.+?)\s*$")
    for y in sorted((src / "esphome").glob("*.yaml")):
        if y.name == "secrets.yaml":
            continue
        dev = re.sub(r"[^a-z0-9]+", "_", y.stem.lower())
        top, in_ap, out = None, False, []
        for line in y.read_text().splitlines():
            if m := re.match(r"^([a-z_]+):", line):
                top, in_ap = m.group(1), False
            if re.match(r"^\s+ap:\s*$", line):
                in_ap = True
            lm = line_re.match(line)
            if lm and not lm.group(3).startswith("!secret") and lm.group(3) not in ("|", ">"):
                indent, field, val = lm.groups()
                name = {("key", "api"): f"{dev}_api_key", ("password", "ota"): f"{dev}_ota_password"}.get((field, top))
                if top == "wifi":
                    name = f"{dev}_ap_password" if in_ap and field == "password" else (None if in_ap else f"wifi_{field}")
                if name:
                    leaked.append(val.strip("\"'"))
                    names.append(name) if name not in names else None
                    line = f"{indent}{field}: !secret {name}"
            out.append(line)
        (dst / "esphome").mkdir(exist_ok=True)
        (dst / "esphome" / y.name).write_text("\n".join(out) + "\n")
    if (dst / "esphome").exists():
        for n in ("wifi_password", "wifi_ssid"):
            names.insert(0, n) if n not in names else None
        (dst / "esphome/secrets.example.yaml").write_text(
            "# Copy to secrets.yaml (never commit it) and fill in real values.\n"
            + "".join(f'{n}: "CHANGE_ME"\n' for n in names))

    # Zigbee2MQTT: MQTT password -> secret.yaml reference
    z2m = src / "zigbee2mqtt/configuration.yaml"
    if z2m.exists():
        def rep(m):
            if not m.group(2).strip("'\"").startswith("!secret"):
                leaked.append(m.group(2).strip("\"'"))
            return f"{m.group(1)}'!secret password'"
        (dst / "zigbee2mqtt").mkdir(exist_ok=True)
        (dst / "zigbee2mqtt/configuration.yaml").write_text(
            re.sub(r"^(\s*password:\s*)(.+)$", rep, z2m.read_text(), flags=re.M))

    # UI dashboards
    (dst / "dashboards").mkdir()
    for p in sorted((src / ".storage").glob("lovelace.*")):
        cfg = json.loads(p.read_text())["data"].get("config")
        if cfg:
            name = p.name.split(".", 1)[1]
            (dst / "dashboards" / f"{name}.yaml").write_text(
                f"# UI dashboard '{name}' exported from .storage/{p.name}\n"
                "# (read-only reference; paste into the dashboard's Raw configuration editor to restore)\n"
                + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120))
    for p in ["lovelace_dashboards", "lovelace_resources"]:
        if (src / ".storage" / p).exists():
            data = json.loads((src / ".storage" / p).read_text())["data"]
            (dst / "dashboards" / f"_{p}.yaml").write_text(yaml.safe_dump(data, sort_keys=False, width=120))


def leak_check(dst, values):
    values = {v for v in values if len(v) >= 6}
    hits = []
    for f in dst.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            hits += [str(f.relative_to(dst)) for v in values if v in text]
    return sorted(set(hits))


def main():
    work = Path(tempfile.mkdtemp(prefix="ha-sync-"))
    slug = create_backup()
    src = extract_config(slug, work)
    # The HA API proxy does not allow deleting backups, so the ~3 MB
    # "git-sync (temporary)" backup stays in HA; delete old ones in the UI.
    stage = work / "stage"
    stage.mkdir()
    leaked = []
    sanitize(src, stage, leaked)
    hits = leak_check(stage, leaked + secret_values(src))
    if hits:
        print("ABORT: secret values found in:", ", ".join(hits), file=sys.stderr)
        sys.exit(2)
    for name in MANAGED:
        target = REPO / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if (stage / name).exists():
            shutil.move(str(stage / name), str(target))
    shutil.rmtree(work)
    print(f"synced from backup {slug}; HA version "
          f"{(REPO / '.HA_VERSION').read_text().strip()}")


if __name__ == "__main__":
    main()
