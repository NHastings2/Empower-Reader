from __future__ import annotations

from datetime import timedelta

DOMAIN = "empower_reader"
DEFAULT_NAME = "Empower Reader"
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)
DEFAULT_DATA_FILE = "empower_reader/latest.json"

CONF_DATA_FILE = "data_file"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

STORAGE_VERSION = 1
