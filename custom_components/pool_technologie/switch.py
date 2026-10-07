"""Switch platform for the Pool Technologie integration."""

import asyncio
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, WRITE_THROTTLE_SECONDS, WRITE_VERIFY_DELAY
from .entity import PoolEntity
from .models import MODELS
from .registers import REG_BOOST_DURATION, REG_BOOST_FLAG, REG_PH_AUTO

_BOOST_DURATION_MINUTES = 1440  # 24 hours

# Each switch describes the register used to read its state and the write
# sequence applied to turn it on or off.
SWITCH_CONFIGS = (
    {
        "translation_key": "boost",
        "unique_id": "boost",
        "icon": "mdi:rocket-launch",
        "read_address": REG_BOOST_DURATION,
        "on": ((REG_BOOST_DURATION, _BOOST_DURATION_MINUTES), (REG_BOOST_FLAG, 256)),
        "off": ((REG_BOOST_DURATION, 0),),
        "verify_on": _BOOST_DURATION_MINUTES,
        "verify_off": 0,
        "extra_attributes": {
            "modbus_address": REG_BOOST_DURATION,
            "modbus_flag_address": REG_BOOST_FLAG,
        },
    },
    {
        "translation_key": "ph_auto",
        "unique_id": "ph_auto",
        "icon": "mdi:tune",
        "read_address": REG_PH_AUTO,
        "on": ((REG_PH_AUTO, 1),),
        "off": ((REG_PH_AUTO, 0),),
        "verify_on": 1,
        "verify_off": 0,
        "extra_attributes": {"modbus_address": REG_PH_AUTO},
    },
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    model_label = MODELS[data["model"]]["name"]

    async_add_entities(
        [
            PoolSwitchEntity(coordinator, config_entry.entry_id, model_label, config)
            for config in SWITCH_CONFIGS
        ]
    )


class PoolSwitchEntity(PoolEntity, SwitchEntity):
    """Config-driven switch backed by Modbus registers."""

    def __init__(self, coordinator, entry_id, model_label, config):
        super().__init__(coordinator, entry_id, model_label)
        self._config = config
        self._read_address = config["read_address"]
        self._last_write = 0.0

        self._attr_translation_key = config["translation_key"]
        self._attr_unique_id = f"{entry_id}_{config['unique_id']}"
        self._attr_icon = config.get("icon")
        self._attr_is_on = False

    @property
    def extra_state_attributes(self):
        return dict(self._config.get("extra_attributes", {}))

    @property
    def is_on(self) -> bool:
        raw = self._raw(self._read_address)
        if raw is None:
            return self._attr_is_on
        self._attr_is_on = raw > 0
        return self._attr_is_on

    async def _apply(self, operations, verify_value):
        now = time.monotonic()
        if now - self._last_write < WRITE_THROTTLE_SECONDS:
            raise HomeAssistantError(
                f"Switch write throttled: another write was issued less than "
                f"{WRITE_THROTTLE_SECONDS}s ago"
            )
        self._last_write = now

        handler = self.coordinator.handler
        for address, value in operations:
            if not await self.hass.async_add_executor_job(
                handler.write_register, address, value
            ):
                raise HomeAssistantError(f"Failed to write register {address}")

        await asyncio.sleep(WRITE_VERIFY_DELAY)
        verified = await self.hass.async_add_executor_job(
            handler.read_register_verified, self._read_address, verify_value
        )
        if not verified:
            raise HomeAssistantError(
                f"Switch state not confirmed by the device (register "
                f"{self._read_address})"
            )

        self._attr_is_on = verify_value > 0
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        await self._apply(self._config["on"], self._config["verify_on"])

    async def async_turn_off(self, **kwargs):
        await self._apply(self._config["off"], self._config["verify_off"])
