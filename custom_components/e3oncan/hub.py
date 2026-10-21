"""Connects the CAN collector to Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .collector import CanCollector
from .const import (
    CONF_CAN_ID,
    CONF_CAN_INTERFACE,
    CONF_DEVICE,
    CONF_MIN_INTERVAL,
    DEFAULT_MIN_INTERVAL,
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
        self.decoder = Decoder(self.device)
        self.values: dict[str, Any] = {}
        self.infos: dict[str, ValueInfo] = {}
        # DIDs seen on the bus that have no (working) codec: did.len -> details
        self.unknown: dict[str, dict[str, str]] = {}
        min_interval = entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
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
        values, error = self.decoder.decode(did, payload)
        self.hass.loop.call_soon_threadsafe(self._apply, did, payload, values, error)

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
