"""Connects the CAN collector to Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .collector import CanCollector, split_scan_key
from .dids import VITOAIR_DIDS, VITOCAL_DIDS
from .poller import UdsPoller
from .const import (
    CONF_CAN_ID,
    CONF_CAN_INTERFACE,
    CONF_DEVICE,
    CONF_MIN_INTERVAL,
    DEFAULT_MIN_INTERVAL,
    DEVICE_SCAN,
    DEVICE_VAIR_READ,
    DEVICE_VX3,
    READ_DEVICES,
    UNAVAILABLE_VALUES,
    SIGNAL_NEW_VALUES,
    SIGNAL_UPDATE,
)
from .decoder import Decoder, ValueInfo

_LOGGER = logging.getLogger(__name__)

MAX_UNKNOWN = 200


class E3Hub:
    """Holds the latest decoded values of one listened-to device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.device: str = entry.data[CONF_DEVICE]
        self.interface: str = entry.data[CONF_CAN_INTERFACE]
        can_id = entry.data.get(CONF_CAN_ID)
        self.can_id: int | None = int(can_id, 0) if can_id else None
        self.is_scan = self.device == DEVICE_SCAN
        self.is_read = self.device in READ_DEVICES
        if self.is_read:
            default_ecu, table_device = READ_DEVICES[self.device]
            self.ecu = self.can_id if self.can_id is not None else default_ecu
        else:
            # the scan names data points with the common E3 tables
            table_device = DEVICE_VX3 if self.is_scan else self.device
        self.decoder = Decoder(table_device)
        # bus scan: CAN ID -> {did.len: data point name}
        self.scan: dict[str, dict[str, str]] = {}
        self.values: dict[str, Any] = {}
        self.infos: dict[str, ValueInfo] = {}
        # DIDs seen on the bus that have no (working) codec: did.len -> details
        self.unknown: dict[str, dict[str, str]] = {}
        # "<did>.<len>" of data points whose sensor is not connected
        self.absent: set[str] = set()
        min_interval = entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
        self.collector: CanCollector | UdsPoller
        if self.is_read:
            dids = VITOAIR_DIDS if self.device == DEVICE_VAIR_READ else VITOCAL_DIDS
            self.collector = UdsPoller(
                self.interface,
                self.ecu,
                dids,
                self._on_payload,
                min_interval=float(min_interval),
            )
        else:
            self.collector = CanCollector(
                self.interface,
                self.device,
                self.can_id,
                self._on_payload,
                min_interval=float(min_interval),
            )
        self.signal_new = SIGNAL_NEW_VALUES.format(entry_id=entry.entry_id)
        self.signal_update = SIGNAL_UPDATE.format(entry_id=entry.entry_id)

    def start(self) -> None:
        self.collector.start()

    def stop(self) -> None:
        self.collector.stop()

    # Runs in the collector thread.
    def _on_payload(self, did: str, payload: bytes) -> None:
        if self.is_scan:
            can_id, real_did = split_scan_key(did)
            codec = self.decoder.codec_for(real_did, len(payload))
            name = codec.id if codec is not None else "unknown"
            self.hass.loop.call_soon_threadsafe(
                self._apply_scan, can_id, f"{real_did}.{len(payload)}", name
            )
            return
        values, error = self.decoder.decode(did, payload)
        self.hass.loop.call_soon_threadsafe(self._apply, did, payload, values, error)

    @callback
    def _apply_scan(self, can_id: str, did: str, name: str) -> None:
        dids = self.scan.get(can_id)
        is_new_id = dids is None
        if is_new_id:
            dids = self.scan[can_id] = {}
        if did in dids:
            return
        dids[did] = name
        if is_new_id:
            async_dispatcher_send(self.hass, f"{self.signal_new}_scan", can_id)
        async_dispatcher_send(self.hass, f"{self.signal_update}_scan_{can_id}")

    @callback
    def _apply(
        self,
        did: str,
        payload: bytes,
        values: list[tuple[ValueInfo, Any]] | None,
        error: str | None,
    ) -> None:
        if values is None:
            key = f"{did}.{len(payload)}"
            is_new = key not in self.unknown
            if is_new and len(self.unknown) >= MAX_UNKNOWN:
                return
            self.unknown[key] = {"reason": error or "", "raw": payload.hex()}
            if is_new:
                async_dispatcher_send(self.hass, f"{self.signal_update}_diagnostics")
            return

        # a sensor that is not connected reports -3276.8 as its actual value:
        # do not create entities for it, and drop the ones created earlier
        absent = any(
            info.path == ("Actual",) and value in UNAVAILABLE_VALUES for info, value in values
        )
        if absent:
            prefix = f"{did}.{len(payload)}"
            if prefix not in self.absent:
                self.absent.add(prefix)
                async_dispatcher_send(self.hass, f"{self.signal_new}_absent", prefix)
            return
        self.absent.discard(f"{did}.{len(payload)}")

        new: list[ValueInfo] = []
        for info, value in values:
            if info.key not in self.infos:
                self.infos[info.key] = info
                new.append(info)
            self.values[info.key] = value
        if new:
            async_dispatcher_send(self.hass, self.signal_new, new)
        for info, _ in values:
            async_dispatcher_send(self.hass, f"{self.signal_update}_{info.key}")
