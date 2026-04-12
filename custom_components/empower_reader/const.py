from __future__ import annotations

from datetime import timedelta
import re

DOMAIN = "empower_reader"
SERVICE_REFRESH = "refresh"
DEFAULT_NAME = "Empower Reader"
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)
DEFAULT_DATA_FILE = "empower_reader/latest.json"
ENERGY_STATISTIC_UNIT = "kWh"

CONF_DATA_FILE = "data_file"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

STORAGE_VERSION = 1


def sensor_entity_id(key: str) -> str:
    return f"sensor.{DOMAIN}_{key}"


def button_entity_id(key: str) -> str:
    return f"button.{DOMAIN}_{key}"


def external_statistic_id(entry_id: str, key: str) -> str:
    safe_entry_id = re.sub(r"[^a-z0-9_]+", "_", entry_id.lower()).strip("_")
    return f"{DOMAIN}:{safe_entry_id}_{key}"
