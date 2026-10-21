"""Passive collector for Viessmann E3 CAN broadcasts.

Port of the receive loop of E3onCAN's ``E3onCANcollect.py``. It only reads
frames from the bus; it never transmits. Nothing here imports Home Assistant.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
import threading
import time
from typing import Any

from .const import (
    DEVICE_E380,
    DEVICE_E3100CB,
    E380_CAN_IDS,
    E3100CB_CAN_ID,
    E3_DEFAULT_CAN_ID,
)

_LOGGER = logging.getLogger(__name__)

# (did, payload) -> None
FrameCallback = Callable[[str, bytes], None]


class CollectParser:
    """Reassemble E3 "Collect" messages from single CAN frames.

    Same state machine as E3onCAN: a message starts with D0=0x21 and a type
    byte 0xB0..0xBF in D3; longer messages continue in frames whose D0 counts
    up from 0x22 and wraps from 0x2F to 0x20.
    """

    def __init__(self, on_payload: FrameCallback) -> None:
        self._on_payload = on_payload
        self._collecting = False
        self._did = 0
        self._len = 0
        self._data = bytearray()
        self._d0_expected = 0x21

    def feed(self, data: bytes) -> None:
        if self._collecting:
            if data and data[0] == self._d0_expected:
                self._data += data[1:]
                self._d0_expected += 1
                if self._d0_expected > 0x2F:
                    self._d0_expected = 0x20
            else:
                if len(self._data) >= self._len:
                    self._emit(self._did, bytes(self._data[: self._len]))
                self._collecting = False

        if self._collecting or len(data) <= 4:
            return
        if data[0] != 0x21 or not 0xB0 <= data[3] <= 0xBF:
            return

        did = data[1] + 256 * data[2]
        if not 0 < did < 10000:
            return
        d3 = data[3]
        if d3 in (0xB1, 0xB2, 0xB3, 0xB4):
            # single frame, 1..4 bytes
            self._emit(did, bytes(data[4 : 4 + (d3 - 0xB0)]))
        elif d3 == 0xB0:
            # multi frame, explicit length
            self._did = did
            self._d0_expected = data[0] + 1
            if data[4] == 0xC1:
                self._len = data[5]
                self._data = bytearray(data[6:])
            else:
                self._len = data[4]
                self._data = bytearray(data[5:])
            self._collecting = True
        else:
            # multi frame, 5..15 bytes
            self._did = did
            self._d0_expected = data[0] + 1
            self._len = d3 - 0xB0
            self._data = bytearray(data[4:])
            self._collecting = True

    def _emit(self, did: int, payload: bytes) -> None:
        self._on_payload(str(did), payload)


def can_filters(device: str, can_id: int | None) -> list[dict[str, Any]]:
    """SocketCAN filters for the frames a device type broadcasts."""
    if device == DEVICE_E380:
        ids: Iterable[int] = E380_CAN_IDS
    elif device == DEVICE_E3100CB:
        ids = [E3100CB_CAN_ID]
    else:
        ids = [can_id if can_id is not None else E3_DEFAULT_CAN_ID[device]]
    return [{"can_id": i, "can_mask": 0x7FF, "extended": False} for i in ids]


class FrameRouter:
    """Turn raw CAN frames into (did, payload) pairs for one device type."""

    def __init__(self, device: str, on_payload: FrameCallback) -> None:
        self._device = device
        self._on_payload = on_payload
        self._parser = CollectParser(on_payload)

    def handle(self, arbitration_id: int, data: bytes) -> None:
        if self._device == DEVICE_E380:
            # 8 data bytes without protocol; the CAN ID is the DID
            self._on_payload(str(arbitration_id), bytes(data))
        elif self._device == DEVICE_E3100CB:
            if len(data) == 8:
                self._on_payload(f"{arbitration_id}.{data[3]:02d}", bytes(data[4:]))
        else:
            self._parser.feed(bytes(data))


class CanCollector:
    """Read one SocketCAN interface in a background thread."""

    def __init__(
        self,
        interface: str,
        device: str,
        can_id: int | None,
        on_payload: FrameCallback,
        min_interval: float = 0,
        bus_type: str = "socketcan",
    ) -> None:
        self._interface = interface
        self._bus_type = bus_type
        self._filters = can_filters(device, can_id)
        self._min_interval = min_interval
        self._next_allowed: dict[str, float] = {}
        self._on_payload = on_payload
        self._router = FrameRouter(device, self._throttled)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames_received = 0
        self.last_error: str | None = None

    def _throttled(self, did: str, payload: bytes) -> None:
        now = time.monotonic()
        if now < self._next_allowed.get(did, 0):
            return
        self._next_allowed[did] = now + self._min_interval
        self._on_payload(did, payload)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"e3oncan-{self._interface}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        import can  # noqa: PLC0415 - heavy import, only inside the worker

        while not self._stop.is_set():
            try:
                with can.Bus(
                    interface=self._bus_type,
                    channel=self._interface,
                    can_filters=self._filters,
                    receive_own_messages=False,
                ) as bus:
                    self.last_error = None
                    _LOGGER.debug("Listening on %s with filters %s", self._interface, self._filters)
                    while not self._stop.is_set():
                        msg = bus.recv(timeout=1.0)
                        if msg is None or msg.is_error_frame or msg.is_remote_frame:
                            continue
                        self.frames_received += 1
                        try:
                            self._router.handle(msg.arbitration_id, msg.data)
                        except Exception:  # noqa: BLE001 - keep listening
                            _LOGGER.exception("Error handling CAN frame %s", msg)
            except Exception as err:  # noqa: BLE001 - interface down, unplugged, ...
                self.last_error = str(err)
                _LOGGER.warning("CAN interface %s not usable (%s), retrying in 30 s", self._interface, err)
                self._stop.wait(30)


def check_interface(interface: str) -> None:
    """Open and close the interface once; raises if it cannot be used."""
    import can  # noqa: PLC0415

    with can.Bus(interface="socketcan", channel=interface, receive_own_messages=False):
        pass
