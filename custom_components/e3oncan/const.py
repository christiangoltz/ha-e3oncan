"""Constants for the E3onCAN integration."""

DOMAIN = "e3oncan"

CONF_CAN_INTERFACE = "can_interface"
CONF_DEVICE = "device"
CONF_CAN_ID = "can_id"
CONF_MIN_INTERVAL = "min_interval"

DEFAULT_CAN_INTERFACE = "can0"
DEFAULT_MIN_INTERVAL = 10  # seconds between updates of the same data point

DEVICE_VX3 = "vx3"
DEVICE_VCAL = "vcal"
DEVICE_VAIR = "vair"
DEVICE_VDENS = "vdens"
DEVICE_E380 = "e380"
DEVICE_E3100CB = "e3100cb"
DEVICE_SCAN = "scan"
DEVICE_VCAL_READ = "vcal_read"
DEVICE_VAIR_READ = "vair_read"

DEVICES = [
    DEVICE_VX3,
    DEVICE_VCAL_READ,
    DEVICE_VAIR_READ,
    DEVICE_VCAL,
    DEVICE_VAIR,
    DEVICE_VDENS,
    DEVICE_E380,
    DEVICE_E3100CB,
    DEVICE_SCAN,
]

DEVICE_NAMES = {
    DEVICE_VX3: "Vitocharge VX3",
    DEVICE_VCAL: "Vitocal",
    DEVICE_VAIR: "Vitoair",
    DEVICE_VDENS: "Vitodens",
    DEVICE_E380: "Energy meter E380",
    DEVICE_E3100CB: "Energy meter E3100CB",
    DEVICE_SCAN: "E3 bus scan",
    DEVICE_VCAL_READ: "Vitocal",
    DEVICE_VAIR_READ: "Vitoair",
}

# CAN IDs the devices broadcast their "Collect" data on (from E3onCAN).
E3_DEFAULT_CAN_ID = {
    DEVICE_VX3: 0x451,
    DEVICE_VAIR: 0x451,
    DEVICE_VDENS: 0x451,
    DEVICE_VCAL: 0x693,
}
# Read mode: (default ECU request ID, decoder tables) per device type.
READ_DEVICES = {
    DEVICE_VCAL_READ: (0x680, DEVICE_VCAL),
    DEVICE_VAIR_READ: (0x6A2, DEVICE_VAIR),
}

# Value open3e devices report for "sensor not connected".
UNAVAILABLE_VALUES = (-3276.8,)

E380_CAN_IDS = list(range(0x250, 0x25E))
E3100CB_CAN_ID = 0x569

SIGNAL_NEW_VALUES = f"{DOMAIN}_new_values_{{entry_id}}"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{entry_id}}"

# Data points that never become entities (pure bus bookkeeping).
IGNORED_DID_NAME_PARTS = ("BusTopology",)
