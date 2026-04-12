from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from empower_lib import Settings, fetch_empower_blob, publish_to_home_assistant


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("empower_reader")

OPTIONS_PATH = Path("/data/options.json")
DATA_DIR = Path("/data")


def load_options() -> dict:
    with OPTIONS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_settings(options: dict) -> Settings:
    return Settings(
        blob_json_path=DATA_DIR / "empower_blob.json",
        storage_state_path=DATA_DIR / "empower_storage_state.json",
        state_cache_path=DATA_DIR / "empower_state_cache.json",
        login_url=options["login_url"],
        dashboard_url=options["dashboard_url"],
        username=options["empower_username"],
        password=options["empower_password"],
        headless=bool(options["headless"]),
        try_headless_first=bool(options["try_headless_first"]),
        mqtt_host=options["mqtt_host"],
        mqtt_port=int(options["mqtt_port"]),
        mqtt_user=options.get("mqtt_user", ""),
        mqtt_password=options.get("mqtt_password", ""),
        mqtt_discovery_prefix=options["discovery_prefix"],
        mqtt_client_id="empower_reader_addon",
        device_id=options["device_id"],
        device_name=options["device_name"],
    )


def validate_options(options: dict) -> None:
    required = ["empower_username", "empower_password", "mqtt_host"]
    missing = [key for key in required if not str(options.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing required add-on options: {', '.join(missing)}")


def run_sync(settings: Settings) -> None:
    payload = fetch_empower_blob(settings)
    result = publish_to_home_assistant(settings, payload)
    LOGGER.info(
        "Published total=%s kWh, last_interval=%s kWh @ %s",
        result["total_kwh"],
        result["last_interval_kwh"],
        result["last_interval_time"],
    )


def main() -> int:
    options = load_options()
    validate_options(options)
    settings = build_settings(options)
    interval_seconds = max(int(options["poll_interval_minutes"]), 5) * 60

    LOGGER.info("Empower Reader add-on started; polling every %s minutes", interval_seconds // 60)
    while True:
        try:
            run_sync(settings)
        except Exception as exc:
            LOGGER.exception("Sync failed: %s", exc)

        time.sleep(interval_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("Fatal add-on error: %s", exc)
        raise SystemExit(1)
