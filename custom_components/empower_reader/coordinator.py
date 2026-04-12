from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import EmpowerAuthError, EmpowerClient, EmpowerConnectionError, EmpowerData
from .const import (
    CONF_DASHBOARD_URL,
    CONF_LOGIN_URL,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DASHBOARD_URL,
    DEFAULT_LOGIN_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmpowerSnapshot:
    data: EmpowerData
    total_kwh: float


class EmpowerDataUpdateCoordinator(DataUpdateCoordinator[EmpowerSnapshot]):
    """Coordinate Empower data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: ClientSession,
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
        self._session = session
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._cache: dict[str, Any] | None = None
        self.update_interval = timedelta(minutes=scan_interval_minutes)

    async def _async_load_cache(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = await self._store.async_load() or {}
        return self._cache

    async def _async_save_cache(self) -> None:
        if self._cache is not None:
            await self._store.async_save(self._cache)

    async def _async_update_data(self) -> EmpowerSnapshot:
        client = EmpowerClient(
            self._session,
            username=self.config_entry.data["username"],
            password=self.config_entry.data["password"],
            login_url=self.config_entry.data.get(CONF_LOGIN_URL, DEFAULT_LOGIN_URL),
            dashboard_url=self.config_entry.data.get(CONF_DASHBOARD_URL, DEFAULT_DASHBOARD_URL),
        )
        try:
            data = await client.async_fetch_data()
        except EmpowerAuthError as exc:
            raise ConfigEntryAuthFailed from exc
        except EmpowerConnectionError as exc:
            raise UpdateFailed(str(exc)) from exc
        except Exception as exc:
            raise UpdateFailed(str(exc)) from exc

        cache = await self._async_load_cache()
        electric = cache.get("electric", {})
        last_ts = str(electric.get("last_ts", ""))
        total_kwh = float(electric.get("total_kwh", 0.0))
        newest_ts = last_ts

        for point in data.points:
            point_iso = point.ts.isoformat()
            if last_ts and point_iso <= last_ts:
                continue
            total_kwh += point.kwh
            newest_ts = point_iso

        if not newest_ts and data.points:
            newest_ts = data.points[-1].ts.isoformat()

        cache["electric"] = {
            "last_ts": newest_ts,
            "total_kwh": total_kwh,
        }
        await self._async_save_cache()
        return EmpowerSnapshot(data=data, total_kwh=total_kwh)
