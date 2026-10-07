"""Sensor platform for the Pool Technologie integration."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_REGULATION_ORP, DOMAIN
from .entity import PoolEntity
from .models import MODELS

_LOGGER = logging.getLogger(__name__)

# Sensors that only make sense when an ORP probe is installed.
_ORP_SENSOR_KEYS = {"orp", "consigne_orp"}


async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    model_key = data["model"]
    model_label = MODELS[model_key]["name"]

    regulation_orp = config_entry.options.get(
        CONF_REGULATION_ORP, config_entry.data.get(CONF_REGULATION_ORP, False)
    )

    sensors = [
        PoolSensor(coordinator, config_entry.entry_id, model_label, sensor_conf)
        for sensor_conf in MODELS[model_key]["sensors"]
        if regulation_orp or sensor_conf.get("translation_key") not in _ORP_SENSOR_KEYS
    ]
    sensors.append(ModbusStatsSensor(coordinator, config_entry.entry_id, model_label))

    async_add_entities(sensors)


class PoolSensor(PoolEntity, SensorEntity, RestoreEntity):
    """Value sensor backed by a single Modbus register."""

    def __init__(self, coordinator, entry_id, model_label, config):
        super().__init__(coordinator, entry_id, model_label)
        self._config = config
        self._address = config["address"]
        self._scale = config.get("scale", 1)
        self._precision = config.get("precision", 0)

        self._attr_translation_key = config.get("translation_key")
        self._attr_icon = config.get("icon", "mdi:water")
        self._attr_native_unit_of_measurement = config.get("unit", "")
        # NOTE: deliberately NOT prefixed with entry_id. The original release
        # used the bare key, so changing it would orphan the existing entities
        # and their history.
        self._attr_unique_id = config["unique_id"]
        self._attr_device_class = config.get("device_class")
        if config.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._attr_native_value = None

    @property
    def extra_state_attributes(self):
        return {"modbus_address": self._address}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self):
        raw = self._raw(self._address)
        if raw is None:
            return self._attr_native_value

        value = round(raw * self._scale, self._precision)

        min_valid = self._config.get("min_valid")
        max_valid = self._config.get("max_valid")
        if (min_valid is not None and value < min_valid) or (
            max_valid is not None and value > max_valid
        ):
            _LOGGER.debug(
                "Out-of-range value ignored for %s: %s",
                self._config["unique_id"],
                value,
            )
            return self._attr_native_value

        self._attr_native_value = value
        return value


class ModbusStatsSensor(PoolEntity, SensorEntity):
    """Diagnostic counters for the Modbus link."""

    _attr_translation_key = "modbus_stats"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, entry_id, model_label):
        super().__init__(coordinator, entry_id, model_label)
        self._attr_unique_id = f"{entry_id}_modbus_stats"

    @property
    def available(self) -> bool:
        # Diagnostics must remain readable precisely when the link is down.
        return True

    @property
    def native_value(self):
        return self.coordinator.handler.last_error or "ok"

    @property
    def extra_state_attributes(self):
        handler = self.coordinator.handler
        return {
            "reads_ok": handler.reads_ok,
            "reads_failed": handler.reads_failed,
            "writes_ok": handler.writes_ok,
            "writes_failed": handler.writes_failed,
            "last_error": handler.last_error,
            "polled_addresses": list(self.coordinator.addresses),
        }
