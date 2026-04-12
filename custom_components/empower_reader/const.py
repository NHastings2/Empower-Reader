from __future__ import annotations

from datetime import timedelta

DOMAIN = "empower_reader"
DEFAULT_NAME = "Empower Reader"
DEFAULT_LOGIN_URL = "https://www.empowernaperville.com"
DEFAULT_DASHBOARD_URL = "https://www.empowernaperville.com/Dashboard"
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

CONF_DASHBOARD_URL = "dashboard_url"
CONF_LOGIN_URL = "login_url"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

STORAGE_VERSION = 1
