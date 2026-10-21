"""Sensors for values decoded from the CAN bus.

Entities are created as data points arrive. Entities known from earlier runs
are restored from the entity registry at startup, so they keep their history
and show as unavailable until the device broadcasts them again.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import E3ConfigEntry
from .const import DEVICE_NAMES, DOMAIN
from .decoder import ValueInfo, parse_key
from .hub import E3Hub

DIAG_FRAMES = "diag_frames"
DIAG_UNKNOWN = "diag_unknown"

_UNIT_FIXES = {"l/h": "L/h", "VAr": "var"}

# unit -> (device class, state class)
_UNIT_CLASSES: dict[str, tuple[SensorDeviceClass | None, SensorStateClass | None]] = {
    "°C": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    "K": (None, SensorStateClass.MEASUREMENT),
    "W": (SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    "kW": (SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    "VA": (SensorDeviceClass.APPARENT_POWER, SensorStateClass.MEASUREMENT),
    "var": (SensorDeviceClass.REACTIVE_POWER, SensorStateClass.MEASUREMENT),
    "V": (SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT),
    "A": (SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT),
    "Hz": (SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT),
    "bar": (SensorDeviceClass.PRESSURE, SensorStateClass.MEASUREMENT),
    "L/h": (SensorDeviceClass.VOLUME_FLOW_RATE, SensorStateClass.MEASUREMENT),
    "m³/h": (SensorDeviceClass.VOLUME_FLOW_RATE, SensorStateClass.MEASUREMENT),
    "h": (SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING),
    "min": (SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
    "s": (SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
    "%": (None, SensorStateClass.MEASUREMENT),
}
_ENERGY_UNITS = {"Wh", "kWh", "MWh"}
_STORAGE_WORDS = ("StateOf", "Capacity", "Remaining")


def _classes(info: ValueInfo, unit: str | None) -> tuple[SensorDeviceClass | None, SensorStateClass | None]:
    if unit is None:
        return None, None
    name = f"{info.did_name}/{'/'.join(info.path)}"
    if unit in _ENERGY_UNITS:
        if any(word in name for word in _STORAGE_WORDS):
            return SensorDeviceClass.ENERGY_STORAGE, SensorStateClass.MEASUREMENT
        return SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING
    if unit == "%" and ("StateOfCharge" in name or "SoC" in name):
        return SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT
    return _UNIT_CLASSES.get(unit, (None, SensorStateClass.MEASUREMENT))


def _words(text: str) -> str:
    """'ElectricalEnergyStorageStateOfEnergy' -> 'Electrical Energy Storage State Of Energy'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).replace("_", " ").strip()


def _entity_name(info: ValueInfo) -> str:
    parts = [_words(info.did_name)]
    parts.extend(_words(p) for p in info.path)
    return " ".join(p for p in parts if p)


def _enabled_by_default(info: ValueInfo) -> bool:
    if info.raw:
        return False
    if any(p.lower().startswith("unknown") for p in info.path):
        return False
    if info.did_name.lower().startswith("unknown"):
        return False
    # enum values come as {"ID": n, "Text": "..."}; the text is enough
    return not (info.path and info.path[-1] == "ID")


def device_info(hub: E3Hub) -> DeviceInfo:
    name = DEVICE_NAMES.get(hub.device, hub.device)
    return DeviceInfo(
        identifiers={(DOMAIN, hub.entry.entry_id)},
        name=name,
        manufacturer="Viessmann",
        model=f"{name} (passive CAN, {hub.interface})",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: E3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    created: set[str] = set()
    prefix = f"{entry.entry_id}_"

    restored: list[SensorEntity] = []
    registry = er.async_get(hass)
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg.domain != "sensor" or not reg.unique_id.startswith(prefix):
            continue
        key = reg.unique_id[len(prefix) :]
        if key in (DIAG_FRAMES, DIAG_UNKNOWN) or key in created:
            continue
        parsed = parse_key(key)
        if parsed is None:
            continue
        info = hub.decoder.describe(*parsed)
        if info is None:
            continue
        created.add(key)
        restored.append(E3ValueSensor(hub, info))

    async_add_entities([*restored, E3FramesSensor(hub), E3UnknownSensor(hub)])

    @callback
    def _new_values(infos: list[ValueInfo]) -> None:
        entities = []
        for info in infos:
            if info.key in created:
                continue
            created.add(info.key)
            entities.append(E3ValueSensor(hub, info))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(async_dispatcher_connect(hass, hub.signal_new, _new_values))
    # values that arrived before the dispatcher was connected
    _new_values(list(hub.infos.values()))


class E3BaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: E3Hub, key: str) -> None:
        self._hub = hub
        self._key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_device_info = device_info(hub)

    def _signal(self) -> str:
        return f"{self._hub.signal_update}_{self._key}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal(), self.async_write_ha_state)
        )


class E3ValueSensor(E3BaseSensor):
    """One decoded value of one data point."""

    def __init__(self, hub: E3Hub, info: ValueInfo) -> None:
        super().__init__(hub, info.key)
        self._info = info
        unit = _UNIT_FIXES.get(info.unit, info.unit) if info.unit else None
        device_class, state_class = _classes(info, unit)
        self._numeric = unit is not None
        self._attr_name = _entity_name(info)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_registry_enabled_default = _enabled_by_default(info)
        self._attr_extra_state_attributes = {"did": info.did, "did_name": info.did_name}
        if info.path:
            self._attr_extra_state_attributes["path"] = "/".join(info.path)

    @property
    def available(self) -> bool:
        return self._key in self._hub.values

    @property
    def native_value(self) -> Any:
        value = self._hub.values.get(self._key)
        if value is None:
            return None
        if self._numeric:
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            return value
        text = str(value)
        return text[:255]


class E3FramesSensor(E3BaseSensor):
    """How many CAN frames the collector has received (diagnostics)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "frames"
    _attr_should_poll = True

    def __init__(self, hub: E3Hub) -> None:
        super().__init__(hub, DIAG_FRAMES)

    async def async_added_to_hass(self) -> None:
        """Polled; no dispatcher needed."""

    @property
    def native_value(self) -> int:
        return self._hub.collector.frames_received

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "interface": self._hub.interface,
            "last_error": self._hub.collector.last_error,
            "data_points": len(self._hub.infos),
        }


class E3UnknownSensor(E3BaseSensor):
    """Data points seen on the bus that could not be decoded (diagnostics)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "unknown"
    _unrecorded_attributes = frozenset({"data_points"})

    def __init__(self, hub: E3Hub) -> None:
        super().__init__(hub, DIAG_UNKNOWN)

    def _signal(self) -> str:
        return f"{self._hub.signal_update}_diagnostics"

    @property
    def native_value(self) -> int:
        return len(self._hub.unknown)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"data_points": dict(sorted(self._hub.unknown.items()))}
