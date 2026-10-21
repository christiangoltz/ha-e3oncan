import struct
import threading
import time

import can
import isotp

from e3oncan.poller import UdsPoller, parse_response, read_request


def test_read_request_is_only_read_data_by_identifier():
    assert read_request(268) == bytes([0x22, 0x01, 0x0C])


def test_parse_response():
    assert parse_response(268, bytes([0x62, 0x01, 0x0C, 1, 2])) == (bytes([1, 2]), None)
    assert parse_response(268, bytes([0x7F, 0x22, 0x31])) == (None, 0x31)
    assert parse_response(268, bytes([0x62, 0x01, 0x0D, 1])) == (None, -1)
    assert parse_response(268, None) == (None, -1)


class FakeEcu:
    """Answers ReadDataByIdentifier like an E3 ECU at 0x680 (responds on 0x690)."""

    def __init__(self, channel, data):
        self.data = data
        self.requests = []
        self._stop = threading.Event()
        self.bus = can.Bus(interface="virtual", channel=channel)
        self.stack = isotp.CanStack(
            bus=self.bus,
            address=isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x690, rxid=0x680),
            params={"tx_data_min_length": 8, "tx_padding": 0},
        )
        self.stack.start()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.is_set():
            req = self.stack.recv(block=True, timeout=0.1)
            if req is None:
                continue
            req = bytes(req)
            self.requests.append(req)
            did = req[1] << 8 | req[2]
            if req[0] != 0x22:
                self.stack.send(bytes([0x7F, req[0], 0x11]))
            elif did in self.data:
                self.stack.send(bytes([0x62, req[1], req[2]]) + self.data[did])
            else:
                self.stack.send(bytes([0x7F, 0x22, 0x31]))

    def close(self):
        self._stop.set()
        self.thread.join(2)
        self.stack.stop()
        self.bus.shutdown()


def test_poller_reads_values_and_skips_unsupported():
    flow = struct.pack("<hhhhB", 249, 160, 711, 250, 0)  # 9 bytes -> ISO-TP multi frame
    energy = struct.pack("<iiiiii", 7, 242, 524, 100, 624, 0)  # 24 bytes
    ecu = FakeEcu("uds1", {268: flow, 548: energy})
    got = {}
    done = threading.Event()

    def on_payload(did, payload):
        got[did] = payload
        if len(got) == 2:
            done.set()

    poller = UdsPoller("uds1", 0x680, {268: 5, 548: 5, 9999: 5}, on_payload, min_interval=60, bus_type="virtual")
    poller.start()
    try:
        assert done.wait(10), got
        time.sleep(0.5)
    finally:
        poller.stop()
        ecu.close()
    assert got == {"268": flow, "548": energy}
    assert 9999 in poller.unsupported
    # every request the poller sent was a ReadDataByIdentifier
    assert ecu.requests and all(r[0] == 0x22 and len(r) == 3 for r in ecu.requests)
    # min_interval=60 -> each DID asked exactly once in this short test
    assert sorted(r[1] << 8 | r[2] for r in ecu.requests) == [268, 548, 9999]
