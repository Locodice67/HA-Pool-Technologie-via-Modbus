"""Set up the Pool Technologie integration."""

import logging

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_FLOW_SENSOR,
    CONF_FRAMING,
    CONF_REGULATION_ORP,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_FRAMING,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SCAN_INTERVAL,
)
from .coordinator import PoolDataCoordinator
from .modbus_handler import ModbusHandler
from .registers import build_polled_addresses

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]

SERVICE_READ_REGISTER = "read_register"
ATTR_ADDRESS = "address"
ATTR_COUNT = "count"
ATTR_ENTRY_ID = "entry_id"

SERVICE_READ_REGISTER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ADDRESS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=65535)
        ),
        vol.Optional(ATTR_COUNT, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=125)
        ),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def async_setup_entry(hass, entry):
    hass.data.setdefault(DOMAIN, {})
    data = dict(entry.data)

    handler = ModbusHandler(
        host=data["host"],
        port=data["port"],
        unit_id=data["unit_id"],
        timeout=entry.options.get(
            CONF_TIMEOUT, data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        ),
        framing=entry.options.get(
            CONF_FRAMING, data.get(CONF_FRAMING, DEFAULT_FRAMING)
        ),
    )

    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)
    )
    regulation_orp = entry.options.get(
        CONF_REGULATION_ORP, data.get(CONF_REGULATION_ORP, False)
    )
    flow_sensor = entry.options.get(
        CONF_FLOW_SENSOR, data.get(CONF_FLOW_SENSOR, False)
    )

    coordinator = PoolDataCoordinator(
        hass,
        handler,
        scan_interval,
        build_polled_addresses(data["model"], regulation_orp, flow_sensor),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "handler": handler,
        "coordinator": coordinator,
        "model": data["model"],
        "scan_interval": scan_interval,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # First poll in the background: never block config-entry setup, and never
    # let an unreachable device delay Home Assistant startup.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN}_initial_poll"
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await _async_setup_services(hass)
    return True


async def _async_update_listener(hass, entry):
    """Reload the integration when its options change (e.g. ORP regulation)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data is not None:
            await hass.async_add_executor_job(data["handler"].close)
    return unloaded


async def _async_setup_services(hass):
    if hass.services.has_service(DOMAIN, SERVICE_READ_REGISTER):
        return

    async def _async_read_register(call: ServiceCall) -> dict:
        address = call.data[ATTR_ADDRESS]
        count = call.data[ATTR_COUNT]
        entry_id = call.data.get(ATTR_ENTRY_ID)

        entries = hass.data.get(DOMAIN, {})
        device = entries.get(entry_id) if entry_id else next(iter(entries.values()), None)
        if device is None:
            return {"success": False, "error": "no_configured_device"}

        registers = await hass.async_add_executor_job(
            device["handler"].read_register, address, count
        )
        if registers is None:
            return {"success": False, "error": "read_failed", "address": address}
        return {"success": True, "address": address, "registers": registers}

    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTER,
        _async_read_register,
        schema=SERVICE_READ_REGISTER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
