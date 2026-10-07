"""Constants for the Pool Technologie integration."""

DOMAIN = "pool_technologie"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_MODEL = "model"
CONF_REGULATION_ORP = "regulation_orp"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_FRAMING = "framing"
CONF_IGNORE_CONNECTION_ERROR = "ignore_connection_error"
CONF_FLOW_SENSOR = "flow_sensor"

# Defaults
SCAN_INTERVAL = 60
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_TIMEOUT = 3
DEFAULT_FRAMING = "tcp"

# Framing options (Modbus over TCP)
FRAMING_TCP = "tcp"  # MBAP header, standard Modbus TCP
FRAMING_RTU_OVER_TCP = "rtuovertcp"  # raw RTU frames over TCP, used by some RS485 gateways

# Validation bounds
MIN_PORT = 1
MAX_PORT = 65535
MIN_UNIT_ID = 1
MAX_UNIT_ID = 247
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 3600
MIN_TIMEOUT = 1
MAX_TIMEOUT = 30

# Reconnection backoff, in seconds
RECONNECT_BACKOFF_INITIAL = 1
RECONNECT_BACKOFF_MAX = 60

# Minimum delay between two user-initiated writes to the same entity, in seconds
WRITE_THROTTLE_SECONDS = 1
# Delay granted to the device to apply a write before it is read back, in seconds
WRITE_VERIFY_DELAY = 0.5
