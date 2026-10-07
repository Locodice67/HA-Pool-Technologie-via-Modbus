"""Config flow for the Pool Technologie integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FLOW_SENSOR,
    CONF_FRAMING,
    CONF_HOST,
    CONF_IGNORE_CONNECTION_ERROR,
    CONF_MODEL,
    CONF_PORT,
    CONF_REGULATION_ORP,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    DEFAULT_FRAMING,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    FRAMING_RTU_OVER_TCP,
    FRAMING_TCP,
    MAX_PORT,
    MAX_SCAN_INTERVAL,
    MAX_TIMEOUT,
    MAX_UNIT_ID,
    MIN_PORT,
    MIN_SCAN_INTERVAL,
    MIN_TIMEOUT,
    MIN_UNIT_ID,
    SCAN_INTERVAL,
)
from .models import MODELS
from .modbus_handler import ModbusHandler
from .registers import REG_PH

_LOGGER = logging.getLogger(__name__)


def _framing_selector():
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=FRAMING_TCP, label="Modbus TCP (MBAP)"
                ),
                selector.SelectOptionDict(
                    value=FRAMING_RTU_OVER_TCP, label="RTU over TCP"
                ),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _model_selector():
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=key, label=value["name"])
                for key, value in MODELS.items()
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class PoolTechnologieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT_ID]}"
            )
            self._abort_if_unique_id_configured()

            data = dict(user_input)
            ignore_error = data.pop(CONF_IGNORE_CONNECTION_ERROR, False)
            if not ignore_error:
                errors = await self._async_test_connection(data)

            if not errors:
                return self.async_create_entry(
                    title=MODELS[data[CONF_MODEL]]["name"],
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(),
            errors=errors,
        )

    async def _async_test_connection(self, user_input) -> dict:
        """Verify the device can be reached and answers a Modbus read."""
        handler = ModbusHandler(
            host=user_input[CONF_HOST],
            port=user_input[CONF_PORT],
            unit_id=user_input[CONF_UNIT_ID],
            timeout=user_input[CONF_TIMEOUT],
            framing=user_input[CONF_FRAMING],
        )
        try:
            connected = await self.hass.async_add_executor_job(handler.connect)
            if not connected:
                return {"base": "cannot_connect"}
            # The pH register is present on every supported model.
            result = await self.hass.async_add_executor_job(
                handler.read_register, REG_PH
            )
            if result is None:
                return {"base": "cannot_read"}
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Connection test failed: %s", err)
            return {"base": "unknown"}
        finally:
            await self.hass.async_add_executor_job(handler.close)
        return {}

    def _user_schema(self):
        return vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_PORT, max=MAX_PORT)
                ),
                vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UNIT_ID, max=MAX_UNIT_ID)
                ),
                vol.Required(CONF_MODEL): _model_selector(),
                vol.Required(CONF_REGULATION_ORP, default=False): bool,
                vol.Required(CONF_FLOW_SENSOR, default=False): bool,
                vol.Required(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT)
                ),
                vol.Required(CONF_FRAMING, default=DEFAULT_FRAMING): _framing_selector(),
                vol.Required(
                    CONF_IGNORE_CONNECTION_ERROR, default=False
                ): bool,
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PoolTechnologieOptionsFlow()


class PoolTechnologieOptionsFlow(config_entries.OptionsFlow):
    """Handle the integration options."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REGULATION_ORP,
                    default=entry.options.get(
                        CONF_REGULATION_ORP,
                        entry.data.get(CONF_REGULATION_ORP, False),
                    ),
                ): bool,
                vol.Required(
                    CONF_FLOW_SENSOR,
                    default=entry.options.get(
                        CONF_FLOW_SENSOR,
                        entry.data.get(CONF_FLOW_SENSOR, False),
                    ),
                ): bool,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=entry.options.get(
                        CONF_SCAN_INTERVAL,
                        entry.data.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL),
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_TIMEOUT,
                    default=entry.options.get(
                        CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                    ),
                ): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT)
                ),
                vol.Required(
                    CONF_FRAMING,
                    default=entry.options.get(
                        CONF_FRAMING, entry.data.get(CONF_FRAMING, DEFAULT_FRAMING)
                    ),
                ): _framing_selector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
