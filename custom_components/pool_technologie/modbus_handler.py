"""Blocking pymodbus wrapper for Pool Technologie devices.

pymodbus's ModbusTcpClient is synchronous. Every method here is blocking and
must be called from an executor thread (hass.async_add_executor_job), never
directly from the HA event loop. The connection is kept open between calls and
a lock serializes access because every entity shares the same handler.
"""

import logging
import threading
import time

from pymodbus.client import ModbusTcpClient

from .const import (
    DEFAULT_FRAMING,
    FRAMING_RTU_OVER_TCP,
    RECONNECT_BACKOFF_INITIAL,
    RECONNECT_BACKOFF_MAX,
)

_LOGGER = logging.getLogger(__name__)

try:  # pymodbus >= 3.7 exposes FramerType
    from pymodbus import FramerType
except ImportError:  # pragma: no cover - older pymodbus
    FramerType = None

try:
    from pymodbus.exceptions import ModbusIOException
except ImportError:  # pragma: no cover - defensive
    # Empty tuple: isinstance() then never matches.
    ModbusIOException = ()


def _resolve_framer(framing: str):
    """Map the user-facing framing option to a pymodbus framer, or None."""
    if FramerType is None:
        return None
    if framing == FRAMING_RTU_OVER_TCP:
        # RTU over TCP: raw RTU frames carried by a TCP transport.
        return getattr(
            FramerType,
            "RTU_OVER_TCP",
            getattr(FramerType, "RTU", None),
        )
    return getattr(FramerType, "SOCKET", None)


