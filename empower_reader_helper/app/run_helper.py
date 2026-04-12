from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("empower_reader_helper")

OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/empower_storage_state.json")

USERNAME_SELECTOR = (
    'input[name="Input.UserName"], input[id="txtusername"], '
    'input[name="Email"], input[type="email"]'
)
PASSWORD_SELECTOR = (
    'input[name="Input.Password"], input[id="pwdinput"], input[type="password"]'
)
SUBMIT_SELECTOR = 'button[type="submit"], input[type="submit"]'


class HelperError(Exception):
    """Base helper error."""


def looks_like_bot_page(html: str) -> bool:
    return "_Incapsula_Resource" in html and "Input.UserName" not in html


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def extract_first_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise HelperError("No JSON object found in dashboard script")

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

    raise HelperError("Dashboard JSON object appears incomplete")


def extract_payload(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    for index, script in enumerate(soup.find_all("script")):
        text = script.string
        if not text or "customerSDPPackage" not in text:
            continue
        try:
            return json.loads(extract_first_balanced_object(text))
        except Exception as exc:
            errors.append(f"{index}:{exc}")

    raise HelperError(
        "Unable to locate customerSDPPackage in dashboard HTML. "
        f"Sample errors: {'; '.join(errors[:3])}"
    )


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    poll_interval_minutes: int
    output_path: Path
    login_url: str
    dashboard_url: str
    headless: bool
    try_headless_first: bool


def load_options() -> Settings:
    with OPTIONS_PATH.open("r", encoding="utf-8") as handle:
        options = json.load(handle)

    return Settings(
        username=options["empower_username"],
        password=options["empower_password"],
        poll_interval_minutes=max(int(options["poll_interval_minutes"]), 5),
        output_path=Path(options["output_path"]),
        login_url=options["login_url"],
        dashboard_url=options["dashboard_url"],
        headless=bool(options["headless"]),
        try_headless_first=bool(options["try_headless_first"]),
    )


def login_and_fetch(page: Any, settings: Settings) -> str:
    page.goto(settings.login_url, wait_until="domcontentloaded", timeout=120_000)

    html = page.content()
    if looks_like_bot_page(html) and settings.try_headless_first:
        raise HelperError("BOT_PAGE_LOGIN")

    page.wait_for_selector(PASSWORD_SELECTOR, timeout=60_000)
    page.fill(USERNAME_SELECTOR, settings.username)
    page.fill(PASSWORD_SELECTOR, settings.password)
    page.click(SUBMIT_SELECTOR)
    page.wait_for_load_state("networkidle", timeout=120_000)

    page.goto(settings.dashboard_url, wait_until="networkidle", timeout=120_000)
    html = page.content()
    if looks_like_bot_page(html):
        raise HelperError("BOT_PAGE_DASHBOARD")

    return html


def fetch_payload(settings: Settings) -> dict[str, Any]:
    attempts = [settings.headless]
    if settings.try_headless_first and settings.headless:
        attempts = [True, False]

    last_error: Exception | None = None

    for headless in attempts:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=headless,
                    executable_path="/usr/bin/chromium",
                )
                context_options: dict[str, Any] = {
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"
                    )
                }
                if STATE_PATH.exists():
                    context_options["storage_state"] = str(STATE_PATH)

                context = browser.new_context(**context_options)
                page = context.new_page()
                html = login_and_fetch(page, settings)
                payload = extract_payload(html)
                context.storage_state(path=str(STATE_PATH))
                browser.close()
                return payload
        except HelperError as exc:
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

    raise HelperError(f"Helper fetch failed: {last_error}")


def write_output(output_path: Path, payload: dict[str, Any]) -> None:
    document = {
        "fetched_at": datetime.utcnow().isoformat(),
        "payload": payload,
    }
    ensure_parent_dir(output_path)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(output_path)


def main() -> int:
    settings = load_options()
    LOGGER.info(
        "Empower Reader Helper started; polling every %s minutes",
        settings.poll_interval_minutes,
    )

    while True:
        try:
            payload = fetch_payload(settings)
            write_output(settings.output_path, payload)
            LOGGER.info("Wrote helper data to %s", settings.output_path)
        except Exception as exc:
            LOGGER.exception("Helper sync failed: %s", exc)

        time.sleep(settings.poll_interval_minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main())
