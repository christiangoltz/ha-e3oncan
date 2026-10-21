"""Local corrections to the vendored E3onCAN data point tables.

Kept separate so that ``e3/`` can be replaced by a newer E3onCAN snapshot
unchanged. Entries are keyed like the decoder table: ``"<did>.<length>"``.
Each one should be reported upstream so it can eventually be dropped here.
"""

from __future__ import annotations

from .e3.Open3Ecodecs import O3EComplexType, O3EInt16, O3EInt32, RawCodec


def _power_12(name: str) -> O3EComplexType:
    # Same layout as the 12-byte variant of DID 1603: the power values are
    # repeated as 32-bit integers after the first four bytes.
    return O3EComplexType(
        12,
        name,
        [
            O3EInt16(2, "ActivePower", scale=1.0, signed=True, unit="W"),
            O3EInt16(2, "ReactivePower", scale=1.0, signed=True, unit="var"),
            RawCodec(8, "Unknown"),
        ],
    )


# E3 devices (vx3, vcal, vair, vdens)
E3_OVERRIDES = {
    # Vitocharge VX3 sends these with 12 instead of 4 bytes.
    "378.12": _power_12("PointOfCommonCouplingPhaseOne"),
    "379.12": _power_12("PointOfCommonCouplingPhaseTwo"),
    "380.12": _power_12("PointOfCommonCouplingPhaseThree"),
    "1810.12": _power_12("ElectricalEnergyInverterPowerAc"),
    # Upstream: unsigned and without units; 15MinPower is negative when feeding in.
    "3366.16": O3EComplexType(
        16,
        "ElectricalActivePowerStatusReport",
        [
            O3EInt32(4, "15MinPower", scale=1.0, signed=True, unit="W"),
            O3EInt32(4, "15MinEnergy", scale=10, signed=True, unit="Wh"),
            RawCodec(4, "Unknown1"),
            RawCodec(4, "Unknown2"),
        ],
    ),
}

# Units for upstream definitions that have none: (did name, sub value) -> unit
E3_UNITS = {
    ("ThreePhaseInverterCurrentPower", "cumulated"): "W",
    ("ThreePhaseInverterCurrentPower", "L1"): "W",
    ("ThreePhaseInverterCurrentPower", "L2"): "W",
    ("ThreePhaseInverterCurrentPower", "L3"): "W",
    ("PointOfCommonCouplingPhaseOne", "ActivePower"): "W",
    ("PointOfCommonCouplingPhaseTwo", "ActivePower"): "W",
    ("PointOfCommonCouplingPhaseThree", "ActivePower"): "W",
    ("PointOfCommonCouplingPhaseOne", "ReactivePower"): "var",
    ("PointOfCommonCouplingPhaseTwo", "ReactivePower"): "var",
    ("PointOfCommonCouplingPhaseThree", "ReactivePower"): "var",
    ("ElectricalEnergyInverterPowerAc", "ActivePower"): "W",
    ("ElectricalEnergyInverterPowerAc", "ReactivePower"): "var",
}
