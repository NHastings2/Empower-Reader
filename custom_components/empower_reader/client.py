from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientResponseError, ClientSession
from bs4 import BeautifulSoup

from .const import DEFAULT_DASHBOARD_URL, DEFAULT_LOGIN_URL

_LOGGER = logging.getLogger(__name__)
STEP = timedelta(minutes=15)

USERNAME_FIELD = "Input.UserName"
PASSWORD_FIELD = "Input.Password"


class EmpowerError(Exception):
    """Base exception for Empower integration errors."""


class EmpowerAuthError(EmpowerError):
    """Raised when login fails."""


class EmpowerConnectionError(EmpowerError):
    """Raised when the remote site cannot be reached or parsed."""


@dataclass(frozen=True)
class EmpowerPoint:
    ts: datetime
    kwh: float


@dataclass(frozen=True)
class EmpowerData:
    customer_name: str | None
    customer_address: str | None
    meter_number: str | None
    sdp: str | None
    last_interval_time: datetime
    last_interval_kwh: float
    points: list[EmpowerPoint]


def _looks_like_bot_page(html: str) -> bool:
    return "_Incapsula_Resource" in html and USERNAME_FIELD not in html


def _extract_first_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise EmpowerConnectionError("No JSON object found in dashboard script")

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

    raise EmpowerConnectionError("Dashboard JSON object appears incomplete")


def _parse_points(payload: dict[str, Any]) -> list[EmpowerPoint]:
    meter_reads = payload.get("meterReads")
    if not isinstance(meter_reads, dict):
        raise EmpowerConnectionError("Expected meterReads in Empower payload")

    start = datetime.fromisoformat(meter_reads["readsStartDate"])
    end = datetime.fromisoformat(meter_reads["readsEndDate"])

    raw_values = []
    for raw in str(meter_reads.get("deliveredReads", "")).split(","):
        value = raw.strip()
        raw_values.append(float(value) if value else 0.0)

    if end < start:
        return []

    interval_count = int((end - start) // STEP) + 1
    if len(raw_values) < interval_count:
        raw_values.extend([0.0] * (interval_count - len(raw_values)))
    elif len(raw_values) > interval_count:
        raw_values = raw_values[:interval_count]

    return [
        EmpowerPoint(start + index * STEP, raw_values[index])
        for index in range(interval_count)
    ]


def _parse_payload_from_dashboard(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    for index, script in enumerate(soup.find_all("script")):
        text = script.string
        if not text or "customerSDPPackage" not in text:
            continue

        try:
            return json.loads(_extract_first_balanced_object(text))
        except Exception as exc:
            errors.append(f"{index}:{exc}")

    raise EmpowerConnectionError(
        "Unable to locate customerSDPPackage in dashboard HTML. "
        f"Sample errors: {'; '.join(errors[:3])}"
    )


def _parse_login_form(html: str, login_url: str) -> tuple[str, dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form is None:
        raise EmpowerConnectionError("Could not find login form on Empower login page")

    action = form.get("action") or login_url
    form_url = urljoin(login_url, action)
    payload: dict[str, str] = {}

    for field in form.find_all("input"):
        name = field.get("name")
        if not name or name in {USERNAME_FIELD, PASSWORD_FIELD}:
            continue
        payload[name] = field.get("value", "")

    return form_url, payload


def _build_data(payload: dict[str, Any]) -> EmpowerData:
    points = _parse_points(payload)
    if not points:
        raise EmpowerConnectionError("Empower returned no interval data")

    customer = None
    meters = payload.get("customerMeters")
    if isinstance(meters, list) and meters and isinstance(meters[0], dict):
        customer = meters[0]

    return EmpowerData(
        customer_name=customer.get("customerName") if customer else None,
        customer_address=customer.get("customerAddress1") if customer else None,
        meter_number=customer.get("meterNumber") if customer else None,
        sdp=customer.get("sdp") if customer else None,
        last_interval_time=points[-1].ts,
        last_interval_kwh=points[-1].kwh,
        points=points,
    )


class EmpowerClient:
    """HTTP client for fetching Empower dashboard data."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        login_url: str = DEFAULT_LOGIN_URL,
        dashboard_url: str = DEFAULT_DASHBOARD_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._login_url = login_url
        self._dashboard_url = dashboard_url

    async def async_fetch_data(self) -> EmpowerData:
        try:
            async with self._session.get(self._login_url) as response:
                response.raise_for_status()
                login_html = await response.text()
        except (ClientResponseError, ClientError) as exc:
            raise EmpowerConnectionError(f"Unable to load login page: {exc}") from exc

        if _looks_like_bot_page(login_html):
            raise EmpowerConnectionError("Empower served an anti-bot challenge on login")

        login_action, form_data = _parse_login_form(login_html, self._login_url)
        form_data[USERNAME_FIELD] = self._username
        form_data[PASSWORD_FIELD] = self._password

        try:
            async with self._session.post(login_action, data=form_data, allow_redirects=True) as response:
                response.raise_for_status()
                post_login_html = await response.text()
        except (ClientResponseError, ClientError) as exc:
            raise EmpowerConnectionError(f"Login request failed: {exc}") from exc

        if USERNAME_FIELD in post_login_html and "Forgot your" in post_login_html:
            raise EmpowerAuthError("Empower login was rejected")

        try:
            async with self._session.get(self._dashboard_url) as response:
                response.raise_for_status()
                dashboard_html = await response.text()
        except (ClientResponseError, ClientError) as exc:
            raise EmpowerConnectionError(f"Unable to load dashboard: {exc}") from exc

        if _looks_like_bot_page(dashboard_html):
            raise EmpowerConnectionError("Empower served an anti-bot challenge on dashboard")

        if USERNAME_FIELD in dashboard_html and "Forgot your" in dashboard_html:
            _LOGGER.debug("Dashboard redirected back to login page")
            raise EmpowerAuthError("Empower session was not authenticated")

        payload = _parse_payload_from_dashboard(dashboard_html)
        return _build_data(payload)
