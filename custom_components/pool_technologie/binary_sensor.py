"""Binary sensor platform for the Pool Technologie integration."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import CONF_FLOW_SENSOR, DOMAIN
from .entity import PoolEntity
from .models import MODELS
from .registers import (
    FLOW_ALARM_BITMASK,
    REG_ALARMS,
    REG_PRODUCTION,
    REG_WATER_FLOW_ALARM,
)

# Electrolyser alarms, read from register 4172 (bitmask), per issue #4 (RACER
# electrolyser). Bits are not confirmed on the other models.
_CELL_ALARMS = (
    {
        "translation_key": "alarme_defaut_cellule",
        "unique_id": "alarme_defaut_cellule",
        "address": REG_ALARMS,
        "bitmask": 0x0002,
        "icon": "mdi:alert-circle",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_manque_sel",
        "unique_id": "alarme_manque_sel",
        "address": REG_ALARMS,
        "bitmask": 0x0004,
        "icon": "mdi:shaker-outline",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_trop_sel",
        "unique_id": "alarme_trop_sel",
        "address": REG_ALARMS,
        "bitmask": 0x0008,
        "icon": "mdi:shaker-outline",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_eau_froide",
        "unique_id": "alarme_eau_froide",
        "address": REG_ALARMS,
        "bitmask": 0x0010,
        "icon": "mdi:snowflake-alert",
        "device_class": "problem",
    },
)

# Alarm of the configurable safety input (flow sensor OR tank/level float).
# On this hardware the alarm is bit 0x20 of register 4600 (0 = OK), not the
# documented 4604 which stayed at 0 during the whole alarm (measured 2026-10-01).
_FLOW_ALARM = {
    "translation_key": "alarme_debit_eau",
    "unique_id": "alarme_debit_eau",
    "address": REG_WATER_FLOW_ALARM,
    "bitmask": FLOW_ALARM_BITMASK,
    "icon": "mdi:water-off",
    "device_class": "problem",
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    model_key = data["model"]
    model_label = MODELS[model_key]["name"]
    entry_id = config_entry.entry_id

    entities = [ModbusStatusSensor(coordinator, entry_id, model_label)]

    flow_sensor = config_entry.options.get(
        CONF_FLOW_SENSOR, config_entry.data.get(CONF_FLOW_SENSOR, False)
    )

    if MODELS[model_key].get("supports_cell_diagnostics"):
        # Operating mode (register 4171): 0 = off/standby, non-zero = producing.
        entities.append(
            PoolRegisterBinarySensor(
                coordinator,
                entry_id,
                model_label,
                {
                    "translation_key": "production_active",
                    "unique_id": "production_active",
                    "address": REG_PRODUCTION,
                    "nonzero": True,
                    "icon": "mdi:play-circle",
                },
            )
        )
        entities.extend(
            PoolRegisterBinarySensor(coordinator, entry_id, model_label, alarm)
            for alarm in _CELL_ALARMS
        )

    # Only created when the optional water-flow sensor is installed.
    if flow_sensor:
        entities.append(
            PoolRegisterBinarySensor(coordinator, entry_id, model_label, _FLOW_ALARM)
        )

    async_add_entities(entities)


class ModbusStatusSensor(PoolEntity, BinarySensorEntity):
    """Reports whether the last Modbus poll succeeded."""

    _attr_translation_key = "modbus_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator, entry_id, model_label):
        super().__init__(coordinator, entry_id, model_label)
        self._attr_unique_id = f"{entry_id}_modbus_status"

    @property
    def available(self) -> bool:
        # The connectivity status must stay visible even when the device is down.
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class PoolRegisterBinarySensor(PoolEntity, BinarySensorEntity):
    """Binary sensor derived from a Modbus register (bitmask or non-zero)."""

    def __init__(self, coordinator, entry_id, model_label, config):
        super().__init__(coordinator, entry_id, model_label)
        self._config = config
        self._address = config["address"]
        self._bitmask = config.get("bitmask")
        self._nonzero = config.get("nonzero", False)

        self._attr_translation_key = config["translation_key"]
        self._attr_unique_id = f"{entry_id}_{config['unique_id']}"
        self._attr_icon = config.get("icon")
        if config.get("device_class") == "problem":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_is_on = False

    @property
    def extra_state_attributes(self):
        return {"modbus_address": self._address}

    @property
    def is_on(self) -> bool:
        raw = self._raw(self._address)
        if raw is None:
            return self._attr_is_on

        if self._bitmask is not None:
            value = bool(raw & self._bitmask)
        elif self._nonzero:
            value = raw != 0
        else:
            value = bool(raw)

        self._attr_is_on = value
        return value