class ModbusHandler:
    """Persistent, thread-safe Modbus TCP connection."""

    def __init__(
        self,
        host="192.168.1.100",
        port=502,
        unit_id=1,
        timeout=3,
        framing=DEFAULT_FRAMING,
    ):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.framing = framing

        kwargs = {
            "host": host,
            "port": port,
            "timeout": timeout,
            # No pymodbus-level retries: a dead device must cost a single
            # timeout per poll, not three.
            "retries": 0,
        }
        framer = _resolve_framer(framing)
        if framer is not None:
            kwargs["framer"] = framer

        self._client = ModbusTcpClient(**kwargs)
        self._lock = threading.Lock()

        # Reconnection backoff state.
        self._last_connect_attempt = 0.0
        self._connect_backoff = RECONNECT_BACKOFF_INITIAL

        # Diagnostics, surfaced by the Modbus stats sensor.
        self.reads_ok = 0
        self.reads_failed = 0
        self.writes_ok = 0
        self.writes_failed = 0
        self.last_error = None

    # -- connection management ------------------------------------------------

    def connect(self) -> bool:
        """Force a connection attempt (used by the config flow connection test)."""
        with self._lock:
            return self._ensure_connected(force=True)

    def close(self):
        with self._lock:
            try:
                self._client.close()
            except Exception:  # pragma: no cover - defensive
                pass

    def _ensure_connected(self, force: bool = False) -> bool:
        """Ensure the socket is open.

        Must be called while holding self._lock. Returns True when a usable
        connection is believed to be available. Reconnection attempts are
        rate-limited with an exponential backoff so that a dead gateway cannot
        make every read wait for the full connect timeout.
        """
        if self._client.connected:
            return True

        now = time.monotonic()
        if not force and (now - self._last_connect_attempt) < self._connect_backoff:
            # Still in backoff: fail fast instead of blocking on connect().
            return False

        self._last_connect_attempt = now
        # Drop any half-open socket before reconnecting.
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass

        try:
            connected = self._client.connect()
        except Exception as err:
            self.last_error = str(err)
            _LOGGER.debug("Modbus connect exception: %s", err)
            connected = False

        if connected:
            self._connect_backoff = RECONNECT_BACKOFF_INITIAL
            self.last_error = None
            _LOGGER.info(
                "Connected to Modbus device %s:%s (unit %s)",
                self.host,
                self.port,
                self.unit_id,
            )
            return True

        self._connect_backoff = min(self._connect_backoff * 2, RECONNECT_BACKOFF_MAX)
        self.last_error = "connect failed"
        _LOGGER.debug(
            "Modbus connect to %s:%s failed, next attempt in %ss",
            self.host,
            self.port,
            self._connect_backoff,
        )
        return False

    # -- reads ----------------------------------------------------------------

    def read_register(self, address, count=1):
        """Read `count` holding registers starting at `address`.

        Returns a list of ints, or None on any failure.
        """
        with self._lock:
            if not self._ensure_connected():
                self.reads_failed += 1
                return None
            try:
                result = self._client.read_holding_registers(
                    address=address, count=count, device_id=self.unit_id
                )
                if result.isError():
                    self.last_error = str(result)
                    self.reads_failed += 1
                    _LOGGER.debug("Modbus read error at %s: %s", address, result)
                    if isinstance(result, ModbusIOException):
                        # No response / transport error: the socket is likely
                        # half-open. Close it so the next attempt goes through
                        # the reconnect backoff instead of timing out again.
                        self._drop_connection()
                    return None
                self.reads_ok += 1
                return result.registers
            except Exception as err:
                self.last_error = str(err)
                self.reads_failed += 1
                self._drop_connection()
                _LOGGER.debug("Modbus read exception at %s: %s", address, err)
                return None

    def read_registers_batch(self, addresses):
        """Read many registers, grouping contiguous addresses into single requests.

        Returns a dict mapping address -> raw register value for the addresses
        that could be read. If the very first request fails, polling is aborted
        so a dead device costs a single timeout instead of one per group.
        """
        ordered = sorted(set(addresses))
        if not ordered:
            return {}

        groups = []
        start = prev = ordered[0]
        for address in ordered[1:]:
            if address == prev + 1:
                prev = address
            else:
                groups.append((start, prev))
                start = prev = address
        groups.append((start, prev))

        values = {}
        for index, (first, last) in enumerate(groups):
            registers = self.read_register(first, count=last - first + 1)
            if registers is None:
                if index == 0 and not values:
                    # First request failed: the device is very likely down.
                    break
                continue
            for offset, value in enumerate(registers):
                values[first + offset] = value
        return values

    # -- writes ---------------------------------------------------------------

    def write_register(self, address, value):
        with self._lock:
            if not self._ensure_connected():
                self.writes_failed += 1
                return False
            try:
                result = self._client.write_register(
                    address=address, value=value, device_id=self.unit_id
                )
                if result.isError():
                    self.last_error = str(result)
                    self.writes_failed += 1
                    _LOGGER.debug("Modbus write error at %s: %s", address, result)
                    if isinstance(result, ModbusIOException):
                        self._drop_connection()
                    return False
                self.writes_ok += 1
                return True
            except Exception as err:
                self.last_error = str(err)
                self.writes_failed += 1
                self._drop_connection()
                _LOGGER.debug("Modbus write exception at %s: %s", address, err)
                return False

    def write_registers(self, address, values):
        with self._lock:
            if not self._ensure_connected():
                self.writes_failed += 1
                return False
            try:
                result = self._client.write_registers(
                    address=address, values=values, device_id=self.unit_id
                )
                if result.isError():
                    self.last_error = str(result)
                    self.writes_failed += 1
                    _LOGGER.debug("Modbus write error at %s: %s", address, result)
                    if isinstance(result, ModbusIOException):
                        self._drop_connection()
                    return False
                self.writes_ok += 1
                return True
            except Exception as err:
                self.last_error = str(err)
                self.writes_failed += 1
                self._drop_connection()
                _LOGGER.debug("Modbus write exception at %s: %s", address, err)
                return False

    def read_register_verified(self, address, expected_value, count=1, tolerance=0):
        """Read a register back after a write to confirm it was applied.

        Runs as a separate locked operation from the write itself, so call it
        after write_register/write_registers, with a short delay if the device
        needs time to process the write.
        """
        result = self.read_register(address, count=count)
        if result is None:
            return False
        return abs(result[0] - expected_value) <= tolerance

    # -- internals ------------------------------------------------------------

    def _drop_connection(self):
        """Close a socket that is in an unknown state. Caller must hold the lock."""
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass
