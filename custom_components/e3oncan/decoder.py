"""Decode Viessmann E3 data points and describe their values.

Wraps the codec tables vendored from E3onCAN (see ``e3/``). Nothing in this
module imports Home Assistant, so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .const import DEVICE_E380, DEVICE_E3100CB, IGNORED_DID_NAME_PARTS
from .e3 import (
    E3onCANcodecs,
    E3onCANdatapointsE380,
    E3onCANdatapointsE3100CB,
    Open3Ecodecs,
    Open3Edatapoints,
    Open3EdatapointsVariants,
)
from .overrides import E3_OVERRIDES, E3_UNIT_REPLACE, E3_UNITS, is_energy_period

_LOGGER = logging.getLogger(__name__)

# The vendored codecs return hex strings unless raw mode is switched off.
Open3Ecodecs.flag_rawmode = False
E3onCANcodecs.flag_rawmode = False

# Units for energy-meter values, whose codecs carry no unit of their own.
_METER_UNITS = {
    "GridActivePower": "W",
    "GridReactivePower": "var",
    "GridVoltage": "V",
    "GridEnergy": "kWh",
}


@dataclass(frozen=True)
class ValueInfo:
    """Static description of one decoded value (one sensor)."""

    key: str
    did: str
    did_name: str
    path: tuple[str, ...]
    unit: str | None
    raw: bool


def _full_did_table(common: dict, variants: dict | None = None) -> dict[str, Any]:
    """Return codecs keyed by ``"<did>.<length>"``, like E3onCAN does."""
    table: dict[str, Any] = {}
    for did, codec in common.items():
        table[f"{did}.{codec.string_len}"] = codec
        if variants and did in variants:
            for did_len, variant in variants[did].items():
                table[f"{did}.{did_len}"] = variant
    return table


def build_did_table(device: str) -> dict[str, Any]:
    """Return the codec table for a device type."""
    if device == DEVICE_E380:
        return _full_did_table(E3onCANdatapointsE380.dataIdentifiersE380)
    if device == DEVICE_E3100CB:
        return _full_did_table(E3onCANdatapointsE3100CB.dataIdentifiersE3100CB)
    table = _full_did_table(
        Open3Edatapoints.dataIdentifiers["dids"],
        Open3EdatapointsVariants.dataIdentifiers["dids"],
    )
    table.update(E3_OVERRIDES)
    return table


def _sub_codec(codec: Any, part: str) -> Any | None:
    """Find the child codec named ``part`` inside a complex codec."""
    for sub in getattr(codec, "subTypes", None) or []:
        if getattr(sub, "id", None) == part:
            return sub
    cases = getattr(codec, "cases", None)
    if cases:
        for case in list(cases.values()) + [getattr(codec, "default", None)]:
            if case is None:
                continue
            if getattr(case, "id", None) == part:
                return case
            found = _sub_codec(case, part)
            if found is not None:
                return found
    return None


def _leaf_codec(codec: Any, path: tuple[str, ...]) -> Any | None:
    current = codec
    for part in path:
        if part.isdigit():
            # list index: stay on the list's element codec
            continue
        nxt = _sub_codec(current, part)
        if nxt is None:
            return None
        current = nxt
    return current


def _is_raw(codec: Any | None) -> bool:
    if codec is None:
        return False
    name = type(codec).__name__
    return name in ("RawCodec", "O3ERawCodec")


def flatten(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Split a decoded value into scalar leaves, the way E3onCAN splits MQTT topics."""
    if isinstance(value, dict):
        out: list[tuple[tuple[str, ...], Any]] = []
        for key, item in value.items():
            out.extend(flatten(item, (*path, str(key))))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for index, item in enumerate(value):
            out.extend(flatten(item, (*path, str(index))))
        return out
    return [(path, value)]


def make_key(did: str, did_len: int, path: tuple[str, ...]) -> str:
    """Stable key for one value: ``<did>.<len>[/<sub>...]``."""
    return "/".join((f"{did}.{did_len}", *path))


class Decoder:
    """Decode raw DID payloads for one device type."""

    def __init__(self, device: str) -> None:
        self.device = device
        self.table = build_did_table(device)

    def codec_for(self, did: str, did_len: int) -> Any | None:
        return self.table.get(f"{did}.{did_len}")

    def decode(
        self, did: str, data: bytes
    ) -> tuple[list[tuple[ValueInfo, Any]] | None, str | None]:
        """Decode one payload.

        Returns ``(values, None)`` on success, or ``(None, reason)`` when the
        DID is unknown or its payload cannot be decoded.
        """
        codec = self.codec_for(did, len(data))
        if codec is None:
            return None, "no codec"
        if is_ignored(codec.id):
            return [], None
        try:
            decoded = codec.decode(bytes(data))
        except Exception as err:  # noqa: BLE001 - vendored codecs raise anything
            return None, f"decode error: {err}"

        result: list[tuple[ValueInfo, Any]] = []
        for path, value in flatten(decoded):
            info = self.describe(did, len(data), path, codec)
            if info is not None:
                result.append((info, value))
        return result, None

    def describe(
        self, did: str, did_len: int, path: tuple[str, ...], codec: Any | None = None
    ) -> ValueInfo | None:
        """Describe a value from its DID, payload length and sub path."""
        if codec is None:
            codec = self.codec_for(did, did_len)
            if codec is None:
                return None
        leaf = _leaf_codec(codec, path) if path else codec
        unit = getattr(leaf, "unit", None) or None
        if unit is None:
            if self.device in (DEVICE_E380, DEVICE_E3100CB):
                unit = _meter_unit(codec.id, path)
            elif path:
                unit = E3_UNITS.get((codec.id, path[-1]))
                if unit is None and is_energy_period(codec.id, path[-1]):
                    unit = "kWh"
        if unit is not None and codec.id in E3_UNIT_REPLACE:
            unit = E3_UNIT_REPLACE[codec.id]
        if unit == "VA" and path and "ReactivePower" in path[-1]:
            # upstream labels reactive power with the apparent power unit
            unit = "var"
        return ValueInfo(
            key=make_key(did, did_len, path),
            did=did,
            did_name=codec.id,
            path=path,
            unit=unit,
            raw=_is_raw(leaf),
        )


def _meter_unit(did_name: str, path: tuple[str, ...]) -> str | None:
    last = path[-1] if path else ""
    if did_name == "GridCurrent":
        return None if last == "cosPhi" else "A"
    if did_name == "GridVoltage" and last == "Frequency":
        return "Hz"
    if did_name == "GridPower":
        return "var" if last == "ReactivePower" else "W"
    if did_name == "GridState":
        return None
    return _METER_UNITS.get(did_name)


_DEVICE_STATISTICS = ("Minimum", "Maximum", "Average")


def is_noise(path: tuple[str, ...]) -> bool:
    """Values switched off by default: the device's own min/max/average and sensor status."""
    if not path:
        return False
    return path[-1] in _DEVICE_STATISTICS or path[-1] == "Error" or "SensorStatus" in path


def is_ignored(did_name: str) -> bool:
    """Data points that never become entities."""
    return any(part in did_name for part in IGNORED_DID_NAME_PARTS)


def parse_key(key: str) -> tuple[str, int, tuple[str, ...]] | None:
    """Inverse of :func:`make_key`."""
    head, *path = key.split("/")
    did, sep, did_len = head.rpartition(".")
    if not sep or not did_len.isdigit():
        return None
    return did, int(did_len), tuple(path)
