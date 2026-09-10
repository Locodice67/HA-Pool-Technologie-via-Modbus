from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from .const import DOMAIN
from .models import MODELS

# Alarmes de l'électrolyseur, lues sur le registre 4172 (bitmask), d'après l'issue #4
# (électrolyseur RACER). Bits non confirmés sur les autres modèles.
_CELL_ALARMS = [
    {
        "translation_key": "alarme_defaut_cellule",
        "unique_id": "alarme_defaut_cellule",
        "address": 4172,
        "bitmask": 0x0002,
        "icon": "mdi:alert-circle",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_manque_sel",
        "unique_id": "alarme_manque_sel",
        "address": 4172,
        "bitmask": 0x0004,
        "icon": "mdi:shaker-outline",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_trop_sel",
        "unique_id": "alarme_trop_sel",
        "address": 4172,
        "bitmask": 0x0008,
        "icon": "mdi:shaker-outline",
        "device_class": "problem",
    },
    {
        "translation_key": "alarme_eau_froide",
        "unique_id": "alarme_eau_froide",
        "address": 4172,
        "bitmask": 0x0010,
        "icon": "mdi:snowflake-alert",
        "device_class": "problem",
    },
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    model_key = config_entry.data["model"]
    model_label = MODELS[model_key]["name"]
    handler = controller.handler
    entry_id = config_entry.entry_id

    entities = [ModbusStatusSensor(entry_id, model_label, controller)]

    if MODELS[model_key].get("supports_cell_diagnostics"):
        # Mode de fonctionnement (registre 4171) : 0 = arrêt/veille, non nul = production.
        entities.append(
            PoolRegisterBinarySensor(
                hass, handler, controller, entry_id, model_label,
                {
                    "translation_key": "production_active",
                    "unique_id": "production_active",
                    "address": 4171,
                    "nonzero": True,
                    "icon": "mdi:play-circle",
                },
            )
        )
        for alarm in _CELL_ALARMS:
            entities.append(
                PoolRegisterBinarySensor(hass, handler, controller, entry_id, model_label, alarm)
            )

    async_add_entities(entities)


class ModbusStatusSensor(BinarySensorEntity):
    def __init__(self, entry_id, model_label, controller):
        self._entry_id = entry_id
        self._model_label = model_label
        self._controller = controller

        self._attr_has_entity_name = True
        self._attr_translation_key = "modbus_status"
        self._attr_unique_id = f"{entry_id}_modbus_status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:lan-connect"
        self._attr_is_on = controller.modbus_ok

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": self._model_label,
            "manufacturer": "Pool Technologie",
            "model": self._model_label,
        }

    async def async_update(self):
        self._attr_is_on = self._controller.modbus_ok


class PoolRegisterBinarySensor(BinarySensorEntity):
    """Binary sensor dérivé d'un registre Modbus (bitmask ou valeur non nulle)."""

    _attr_should_poll = False

    def __init__(self, hass, handler, controller, entry_id, model_label, config):
        self._hass = hass
        self._handler = handler
        self._controller = controller
        self._entry_id = entry_id
        self._model_label = model_label
        self._config = config
        self._address = config["address"]
        self._bitmask = config.get("bitmask")
        self._nonzero = config.get("nonzero", False)

        self._attr_has_entity_name = True
        self._attr_translation_key = config["translation_key"]
        self._attr_unique_id = f"{entry_id}_{config['unique_id']}"
        self._attr_icon = config.get("icon")
        if config.get("device_class") == "problem":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_is_on = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": self._model_label,
            "manufacturer": "Pool Technologie",
            "model": self._model_label,
        }

    @property
    def extra_state_attributes(self):
        return {"modbus_address": self._address}

    async def async_added_to_hass(self):
        await self._async_poll_refresh()
        self._controller.add_poll_listener(self._async_poll_refresh)

    async def async_will_remove_from_hass(self):
        self._controller.remove_poll_listener(self._async_poll_refresh)

    async def _async_poll_refresh(self) -> bool:
        result = await self._hass.async_add_executor_job(self._handler.read_register, self._address)
        if result is None:
            return False
        raw = int(result[0])
        if self._bitmask is not None:
            self._attr_is_on = bool(raw & self._bitmask)
        elif self._nonzero:
            self._attr_is_on = raw != 0
        else:
            self._attr_is_on = bool(raw)
        self.async_write_ha_state()
        return True
