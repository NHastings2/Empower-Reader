from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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
)


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

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

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
        }
