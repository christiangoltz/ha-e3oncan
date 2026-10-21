import struct

from e3oncan.collector import CanCollector, CollectParser, FrameRouter, can_filters
from e3oncan.decoder import Decoder, flatten, make_key, parse_key


def frames_for(did: int, payload: bytes) -> list[bytes]:
    """Encode a payload the way E3 devices broadcast it (Collect protocol)."""
    lo, hi = did & 0xFF, did >> 8
    n = len(payload)
    if n <= 4:
        return [bytes([0x21, lo, hi, 0xB0 + n]) + payload]
    if n <= 15:
        first = bytes([0x21, lo, hi, 0xB0 + n]) + payload[:4]
        rest = payload[4:]
    else:
        first = bytes([0x21, lo, hi, 0xB0, n]) + payload[:3]
        rest = payload[3:]
    out = [first]
    d0 = 0x22
    while rest:
        out.append(bytes([d0]) + rest[:7])
        rest = rest[7:]
        d0 = 0x20 if d0 == 0x2F else d0 + 1
    return out


def feed(parser, frames):
    for f in frames:
        parser.feed(f)
    parser.feed(bytes([0x00] * 8))  # any unrelated frame ends a multi-frame message


def collect(did, payload):
    got = []
    feed(CollectParser(lambda d, p: got.append((d, p))), frames_for(did, payload))
    return got


def test_single_frame():
    payload = struct.pack("<hH", 3863, 0)
    assert collect(1834, payload) == [("1834", payload)]


def test_multi_frame_short():
    payload = struct.pack("<iii", 1200, 800, 0)
    assert collect(1831, payload) == [("1831", payload)]


def test_multi_frame_long_with_wrap():
    payload = bytes(range(124))  # longer than 15 bytes and wraps D0 past 0x2F
    assert collect(2772, payload) == [("2772", payload)]


def test_multi_frame_c1_length():
    payload = bytes(range(40))
    lo, hi = 1801 & 0xFF, 1801 >> 8
    frames = [bytes([0x21, lo, hi, 0xB0, 0xC1, 40]) + payload[:2]]
    rest, d0 = payload[2:], 0x22
    while rest:
        frames.append(bytes([d0]) + rest[:7])
        rest, d0 = rest[7:], d0 + 1
    got = []
    feed(CollectParser(lambda d, p: got.append((d, p))), frames)
    assert got == [("1801", payload)]


def test_ignores_garbage():
    got = []
    p = CollectParser(lambda d, pl: got.append(d))
    for f in (b"", b"\x21\x01", bytes([0x10, 1, 2, 0xB1, 5]), bytes([0x21, 0, 0, 0xB1, 5])):
        p.feed(f)
    assert got == []


def test_decode_vx3_values():
    dec = Decoder("vx3")
    values, err = dec.decode("1834", struct.pack("<hH", 3863, 0))
    assert err is None
    by_key = {info.key: (info, v) for info, v in values}
    info, value = by_key["1834.4/StateOfEnergy"]
    assert value == 3863.0 and info.unit == "Wh" and not info.raw
    assert by_key["1834.4/Unknown"][0].raw

    values, err = dec.decode("1831", struct.pack("<iii", 1200, 800, -5))
    flat = {i.path: v for i, v in values}
    assert flat[("String1",)] == 1200.0 and flat[("String3",)] == -5.0


def test_decode_unknown_did():
    values, err = Decoder("vx3").decode("9999", b"\x01\x02")
    assert values is None and err == "no codec"


def test_enum_values_flatten_to_id_and_text():
    dec = Decoder("vcal")
    values, err = dec.decode("531", bytes([1, 1]))
    assert err is None
    paths = {i.path for i, _ in values}
    assert ("State", "ID") in paths and ("State", "Text") in paths


def test_key_roundtrip_and_describe():
    key = make_key("1603", 8, ("ActivePower",))
    assert parse_key(key) == ("1603", 8, ("ActivePower",))
    assert parse_key("1385.01.4/Total") == ("1385.01", 4, ("Total",))
    dec = Decoder("vx3")
    info = dec.describe("1834", 4, ("StateOfEnergy",))
    assert info is not None and info.unit == "Wh"


