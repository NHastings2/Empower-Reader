from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


STEP = timedelta(minutes=15)
USERNAME_SELECTOR = (
    'input[name="Input.UserName"], input[id="txtusername"], '
    'input[name="Email"], input[type="email"]'
)
PASSWORD_SELECTOR = (
    'input[name="Input.Password"], input[id="pwdinput"], input[type="password"]'
)
SUBMIT_SELECTOR = 'button[type="submit"], input[type="submit"]'


@dataclass(frozen=True)
class Settings:
    blob_json_path: Path
    storage_state_path: Path
    state_cache_path: Path
    login_url: str
    dashboard_url: str
    username: str
    password: str
    headless: bool
    try_headless_first: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_discovery_prefix: str
    mqtt_client_id: str
    device_id: str
    device_name: str


@dataclass(frozen=True)
class Point:
    ts: datetime
    kwh: float


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def looks_like_bot_page(html: str) -> bool:
    return "_Incapsula_Resource" in html and "Input.UserName" not in html


def extract_first_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in script contents")

    depth = 0
    in_string = False
    quote = ""
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_string = False
            continue

        if char in {'"', "'"}:
            in_string = True
            quote = char
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError("JSON object in script appears to be incomplete")


def extract_embedded_json_from_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    errors: List[str] = []

    for index, script in enumerate(soup.find_all("script")):
        text = script.string
        if not text or "customerSDPPackage" not in text:
            continue

        try:
            return json.loads(extract_first_balanced_object(text))
        except Exception as exc:
            errors.append(f"{index}:{exc}")

    raise ValueError(
        "Unable to locate or parse customerSDPPackage from dashboard HTML. "
        f"Sample errors: {'; '.join(errors[:5])}"
    )


def _login_and_fetch(page: Any, settings: Settings) -> str:
    page.goto(settings.login_url, wait_until="domcontentloaded", timeout=120_000)
    html = page.content()
    if looks_like_bot_page(html) and settings.try_headless_first:
        raise RuntimeError("BOT_PAGE_LOGIN")

    page.wait_for_selector(PASSWORD_SELECTOR, timeout=60_000)
    page.fill(USERNAME_SELECTOR, settings.username)
    page.fill(PASSWORD_SELECTOR, settings.password)
    page.click(SUBMIT_SELECTOR)
    page.wait_for_load_state("networkidle", timeout=120_000)

    page.goto(settings.dashboard_url, wait_until="networkidle", timeout=120_000)
    html = page.content()
    if looks_like_bot_page(html):
        raise RuntimeError("BOT_PAGE_DASHBOARD")

    return html


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_empower_blob(settings: Settings) -> Dict[str, Any]:
    ensure_parent_dir(settings.storage_state_path)
    ensure_parent_dir(settings.blob_json_path)

    attempts = [settings.headless]
    if settings.try_headless_first and settings.headless:
        attempts = [True, False]

    last_error: Optional[Exception] = None

    for headless in attempts:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=headless,
                    executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),
                )
                context_options: Dict[str, Any] = {
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"
                    )
                }
                if settings.storage_state_path.exists():
                    context_options["storage_state"] = str(settings.storage_state_path)

                context = browser.new_context(**context_options)
                page = context.new_page()
                html = _login_and_fetch(page, settings)
                data = extract_embedded_json_from_html(html)
                context.storage_state(path=str(settings.storage_state_path))
                browser.close()
                write_json(settings.blob_json_path, data)
                return data
        except RuntimeError as exc:
            last_error = exc
            if str(exc).startswith("BOT_PAGE_") and headless:
                continue
            break
        except PlaywrightTimeoutError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break

    raise RuntimeError(f"Empower fetch failed: {last_error}")


def parse_csv_kwh(csv_str: str) -> List[float]:
    values: List[float] = []
    for raw in csv_str.split(","):
        value = raw.strip()
        values.append(float(value) if value else 0.0)
    return values


