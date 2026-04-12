from __future__ import annotations

import inspect
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
    ENERGY_STATISTIC_UNIT,
    STORAGE_VERSION,
    external_statistic_id,
    sensor_entity_id,
)

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
        StatisticMeanType,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )
except ImportError:  # pragma: no cover - Home Assistant runtime import guard
    StatisticData = None
    StatisticMetaData = None
    StatisticMeanType = None
    async_add_external_statistics = None


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
            entry.data.get(CONF_SCAN_INTERVAL_MINUTES, int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)),
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.config_entry = entry
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._cache: dict[str, Any] | None = None
        self.update_interval = timedelta(minutes=scan_interval_minutes)
        self._hass = hass

    def _statistic_metadata(
        self,
        *,
        statistic_id: str,
        name: str,
        unit_of_measurement: str,
        has_sum: bool,
        has_mean: bool,
        unit_class: str | None,
    ) -> Any:
        if StatisticMetaData is None:
            raise UpdateFailed("Recorder statistics API is unavailable")

        kwargs: dict[str, Any] = {
            "statistic_id": statistic_id,
            "source": "external",
            "name": name,
            "unit_of_measurement": unit_of_measurement,
        }
        optional_kwargs: dict[str, Any] = {
            "has_sum": has_sum,
            "has_mean": has_mean,
            "unit_class": unit_class,
        }
        if StatisticMeanType is not None:
            optional_kwargs["mean_type"] = (
                StatisticMeanType.ARITHMETIC
                if has_mean
                else StatisticMeanType.NONE
            )

        if StatisticMetaData is dict:
            return {
                **kwargs,
                **{key: value for key, value in optional_kwargs.items() if value is not None},
            }

        try:
            params = inspect.signature(StatisticMetaData).parameters
        except (TypeError, ValueError):
            params = {}

        if params:
            for key, value in optional_kwargs.items():
                if key in params and value is not None:
                    kwargs[key] = value
            return StatisticMetaData(**kwargs)

        for key, value in optional_kwargs.items():
            if value is not None:
                kwargs[key] = value

        try:
            return StatisticMetaData(**kwargs)
        except TypeError:
            minimal_kwargs = {
                "statistic_id": statistic_id,
                "source": "external",
                "name": name,
                "unit_of_measurement": unit_of_measurement,
            }
            return StatisticMetaData(**minimal_kwargs)

    def _statistic_data(self, **raw: Any) -> Any:
        if StatisticData is None:
            raise UpdateFailed("Recorder statistics API is unavailable")

        if StatisticData is dict:
            return raw

        try:
            params = inspect.signature(StatisticData).parameters
        except (TypeError, ValueError):
            params = {}

        if params:
            kwargs = {key: value for key, value in raw.items() if key in params}
            return StatisticData(**kwargs)

        try:
            return StatisticData(**raw)
        except TypeError:
            minimal_kwargs = {
                key: value
                for key, value in raw.items()
                if key in {"start", "state", "sum", "mean", "min", "max", "last_reset"}
            }
            if "start" not in minimal_kwargs:
                raise UpdateFailed("Recorder statistics data requires a start timestamp")
            return StatisticData(**minimal_kwargs)

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

    async def _async_import_interval_statistics(
        self,
        *,
        new_points: list[EmpowerPoint],
        total_before: float,
    ) -> float:
        if not new_points:
            return total_before
        if async_add_external_statistics is None:
            raise UpdateFailed("Recorder statistics import API is unavailable")

        total_statistic_id = external_statistic_id(
            self.config_entry.entry_id, "electric_total_kwh"
        )

        total_metadata = self._statistic_metadata(
            statistic_id=total_statistic_id,
            name="Empower Electric Total",
            unit_of_measurement=ENERGY_STATISTIC_UNIT,
            has_sum=True,
            has_mean=False,
            unit_class="energy",
        )

        running_total = total_before
        total_rows: list[Any] = []

        for point in new_points:
            start = self._point_start(point)
            running_total += point.kwh

            total_rows.append(
                self._statistic_data(
                    start=start,
                    state=round(running_total, 3),
                    sum=round(running_total, 3),
                )
            )

        await async_add_external_statistics(self._hass, total_metadata, total_rows)
        return running_total

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
        total_statistic_id = external_statistic_id(
            self.config_entry.entry_id, "electric_total_kwh"
        )
        cached_statistic_id = str(electric.get("statistic_id", ""))
        last_ts = str(electric.get("last_ts", ""))
        total_kwh = float(electric.get("total_kwh", 0.0))

        if cached_statistic_id and cached_statistic_id != total_statistic_id:
            _LOGGER.info(
                "Statistic ID changed from %s to %s; re-importing available Empower history",
                cached_statistic_id,
                total_statistic_id,
            )
            last_ts = ""
            total_kwh = 0.0

        new_points: list[EmpowerPoint] = []

        for point in data.points:
            point_iso = point.ts.isoformat()
            if last_ts and point_iso <= last_ts:
                continue
            new_points.append(point)

        imported_total = await self._async_import_interval_statistics(
            new_points=new_points,
            total_before=total_kwh,
        )
        newest_ts = last_ts
        if new_points:
            newest_ts = new_points[-1].ts.isoformat()
        elif data.points:
            newest_ts = data.points[-1].ts.isoformat()

        cache["electric"] = {
            "last_ts": newest_ts,
            "total_kwh": imported_total,
            "statistic_id": total_statistic_id,
        }
        await self._async_save_cache()
        imported_through = self._parse_cached_point_time(newest_ts) if newest_ts else None
        return EmpowerSnapshot(
            data=data,
            total_kwh=imported_total,
            imported_through=imported_through,
        )
