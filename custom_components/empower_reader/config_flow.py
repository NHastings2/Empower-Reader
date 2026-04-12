from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .client import EmpowerClient, EmpowerConnectionError
from .const import (
    CONF_DATA_FILE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DATA_FILE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DATA_FILE, default=DEFAULT_DATA_FILE): str,
    }
)


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL_MINUTES,
            default=DEFAULT_SCAN_INTERVAL_MINUTES,
        ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
    }
)


def _validate_input(data: dict[str, str], config_dir: str) -> str:
    client = EmpowerClient(Path(config_dir) / data[CONF_DATA_FILE])
    empower_data = client.fetch_data()
    return empower_data.sdp or empower_data.meter_number or data[CONF_DATA_FILE]


class EmpowerReaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                unique_id = await self.hass.async_add_executor_job(
                    _validate_input, user_input, self.hass.config.config_dir
                )
            except EmpowerConnectionError as exc:
                _LOGGER.warning("Empower helper validation failed during config flow: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Empower helper validation")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Empower Reader",
                    data={
                        CONF_DATA_FILE: user_input[CONF_DATA_FILE],
                        CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return EmpowerReaderOptionsFlow(config_entry)


class EmpowerReaderOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, int] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        default_data_file = self.config_entry.options.get(
            CONF_DATA_FILE,
            self.config_entry.data.get(CONF_DATA_FILE, DEFAULT_DATA_FILE),
        )
        default_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES,
            self.config_entry.data.get(
                CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
            ),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DATA_FILE,
                        default=default_data_file,
                    ): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL_MINUTES,
                        default=default_interval,
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
                }
            ),
        )