def expected_intervals(start: datetime, end: datetime) -> int:
    if end < start:
        return 0
    return int((end - start) // STEP) + 1


def build_points_from_meter_reads(pkg: Dict[str, Any]) -> List[Point]:
    meter_reads = pkg.get("meterReads")
    if not isinstance(meter_reads, dict):
        raise ValueError("Expected meterReads to be an object in the Empower payload")

    start = datetime.fromisoformat(meter_reads["readsStartDate"])
    end = datetime.fromisoformat(meter_reads["readsEndDate"])
    values = parse_csv_kwh(meter_reads.get("deliveredReads", ""))

    interval_count = expected_intervals(start, end)
    if interval_count <= 0:
        return []

    if len(values) < interval_count:
        values.extend([0.0] * (interval_count - len(values)))
    elif len(values) > interval_count:
        values = values[:interval_count]

    return [Point(start + index * STEP, values[index]) for index in range(interval_count)]


def load_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def update_running_total(
    cache: Dict[str, Any], points: List[Point]
) -> Tuple[float, float, str]:
    state = cache.get("electric", {})
    last_ts = str(state.get("last_ts", ""))
    total_kwh = float(state.get("total_kwh", 0.0))
    newest_interval_kwh = 0.0
    newest_interval_iso = last_ts

    for point in points:
        iso = point.ts.isoformat()
        if last_ts and iso <= last_ts:
            continue
        total_kwh += point.kwh
        newest_interval_kwh = point.kwh
        newest_interval_iso = iso

    if not newest_interval_iso and points:
        newest_interval_iso = points[-1].ts.isoformat()
        newest_interval_kwh = points[-1].kwh

    cache["electric"] = {"last_ts": newest_interval_iso, "total_kwh": total_kwh}
    return total_kwh, newest_interval_kwh, newest_interval_iso


def _device_payload(settings: Settings, pkg: Dict[str, Any]) -> Dict[str, Any]:
    meter = {}
    meters = pkg.get("customerMeters")
    if isinstance(meters, list) and meters and isinstance(meters[0], dict):
        meter = meters[0]

    payload: Dict[str, Any] = {
        "identifiers": [settings.device_id],
        "name": settings.device_name,
        "manufacturer": "Naperville Empower",
    }
    if meter.get("meterNumber"):
        payload["model"] = str(meter["meterNumber"])
    if meter.get("sdp"):
        payload["serial_number"] = str(meter["sdp"])
    return payload


def mqtt_connect(settings: Settings) -> mqtt.Client:
    client = mqtt.Client(
        client_id=settings.mqtt_client_id,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    )
    if settings.mqtt_user:
        client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()
    return client


def publish_status(client: mqtt.Client, settings: Settings, online: bool) -> None:
    client.publish(
        f"{settings.device_id}/status",
        "online" if online else "offline",
        retain=True,
    )


def publish_discovery_sensor(
    client: mqtt.Client,
    settings: Settings,
    pkg: Dict[str, Any],
    entity_id: str,
    name: str,
    unit: Optional[str] = None,
    device_class: Optional[str] = None,
    state_class: Optional[str] = None,
) -> None:
    topic = (
        f"{settings.mqtt_discovery_prefix}/sensor/"
        f"{settings.device_id}/{entity_id}/config"
    )
    payload: Dict[str, Any] = {
        "name": name,
        "object_id": entity_id,
        "unique_id": f"{settings.device_id}_{entity_id}",
        "state_topic": f"{settings.device_id}/sensor/{entity_id}/state",
        "availability_topic": f"{settings.device_id}/status",
        "device": _device_payload(settings, pkg),
    }
    if unit:
        payload["unit_of_measurement"] = unit
    if device_class:
        payload["device_class"] = device_class
    if state_class:
        payload["state_class"] = state_class
    client.publish(topic, json.dumps(payload), retain=True)


def publish_state(
    client: mqtt.Client, settings: Settings, entity_id: str, value: str
) -> None:
    client.publish(
        f"{settings.device_id}/sensor/{entity_id}/state",
        str(value),
        retain=True,
    )


def publish_to_home_assistant(settings: Settings, pkg: Dict[str, Any]) -> Dict[str, str]:
    points = build_points_from_meter_reads(pkg)
    if not points:
        raise ValueError("No 15-minute meter reads were available to publish")

    cache = load_cache(settings.state_cache_path)
    total_kwh, _, _ = update_running_total(cache, points)
    save_cache(settings.state_cache_path, cache)

    last_point = points[-1]
    client = mqtt_connect(settings)
    publish_status(client, settings, True)

    publish_discovery_sensor(
        client,
        settings,
        pkg,
        entity_id="electric_total_kwh",
        name="Empower Electric Total",
        unit="kWh",
        device_class="energy",
        state_class="total_increasing",
    )
    publish_discovery_sensor(
        client,
        settings,
        pkg,
        entity_id="electric_last_interval_kwh",
        name="Empower Electric Last Interval",
        unit="kWh",
        device_class="energy",
        state_class="measurement",
    )
    publish_discovery_sensor(
        client,
        settings,
        pkg,
        entity_id="electric_last_interval_time",
        name="Empower Electric Last Interval Time",
        device_class="timestamp",
    )

    publish_state(client, settings, "electric_total_kwh", f"{total_kwh:.3f}")
    publish_state(client, settings, "electric_last_interval_kwh", f"{last_point.kwh:.3f}")
    publish_state(client, settings, "electric_last_interval_time", last_point.ts.isoformat())

    client.loop_stop()
    client.disconnect()

    return {
        "total_kwh": f"{total_kwh:.3f}",
        "last_interval_kwh": f"{last_point.kwh:.3f}",
        "last_interval_time": last_point.ts.isoformat(),
    }
