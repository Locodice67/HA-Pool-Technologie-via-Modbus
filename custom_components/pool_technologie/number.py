"""Number platform for the Pool Technologie integration."""

import asyncio
import time

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfElectricPotential
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_REGULATION_ORP,
    DOMAIN,
    WRITE_THROTTLE_SECONDS,
    WRITE_VERIFY_DELAY,
)
from .entity import PoolEntity
from .models import MODELS
from .registers import (
    REG_CELL_INVERSION_HOURS,
    REG_ELECTROLYSIS_SETPOINT,
    REG_ORP_SETPOINT,
    REG_PH_CORRECTOR,
    REG_PH_SETPOINT,
    REG_POOL_SIZE,
)

# `requires` selects when an entity is created:
#   "orp"              -> ORP regulation enabled
#   "electrolysis"     -> model exposes an electrolysis setpoint, manual mode only
#   "cell_diagnostics" -> model supports cell diagnostics
NUMBER_CONFIGS = (
    {
        "translation_key": "consigne_ph",
        "unique_id": "consigne_ph",
        "address": REG_PH_SETPOINT,
        "unit": "pH",
        "icon": "mdi:cog",
        "min": 6.0,
        "max": 8.5,
        "step": 0.1,
        "default": 7.2,
        "scale": 0.000390625,
        "precision": 2,
        "tolerance": 1,
    },
    {
        "translation_key": "consigne_orp",
        "unique_id": "consigne_orp",
        "address": REG_ORP_SETPOINT,
        "unit": UnitOfElectricPotential.MILLIVOLT,
        "icon": "mdi:cog",
        "min": 400,
        "max": 900,
        "step": 10,
        "default": 650,
        "requires": "orp",
    },
    {
        "translation_key": "consigne_electrolyse",
        "unique_id": "consigne_electrolyse",
        "address": REG_ELECTROLYSIS_SETPOINT,
        "unit": "%",
        "icon": "mdi:cog",
        "min": 10,
        "max": 100,
        "step": 1,
        "default": 20,
        "requires": "electrolysis",
    },
    {
        "translation_key": "concentration_correcteur_ph",
        "unique_id": "concentration_correcteur_ph",
        "address": REG_PH_CORRECTOR,
        "unit": "%",
        "icon": "mdi:flask-outline",
        "min": 5,
        "max": 50,
        "step": 1,
        "default": 15,
        "precision": 1,
    },
    {
        "translation_key": "taille_bassin",
        "unique_id": "taille_bassin",
        "address": REG_POOL_SIZE,
        "unit": "m³",
        "icon": "mdi:texture-box",
        "min": 1,
        "max": 250,
        "step": 1,
        "default": 30,
    },
    {
        "translation_key": "heure_inversion_cellule",
        "unique_id": "heure_inversion_cellule",
        "address": REG_CELL_INVERSION_HOURS,
        "unit": "h",
        "icon": "mdi:swap-horizontal",
        "min": 1,
        "max": 24,
        "step": 1,
        "default": 4,
        "requires": "cell_diagnostics",
    },
)


def _is_required(config, model_info, regulation_orp) -> bool:
    requires = config.get("requires")
    if requires == "orp":
        return regulation_orp
    if requires == "electrolysis":
        return (
            bool(model_info.get("supports_electrolysis_setpoint"))
            and not regulation_orp
        )
    if requires == "cell_diagnostics":
        return bool(model_info.get("supports_cell_diagnostics"))
    return True


async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    model_key = data["model"]
    model_label = MODELS[model_key]["name"]
    model_info = MODELS[model_key]

    regulation_orp = config_entry.options.get(
        CONF_REGULATION_ORP, config_entry.data.get(CONF_REGULATION_ORP, False)
    )

    entities = [
        PoolNumberEntity(coordinator, config_entry.entry_id, model_label, config)
        for config in NUMBER_CONFIGS
        if _is_required(config, model_info, regulation_orp)
    ]
    async_add_entities(entities)


class PoolNumberEntity(PoolEntity, NumberEntity):
    """Config-driven number entity with write verification and throttling."""

    _attr_mode = "box"

    def __init__(self, coordinator, entry_id, model_label, config):
        super().__init__(coordinator, entry_id, model_label)
        self._config = config
        self._address = config["address"]
        self._scale = config.get("scale", 1)
        self._precision = config.get("precision", 0)
        self._tolerance = config.get("tolerance", 0)
        self._last_write = 0.0

        self._attr_translation_key = config["translation_key"]
        self._attr_unique_id = f"{entry_id}_{config['unique_id']}"
        self._attr_icon = config.get("icon", "mdi:cog")
        self._attr_native_unit_of_measurement = config.get("unit")
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = config.get("step", 1)
        self._attr_native_value = config.get("default")

    @property
    def extra_state_attributes(self):
        return {"modbus_address": self._address}

    @property
    def native_value(self):
        raw = self._raw(self._address)
        if raw is None:
            return self._attr_native_value

        value = round(raw * self._scale, self._precision)
        # Out-of-range value (device off, or an aberrant read): keep the last
        # known good value instead of showing nonsense.
        if not (self._attr_native_min_value <= value <= self._attr_native_max_value):
            return self._attr_native_value

        self._attr_native_value = value
        return value

    def _encode(self, value):
        return int(round(value / self._scale))

    async def async_set_native_value(self, value: float) -> None:
        now = time.monotonic()
        if now - self._last_write < WRITE_THROTTLE_SECONDS:
            raise HomeAssistantError(
                f"Write to register {self._address} throttled: another write "
                f"was issued less than {WRITE_THROTTLE_SECONDS}s ago"
            )
        self._last_write = now

        raw = self._encode(value)
        handler = self.coordinator.handler

        if not await self.hass.async_add_executor_job(
            handler.write_register, self._address, raw
        ):
            raise HomeAssistantError(
                f"Failed to write register {self._address} (raw={raw})"
            )

        await asyncio.sleep(WRITE_VERIFY_DELAY)
        verified = await self.hass.async_add_executor_job(
            handler.read_register_verified, self._address, raw, 1, self._tolerance
        )
        if not verified:
            raise HomeAssistantError(
                f"Register {self._address} not confirmed by the device after "
                f"write (raw={raw})"
            )

        self._attr_native_value = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
