"""Shared entity base classes for the Pool Technologie integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolDataCoordinator


class PoolEntity(CoordinatorEntity[PoolDataCoordinator]):
    """Base entity bound to the shared coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, entry_id, model_label):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._model_label = model_label

    @property
    def available(self) -> bool:
        # CoordinatorEntity already checks last_update_success; also require at
        # least one successful read so a failed first poll is unavailable.
        return self.coordinator.data is not None and super().available

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": self._model_label,
            "manufacturer": "Pool Technologie",
            "model": self._model_label,
        }

    def _raw(self, address):
        """Return the raw value of a register, or None if not available."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(address)
