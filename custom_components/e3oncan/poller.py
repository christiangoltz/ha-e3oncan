"""Active, read-only polling of an E3 controller (UDS over ISO-TP).

Used for controllers that do not broadcast their data on the bus the adapter
is connected to (e.g. the Vitocal main controller on the external CAN bus).

Read-only by construction: the only request this module can build is
UDS service 0x22 *ReadDataByIdentifier*. There is no code path that writes
data, changes sessions or performs any other service.

Same transport settings as open3e (ISO-TP, 11-bit addressing, response ID =
request ID + 0x10). Nothing here imports Home Assistant.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time

_LOGGER = logging.getLogger(__name__)

READ_DATA_BY_IDENTIFIER = 0x22

# Negative response codes
NRC_REQUEST_OUT_OF_RANGE = 0x31  # DID not supported by this ECU
NRC_CONDITIONS_NOT_CORRECT = 0x22

RETRY_UNSUPPORTED = 24 * 3600  # seconds; effectively "not on this ECU"
RETRY_REJECTED = 600
RETRY_TIMEOUT = 120
GAP_BETWEEN_REQUESTS = 0.05

PayloadCallback = Callable[[str, bytes], None]

ISOTP_PARAMS = {
    "stmin": 10,
    "blocksize": 0,
    "wftmax": 0,
    "tx_data_length": 8,
    "tx_data_min_length": 8,
    "tx_padding": 0,
    "rx_flowcontrol_timeout": 1000,
    "rx_consecutive_frame_timeout": 1000,
    "max_frame_size": 4095,
    "can_fd": False,
    "bitrate_switch": False,
}


def read_request(did: int) -> bytes:
    """The one request this module sends: ReadDataByIdentifier(did)."""
    if not 0 <= did <= 0xFFFF:
        raise ValueError(did)
    return bytes([READ_DATA_BY_IDENTIFIER, did >> 8, did & 0xFF])


def parse_response(did: int, response: bytes | None) -> tuple[bytes | None, int | None]:
    """Return ``(payload, None)`` for a positive response or ``(None, nrc)``.

    ``nrc`` is -1 for no / malformed response.
    """
    if not response:
        return None, -1
    if response[0] == 0x7F:
        return None, response[2] if len(response) >= 3 else -1
    if (
        len(response) >= 3
        and response[0] == READ_DATA_BY_IDENTIFIER + 0x40
        and response[1] == did >> 8
        and response[2] == did & 0xFF
    ):
        return bytes(response[3:]), None
    return None, -1


class UdsPoller:
    """Poll a fixed set of DIDs of one ECU in a background thread."""

    def __init__(
        self,
        interface: str,
        ecu_tx: int,
        dids: dict[int, float],
        on_payload: PayloadCallback,
        min_interval: float = 10,
        bus_type: str = "socketcan",
        request_timeout: float = 2.0,
    ) -> None:
        self._interface = interface
        self._tx = ecu_tx
        self._rx = ecu_tx + 0x10
        self._intervals = {did: max(float(sec), float(min_interval)) for did, sec in dids.items()}
        self._next_due = dict.fromkeys(self._intervals, 0.0)
        self._on_payload = on_payload
        self._bus_type = bus_type
        self._timeout = request_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames_received = 0  # positive responses, for the diagnostics sensor
        self.last_error: str | None = None
        self.unsupported: set[int] = set()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"e3oncan-uds-{self._tx:#x}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self) -> None:
        import can  # noqa: PLC0415
        import isotp  # noqa: PLC0415

        while not self._stop.is_set():
            try:
                with can.Bus(
                    interface=self._bus_type,
                    channel=self._interface,
                    can_filters=[{"can_id": self._rx, "can_mask": 0x7FF, "extended": False}],
                    receive_own_messages=False,
                ) as bus:
                    address = isotp.Address(
                        isotp.AddressingMode.Normal_11bits, txid=self._tx, rxid=self._rx
                    )
                    stack = isotp.CanStack(bus=bus, address=address, params=ISOTP_PARAMS)
                    stack.set_sleep_timing(0.01, 0.01)
                    stack.start()
                    try:
                        self.last_error = None
                        self._poll_loop(stack)
                    finally:
                        stack.stop()
            except Exception as err:  # noqa: BLE001
                self.last_error = str(err)
                _LOGGER.warning(
                    "Polling ECU %#x on %s failed (%s), retrying in 30 s", self._tx, self._interface, err
                )
                self._stop.wait(30)

    def _poll_loop(self, stack) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            due = [did for did, t in self._next_due.items() if t <= now]
            if not due:
                self._stop.wait(0.5)
                continue
            for did in sorted(due, key=self._next_due.get):
                if self._stop.is_set():
                    return
                self._poll(stack, did)
                self._stop.wait(GAP_BETWEEN_REQUESTS)

    def _poll(self, stack, did: int) -> None:
        payload, nrc = self.read(stack, did)
        now = time.monotonic()
        if payload is not None:
            self.frames_received += 1
            self.unsupported.discard(did)
            self._next_due[did] = now + self._intervals[did]
            self._on_payload(str(did), payload)
        elif nrc == NRC_REQUEST_OUT_OF_RANGE:
            self.unsupported.add(did)
            self._next_due[did] = now + RETRY_UNSUPPORTED
        elif nrc == NRC_CONDITIONS_NOT_CORRECT:
            self._next_due[did] = now + RETRY_REJECTED
        elif nrc == -1:
            self._next_due[did] = now + RETRY_TIMEOUT
        else:
            self._next_due[did] = now + RETRY_REJECTED

    def read(self, stack, did: int) -> tuple[bytes | None, int | None]:
        """Send ReadDataByIdentifier and wait for the answer (handles 'response pending')."""
        # drop anything left over from an earlier, timed-out request
        while stack.available():
            stack.recv()
        stack.send(read_request(did))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            data = stack.recv(block=True, timeout=0.1)
            if data is None:
                continue
            data = bytes(data)
            if len(data) >= 3 and data[0] == 0x7F and data[2] == 0x78:
                # responsePending: the ECU needs more time
                deadline = time.monotonic() + self._timeout
                continue
            return parse_response(did, data)
        return None, -1
