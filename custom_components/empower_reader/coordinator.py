from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import EmpowerClient, EmpowerConnectionError, EmpowerData, EmpowerPoint
from .const import (
    CONF_DATA_FILE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DATA_FILE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    STATISTICS_ID,
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
            entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.config_entry = entry
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}"
        )
        self._cache: dict[str, Any] | None = None
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

    def _current_local_date(self) -> Any:
        return dt_util.now().astimezone(
            dt_util.get_time_zone(self._hass.config.time_zone)
        ).date()

    def _local_date_for_point(self, point: EmpowerPoint) -> Any:
        return self._point_start(point).astimezone(
            dt_util.get_time_zone(self._hass.config.time_zone)
        ).date()

    def _current_day_total(self, data: EmpowerData) -> float:
        today = self._current_local_date()
        return round(
            sum(point.kwh for point in data.points if self._local_date_for_point(point) == today),
            3,
        )

    def _latest_available_day_total(self, data: EmpowerData) -> float:
        if not data.points:
            return 0.0
        latest_day = self._local_date_for_point(data.points[-1])
        return round(
            sum(
                point.kwh
                for point in data.points
                if self._local_date_for_point(point) == latest_day
            ),
            3,
        )

    def _visible_seed_total(self, data: EmpowerData) -> float:
        current_day_total = self._current_day_total(data)
        if current_day_total > 0.0:
            return current_day_total
        return self._latest_available_day_total(data)

    def _initial_state_from_visible_data(self, data: EmpowerData) -> tuple[float, str]:
        if not data.points:
            return 0.0, ""
        return self._visible_seed_total(data), data.points[-1].ts.isoformat()

    async def _async_load_cache(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = await self._store.async_load() or {}
        return self._cache

    async def _async_save_cache(self) -> None:
        if self._cache is not None:
            await self._store.async_save(self._cache)

    async def _async_inject_statistics(
        self, points: list[EmpowerPoint], sum_base: float
    ) -> tuple[bool, float]:
        """Group points into hourly buckets and inject into the recorder.

        Returns (success, new_cumulative_sum). On failure returns (False, sum_base)
        so the caller knows not to advance stats_through_ts.
        """
        if not points:
            return True, sum_base

        # Import recorder classes lazily so any version mismatch only affects
        # statistics injection and does not prevent the integration from loading.
        try:
            from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
                StatisticData,
                StatisticMetaData,
                async_add_external_statistics,
            )
        except ImportError:
            try:
                from homeassistant.components.recorder.models import (  # noqa: PLC0415
                    StatisticData,
                    StatisticMetaData,
                )
                from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
                    async_add_external_statistics,
                )
            except ImportError as exc:
                _LOGGER.warning("Empower: recorder statistics API not available: %s", exc)
                return False, sum_base

        hourly: dict[datetime, float] = defaultdict(float)
        for point in points:
            utc = self._point_start(point)
            hour_start = utc.replace(minute=0, second=0, microsecond=0)
            hourly[hour_start] += point.kwh

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Electric Energy",
            source=DOMAIN,
            statistic_id=STATISTICS_ID,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        stats: list[StatisticData] = []
        running_sum = sum_base
        for hour_start in sorted(hourly):
            hour_kwh = round(hourly[hour_start], 3)
            running_sum = round(running_sum + hour_kwh, 3)
            stats.append(StatisticData(start=hour_start, state=hour_kwh, sum=running_sum))

        try:
            async_add_external_statistics(self._hass, metadata, stats)
            _LOGGER.warning(
                "Empower: injected %d hourly statistics through %s (cumulative %.3f kWh)",
                len(stats),
                stats[-1].start.isoformat(),
                running_sum,
            )
            return True, running_sum
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Empower: failed to inject statistics into recorder: %s", exc)
            return False, sum_base

    async def _async_update_data(self) -> EmpowerSnapshot:
        _LOGGER.warning("Empower: coordinator update starting")
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
        latest_visible_ts = data.points[-1].ts.isoformat() if data.points else ""
        visible_seed_total = self._visible_seed_total(data)

        # --- total_kwh / last_seen_ts tracking (sensor state) ---

        if "tracked_local_date" in electric:
            total_kwh, last_seen_ts = self._initial_state_from_visible_data(data)
            _LOGGER.info(
                "Migrated legacy Empower energy cache to monotonic mode at %.3f kWh through %s",
                total_kwh,
                last_seen_ts,
            )
        elif not electric:
            total_kwh, last_seen_ts = self._initial_state_from_visible_data(data)
            _LOGGER.info(
                "Started native Empower energy accumulation at %.3f kWh from interval %s",
                total_kwh,
                last_seen_ts,
            )
        else:
            if total_kwh == 0.0 and visible_seed_total > 0.0 and latest_visible_ts:
                total_kwh = visible_seed_total
                last_seen_ts = latest_visible_ts
                _LOGGER.info(
                    "Re-seeded Empower energy total from visible helper data at %.3f kWh",
                    total_kwh,
                )

            new_points: list[EmpowerPoint] = [
                p for p in data.points
                if not last_seen_ts or p.ts.isoformat() > last_seen_ts
            ]
            if new_points:
                total_kwh = round(total_kwh + sum(p.kwh for p in new_points), 3)
                last_seen_ts = new_points[-1].ts.isoformat()
                _LOGGER.info(
                    "Added %s Empower intervals through %s; total is now %.3f kWh",
                    len(new_points),
                    last_seen_ts,
                    total_kwh,
                )
            elif data.points and not last_seen_ts:
                last_seen_ts = data.points[-1].ts.isoformat()

        # --- recorder statistics injection ---
        # Tracked independently so historical hours get correct timestamps in the
        # Energy Dashboard even when data arrives in batches.

        stats_through_ts = str(electric.get("stats_through_ts", ""))
        stats_sum = float(electric.get("stats_sum", 0.0))

        # If a previous injection failed after saving stats_through_ts, stats_sum will
        # be 0 while stats_through_ts is non-empty. Reset so all points are retried.
        if stats_through_ts and stats_sum == 0.0 and data.points:
            _LOGGER.warning("Empower: resetting statistics cursor to retry failed injection")
            stats_through_ts = ""

        stats_new_points: list[EmpowerPoint] = [
            p for p in data.points
            if not stats_through_ts or p.ts.isoformat() > stats_through_ts
        ]
        if stats_new_points:
            success, stats_sum = await self._async_inject_statistics(stats_new_points, stats_sum)
            if success:
                stats_through_ts = stats_new_points[-1].ts.isoformat()

        # --- persist ---

        cache["electric"] = {
            "last_seen_ts": last_seen_ts,
            "last_ts": last_seen_ts,
            "total_kwh": total_kwh,
            "stats_through_ts": stats_through_ts,
            "stats_sum": stats_sum,
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
