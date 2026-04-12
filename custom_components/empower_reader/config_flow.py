from __future__ import annotations

import voluptuous as vol
from aiohttp import CookieJar, ClientSession
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .client import EmpowerAuthError, EmpowerClient, EmpowerConnectionError
from .const import (
    CONF_DASHBOARD_URL,
    CONF_LOGIN_URL,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DASHBOARD_URL,
    DEFAULT_LOGIN_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_LOGIN_URL, default=DEFAULT_LOGIN_URL): str,
        vol.Optional(CONF_DASHBOARD_URL, default=DEFAULT_DASHBOARD_URL): str,
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


async def _validate_input(data: dict[str, str]) -> str:
    session = ClientSession(cookie_jar=CookieJar(unsafe=True))
    try:
        client = EmpowerClient(
            session,
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            login_url=data.get(CONF_LOGIN_URL, DEFAULT_LOGIN_URL),
            dashboard_url=data.get(CONF_DASHBOARD_URL, DEFAULT_DASHBOARD_URL),
        )
        empower_data = await client.async_fetch_data()
    finally:
        await session.close()

    return empower_data.sdp or empower_data.meter_number or data[CONF_USERNAME]


class EmpowerReaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                unique_id = await _validate_input(user_input)
            except EmpowerAuthError:
                errors["base"] = "invalid_auth"
            except EmpowerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Empower Reader",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_LOGIN_URL: user_input.get(CONF_LOGIN_URL, DEFAULT_LOGIN_URL),
                        CONF_DASHBOARD_URL: user_input.get(
                            CONF_DASHBOARD_URL, DEFAULT_DASHBOARD_URL
                        ),
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
                        CONF_SCAN_INTERVAL_MINUTES,
                        default=default_interval,
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
                }
            ),
        )
