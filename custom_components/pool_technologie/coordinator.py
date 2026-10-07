"""DataUpdateCoordinator for the Pool Technologie integration."""

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PoolDataCoordinator(DataUpdateCoordinator[dict[int, int]]):
    """Poll the Modbus device once per interval and share the result.

    All entities read their value from `coordinator.data`, a mapping of
    register address -> raw value. When the device is unreachable the update
    fails and Home Assistant marks every entity as unavailable instead of
    leaving stale values behind.
    """

    def __init__(self, hass, handler, scan_interval, addresses):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.handler = handler
        self.addresses = tuple(addresses)

    async def _async_update_data(self) -> dict[int, int]:
        try:
            return await self.hass.async_add_executor_job(self._read_all)
        except UpdateFailed:
            raise
        except Exception as err:  # pragma: no cover - defensive
            raise UpdateFailed(f"Unexpected Modbus error: {err}") from err

    def _read_all(self) -> dict[int, int]:
        values = self.handler.read_registers_batch(self.addresses)
        if not values:
            raise UpdateFailed("No response from Modbus device")
        if len(values) < len(self.addresses):
            _LOGGER.debug(
                "Partial Modbus read: %d/%d registers",
                len(values),
                len(self.addresses),
            )
        return values