def test_e380_router_and_units():
    got = []
    router = FrameRouter("e380", lambda d, p: got.append((d, p)))
    data = struct.pack("<hhhh", 96, 7, -108, -4)
    router.handle(0x250, data)
    assert got == [(str(0x250), data)]
    values, err = Decoder("e380").decode(str(0x250), data)
    assert err is None
    flat = {i.path[-1]: (i.unit, v) for i, v in values}
    assert flat["Total"] == ("W", -4.0)


def test_e3100cb_router():
    got = []
    router = FrameRouter("e3100cb", lambda d, p: got.append((d, p)))
    router.handle(0x569, bytes([0, 0, 0, 4, 0x10, 0x00, 0, 0]))
    assert got == [(f"{0x569}.04", bytes([0x10, 0, 0, 0]))]
    values, err = Decoder("e3100cb").decode(f"{0x569}.04", bytes([0x10, 0, 0, 0]))
    assert err is None, err


def test_filters():
    assert can_filters("vx3", None) == [{"can_id": 0x451, "can_mask": 0x7FF, "extended": False}]
    assert can_filters("vcal", 0x123)[0]["can_id"] == 0x123
    assert len(can_filters("e380", None)) == 14


def test_throttle():
    got = []
    c = CanCollector("can0", "vx3", None, lambda d, p: got.append(d), min_interval=60)
    c._throttled("1834", b"\x00")
    c._throttled("1834", b"\x00")
    c._throttled("1836", b"\x00")
    assert got == ["1834", "1836"]


def test_flatten_lists():
    assert flatten({"a": [1, {"b": 2}]}) == [(("a", "0"), 1), (("a", "1", "b"), 2)]


def test_collector_end_to_end_on_virtual_bus():
    import threading

    import can

    got = []
    done = threading.Event()

    def on_payload(did, payload):
        got.append((did, payload))
        done.set()

    collector = CanCollector("e3test", "vx3", None, on_payload, bus_type="virtual")
    collector.start()
    try:
        sender = can.Bus(interface="virtual", channel="e3test")
        import time
        time.sleep(0.3)  # let the collector open its bus
        payload = struct.pack("<iii", 1500, 0, 0)
        for f in frames_for(1831, payload):
            sender.send(can.Message(arbitration_id=0x451, data=f, is_extended_id=False))
        # a frame on another CAN ID must be ignored (filtered)
        sender.send(can.Message(arbitration_id=0x123, data=bytes([0x21, 0x2A, 0x07, 0xB1, 9]), is_extended_id=False))
        sender.send(can.Message(arbitration_id=0x451, data=bytes(8), is_extended_id=False))
        assert done.wait(3), "no payload decoded"
        sender.shutdown()
    finally:
        collector.stop()
    assert got == [("1831", payload)]
    assert collector.frames_received == 4


def test_overrides_from_real_vx3_frames():
    """Raw payloads captured on a Vitocharge VX3 (Oct 2026)."""
    dec = Decoder("vx3")
    flat = lambda did, raw: {i.path: (i.unit, v) for i, v in dec.decode(did, bytes.fromhex(raw))[0]}

    phase1 = flat("378", "04002bff040000002bffffff")
    assert phase1[("ActivePower",)] == ("W", 4.0)
    assert phase1[("ReactivePower",)] == ("var", -213.0)
    assert flat("380", "edff4bffedffffff4bffffff")[("ActivePower",)] == ("W", -19.0)
    assert flat("1810", "9301d80093010000d8000000")[("ActivePower",)] == ("W", 403.0)

    report = flat("3366", (-406).to_bytes(4, "little", signed=True).hex() + "00" * 12)
    assert report[("15MinPower",)] == ("W", -406.0)

    inverter = flat("1824", "94010000860000008600000086000000")
    assert inverter[("cumulated",)] == ("W", 404.0)

    pcc = flat("1603", "0000eafd")
    assert pcc[("ReactivePower",)][0] == "var"
