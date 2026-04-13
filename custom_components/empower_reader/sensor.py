from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, sensor_entity_id
from .coordinator import EmpowerDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class EmpowerSensorDescription(SensorEntityDescription):
    value_fn: Any


SENSORS: tuple[EmpowerSensorDescription, ...] = (
    EmpowerSensorDescription(
        key="electric_total_kwh",
        translation_key="electric_total_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda snapshot: snapshot.total_kwh,
    ),
    EmpowerSensorDescription(
        key="electric_last_interval_kwh",
        translation_key="electric_last_interval_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda snapshot: snapshot.data.last_interval_kwh,
    ),
    EmpowerSensorDescription(
        key="electric_last_interval_time",
        translation_key="electric_last_interval_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.data.last_interval_time,
    ),
    EmpowerSensorDescription(
        key="electric_estimated_demand",
        translation_key="electric_estimated_demand",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda snapshot: round(snapshot.data.last_interval_kwh * 4000, 1),
    ),
    EmpowerSensorDescription(
        key="first_available_interval",
        translation_key="first_available_interval",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.data.first_interval_time,
    ),
    EmpowerSensorDescription(
        key="helper_last_fetch",
        translation_key="helper_last_fetch",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.data.fetched_at,
    ),
    EmpowerSensorDescription(
        key="helper_data_age_minutes",
        translation_key="helper_data_age_minutes",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: _helper_age_minutes(snapshot.data.fetched_at),
    ),
    EmpowerSensorDescription(
        key="available_interval_count",
        translation_key="available_interval_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: len(snapshot.data.points),
    ),
    EmpowerSensorDescription(
        key="last_imported_interval",
        translation_key="last_imported_interval",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.imported_through,
    ),
)


def _helper_age_minutes(fetched_at: datetime | None) -> float | None:
    if fetched_at is None:
        return None
    normalized = _normalize_timestamp(fetched_at)
    if normalized is None:
        return None
    return round(max((dt_util.utcnow() - normalized).total_seconds(), 0) / 60, 1)


def _normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        local_tz = dt_util.DEFAULT_TIME_ZONE
        if local_tz is None:
            return value.replace(tzinfo=dt_util.UTC)
        value = value.replace(tzinfo=local_tz)
    return dt_util.as_utc(value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmpowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        EmpowerSensor(coordinator, entry, description) for description in SENSORS
    )


class EmpowerSensor(
    CoordinatorEntity[EmpowerDataUpdateCoordinator], SensorEntity
):
    entity_description: EmpowerSensorDescription

    def __init__(
        self,
        coordinator: EmpowerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: EmpowerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = sensor_entity_id(description.key)

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        if isinstance(value, datetime):
            return _normalize_timestamp(value)
        return value

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data.data
        identifier = data.sdp or self._entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="Naperville Empower",
            name=data.customer_name or "Empower Reader",
            model=data.meter_number,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.data
        return {
            "customer_address": data.customer_address,
            "meter_number": data.meter_number,
            "service_point_id": data.sdp,
            "first_available_interval": data.first_interval_time.isoformat(),
            "available_interval_count": len(data.points),
            "helper_fetched_at": data.fetched_at.isoformat() if data.fetched_at else None,
            "imported_through": (
                self.coordinator.data.imported_through.isoformat()
                if self.coordinator.data.imported_through
                else None
            ),
        }
