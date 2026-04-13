from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


STEP = timedelta(minutes=15)


class EmpowerError(Exception):
    """Base exception for Empower integration errors."""


class EmpowerConnectionError(EmpowerError):
    """Raised when helper data cannot be loaded or parsed."""


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
    first_interval_time: datetime
    last_interval_time: datetime
    last_interval_kwh: float
    fetched_at: datetime | None
    points: list[EmpowerPoint]


def _parse_meter_reads(meter_reads: dict[str, Any]) -> list[EmpowerPoint]:
    start = datetime.fromisoformat(meter_reads["readsStartDate"])
    end = datetime.fromisoformat(meter_reads["readsEndDate"])
    raw_values: list[float] = []

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


def _iter_meter_reads_candidates(node: Any) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(node, dict):
        meter_reads = node.get("meterReads")
        if isinstance(meter_reads, dict):
            if "readsStartDate" in meter_reads and "readsEndDate" in meter_reads:
                matches.append(meter_reads)
        for value in node.values():
            matches.extend(_iter_meter_reads_candidates(value))
    elif isinstance(node, list):
        for item in node:
            matches.extend(_iter_meter_reads_candidates(item))
    return matches


def _parse_points(payload: dict[str, Any]) -> list[EmpowerPoint]:
    candidates = _iter_meter_reads_candidates(payload)
    if not candidates:
        raise EmpowerConnectionError("Expected meterReads in Empower payload")

    parsed_candidates: list[list[EmpowerPoint]] = []
    errors: list[str] = []

    for index, meter_reads in enumerate(candidates):
        try:
            points = _parse_meter_reads(meter_reads)
        except Exception as exc:
            errors.append(f"{index}:{exc}")
            continue
        if points:
            parsed_candidates.append(points)

    if not parsed_candidates:
        raise EmpowerConnectionError(
            "Helper data file did not include parseable interval data. "
            f"Candidate errors: {'; '.join(errors[:3])}"
        )

    return min(
        parsed_candidates,
        key=lambda points: (points[0].ts, -len(points)),
    )


def _build_data(document: dict[str, Any]) -> EmpowerData:
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise EmpowerConnectionError("Helper data file is missing a payload object")

    points = _parse_points(payload)
    if not points:
        raise EmpowerConnectionError("Helper data file did not include interval data")

    customer = None
    meters = payload.get("customerMeters")
    if isinstance(meters, list) and meters and isinstance(meters[0], dict):
        customer = meters[0]

    fetched_at_raw = document.get("fetched_at")
    fetched_at = (
        datetime.fromisoformat(fetched_at_raw)
        if isinstance(fetched_at_raw, str) and fetched_at_raw
        else None
    )

    return EmpowerData(
        customer_name=customer.get("customerName") if customer else None,
        customer_address=customer.get("customerAddress1") if customer else None,
        meter_number=customer.get("meterNumber") if customer else None,
        sdp=customer.get("sdp") if customer else None,
        first_interval_time=points[0].ts,
        last_interval_time=points[-1].ts,
        last_interval_kwh=points[-1].kwh,
        fetched_at=fetched_at,
        points=points,
    )


class EmpowerClient:
    """Read and parse helper output produced by the Playwright add-on."""

    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path

    def fetch_data(self) -> EmpowerData:
        if not self._data_path.exists():
            raise EmpowerConnectionError(
                f"Helper data file not found: {self._data_path}"
            )

        try:
            document = json.loads(self._data_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise EmpowerConnectionError(
                f"Unable to read helper data file: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise EmpowerConnectionError(
                f"Helper data file is not valid JSON: {exc}"
            ) from exc

        return _build_data(document)
