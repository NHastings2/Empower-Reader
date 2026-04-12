from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, button_entity_id
from .coordinator import EmpowerDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class EmpowerButtonDescription(ButtonEntityDescription):
    pass


BUTTONS: tuple[EmpowerButtonDescription, ...] = (
    EmpowerButtonDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmpowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        EmpowerRefreshButton(coordinator, entry, description)
        for description in BUTTONS
    )


class EmpowerRefreshButton(ButtonEntity):
    entity_description: EmpowerButtonDescription

    def __init__(
        self,
        coordinator: EmpowerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: EmpowerButtonDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = button_entity_id(description.key)

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        data = self._coordinator.data.data
        identifier = data.sdp or self._entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="Naperville Empower",
            name=data.customer_name or "Empower Reader",
            model=data.meter_number,
        )
