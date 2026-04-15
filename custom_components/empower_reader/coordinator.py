from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import EmpowerClient, EmpowerConnectionError, EmpowerData, EmpowerPoint
from .const import (
    CONF_DATA_FILE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DATA_FILE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmpowerSnapshot:
    data: EmpowerData
    total_kwh: float
    imported_through: Any | None


class EmpowerDataUpdateCoordinator(DataUpdateCoordinator[EmpowerSnapshot]):
    """Coordinate Empower data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        scan_interval_minutes = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES,
            entry.data.get(
                CONF_SCAN_INTERVAL_MINUTES,
                int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
            ),
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.config_entry = entry
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}"
        )
        self._cache: dict[str, Any] | None = None
        self.update_interval = timedelta(minutes=scan_interval_minutes)
        self._hass = hass

    def _point_start(self, point: EmpowerPoint) -> Any:
        if point.ts.tzinfo is None:
            local_tz = dt_util.get_time_zone(self._hass.config.time_zone)
            aware = point.ts.replace(tzinfo=local_tz)
        else:
            aware = point.ts
        return dt_util.as_utc(aware)

    def _parse_cached_point_time(self, raw: str) -> Any | None:
        parsed = dt_util.parse_datetime(raw)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            local_tz = dt_util.get_time_zone(self._hass.config.time_zone)
            parsed = parsed.replace(tzinfo=local_tz)
        return dt_util.as_utc(parsed)

    def _point_local_date(self, point: EmpowerPoint) -> Any:
        return dt_util.as_local(self._point_start(point)).date()

    def _current_local_date(self) -> Any:
        return dt_util.now().date()

    def _initial_total_for_today(self, data: EmpowerData) -> tuple[float, str]:
        today = self._current_local_date()
        todays_points = [
            point for point in data.points if self._point_local_date(point) == today
        ]
        if not todays_points:
            return 0.0, data.points[-1].ts.isoformat() if data.points else ""
        return (
            round(sum(point.kwh for point in todays_points), 3),
            todays_points[-1].ts.isoformat(),
        )

    async def _async_load_cache(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = await self._store.async_load() or {}
        return self._cache

    async def _async_save_cache(self) -> None:
        if self._cache is not None:
            await self._store.async_save(self._cache)

    async def _async_update_data(self) -> EmpowerSnapshot:
        client = EmpowerClient(
            Path(
                self._hass.config.path(
                    self.config_entry.data.get(CONF_DATA_FILE, DEFAULT_DATA_FILE)
                )
            )
        )
        try:
            data = await self._hass.async_add_executor_job(client.fetch_data)
        except EmpowerConnectionError as exc:
            raise UpdateFailed(str(exc)) from exc
        except Exception as exc:
            raise UpdateFailed(str(exc)) from exc

        cache = await self._async_load_cache()
        electric = cache.get("electric", {})
        last_seen_ts = str(electric.get("last_seen_ts", ""))
        total_kwh = float(electric.get("total_kwh", 0.0))
        tracked_local_date = str(electric.get("tracked_local_date", ""))
        today_local_date = self._current_local_date().isoformat()

        if not electric or tracked_local_date != today_local_date:
            total_kwh, last_seen_ts = self._initial_total_for_today(data)
            cache["electric"] = {
                "last_seen_ts": last_seen_ts,
                "last_ts": last_seen_ts,
                "total_kwh": total_kwh,
                "tracked_local_date": today_local_date,
            }
            await self._async_save_cache()
            imported_through = (
                self._parse_cached_point_time(last_seen_ts) if last_seen_ts else None
            )
            _LOGGER.info(
                "Started native Empower energy accumulation for %s at %.3f kWh",
                today_local_date,
                total_kwh,
            )
            return EmpowerSnapshot(
                data=data,
                total_kwh=total_kwh,
                imported_through=imported_through,
            )

        new_points: list[EmpowerPoint] = []
        for point in data.points:
            point_iso = point.ts.isoformat()
            if last_seen_ts and point_iso <= last_seen_ts:
                continue
            if self._point_local_date(point) != self._current_local_date():
                continue
            new_points.append(point)

        if new_points:
            total_kwh = round(total_kwh + sum(point.kwh for point in new_points), 3)
            last_seen_ts = new_points[-1].ts.isoformat()
            _LOGGER.info(
                "Added %s Empower intervals for %s; total is now %.3f kWh",
                len(new_points),
                today_local_date,
                total_kwh,
            )
        elif data.points and not last_seen_ts:
            last_seen_ts = data.points[-1].ts.isoformat()

        cache["electric"] = {
            "last_seen_ts": last_seen_ts,
            "last_ts": last_seen_ts,
            "total_kwh": total_kwh,
            "tracked_local_date": today_local_date,
        }
        await self._async_save_cache()
        imported_through = (
            self._parse_cached_point_time(last_seen_ts) if last_seen_ts else None
        )
        return EmpowerSnapshot(
            data=data,
            total_kwh=total_kwh,
            imported_through=imported_through,
        )
