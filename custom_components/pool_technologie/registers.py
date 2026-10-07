"""Central registry of the Modbus registers used by the integration.

Keeping every address in one place avoids the previous situation where the
same register (for example the ORP setpoint) was hard-coded in several entity
files, and lets the coordinator know exactly what to poll.
"""

# Holding registers
REG_PH = 259
REG_TEMPERATURE = 260
REG_SALT = 261
REG_ORP = 262
REG_CELL_VOLTAGE = 1061
REG_POOL_SIZE = 4111
REG_ELECTROLYSIS_SETPOINT = 4168
REG_CELL_INVERSION_HOURS = 4170
REG_PRODUCTION = 4171
REG_ALARMS = 4172
REG_BOOST_FLAG = 4182
REG_BOOST_DURATION = 4188
REG_PH_AUTO = 4200
REG_PH_SETPOINT = 4207
REG_PH_CORRECTOR = 4208
REG_ORP_SETPOINT = 4235
REG_CELL_HOURS = 4463
# Alarm of the configurable safety input (flow sensor OR tank/level float).
# Measured on a Just Salt Pro (2026-10-01): the input alarm sets bit 0x20 of
# register 4600 (mirrored on 4592). The previously documented address 4604
# stayed at 0 for the whole alarm and is not used on this model.
REG_WATER_FLOW_ALARM = 4600
FLOW_ALARM_BITMASK = 0x0020


def build_polled_addresses(
    model: str, regulation_orp: bool, flow_sensor: bool = False
) -> tuple[int, ...]:
    """Return every register that must be polled for a given configuration.

    Only registers that exist on the selected model are polled, so the
    coordinator never sends requests for unsupported registers.
    """
    # Imported lazily to avoid a circular import at module load time.
    from .models import MODELS

    info = MODELS[model]
    addresses = {
        REG_PH,
        REG_TEMPERATURE,
        REG_SALT,
        REG_PH_SETPOINT,
        REG_PH_CORRECTOR,
        REG_POOL_SIZE,
        REG_BOOST_DURATION,
        REG_PH_AUTO,
    }

    if regulation_orp:
        addresses.add(REG_ORP)
        addresses.add(REG_ORP_SETPOINT)

    if info.get("supports_cell_diagnostics"):
        addresses.update(
            {
                REG_CELL_VOLTAGE,
                REG_CELL_HOURS,
                REG_PRODUCTION,
                REG_ALARMS,
                REG_CELL_INVERSION_HOURS,
            }
        )

    if info.get("supports_electrolysis_setpoint") and not regulation_orp:
        addresses.add(REG_ELECTROLYSIS_SETPOINT)

    if flow_sensor:
        addresses.add(REG_WATER_FLOW_ALARM)

    return tuple(sorted(addresses))
