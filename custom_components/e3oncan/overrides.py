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
    # Vitoair fans: upstream divides the speed by 10; the raw value is rpm.
    "1040.6": O3EComplexType(
        6,
        "SupplyAirFan",
        [RawCodec(3, "Unknown1"), O3EInt16(2, "Actual", scale=1.0, signed=True, unit="rpm"), RawCodec(1, "Unknown2")],
    ),
    "1041.6": O3EComplexType(
        6,
        "ExhaustAirFan",
        [RawCodec(3, "Unknown1"), O3EInt16(2, "Actual", scale=1.0, signed=True, unit="rpm"), RawCodec(1, "Unknown2")],
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

_SENSOR_VALUES = ("Actual", "Minimum", "Maximum", "Average")

# Units for whole groups of upstream definitions that have none (mostly
# Vitoair and Vitocal values read by polling):
# (end of the data point name, sub values or None for all) -> unit
E3_NAME_UNITS = (
    ("TemperatureSensor", _SENSOR_VALUES, "°C"),
    ("MinimumVentilationSupplyAirTemperature", None, "°C"),
    ("FrostProtectionConfiguration", ("Temperature",), "°C"),
    ("HumiditySensor", _SENSOR_VALUES, "%"),
    ("CurrentVentilationHeatRecovery", None, "%"),
    ("FilterRuntime", None, "h"),
    ("VentilationCurrentVolumeFlow", None, "m³/h"),
    ("ThreeWayValvePositionPercent", None, "%"),
    ("Pump", ("TargetValue", "Actual", "ActualValue"), "%"),
    ("PumpStatus", ("Actual",), "%"),
    ("PumpMinimumMaximumLimit", None, "%"),
    ("CompressorMinMaxSpeedHeating", None, "%"),
    ("DesiredThermalCapacity", None, "W"),
)


def name_unit(did_name: str, sub: str) -> str | None:
    """Unit from E3_NAME_UNITS, or the energy of a seasonal performance counter."""
    if did_name.startswith("Seasonal") and sub in ("EnergyThermal", "EnergyElectric"):
        return "kWh"
    for suffix, subs, unit in E3_NAME_UNITS:
        if did_name.endswith(suffix) and (subs is None or sub in subs):
            return unit
    return None


# Units that are wrong upstream: did name -> correct unit for all its values
E3_UNIT_REPLACE = {
    "WaterPressureSensor": "bar",  # upstream says hPa, the values are bar
}

# Period counters (Today, Past7Days, ...) of these data points are kWh
ENERGY_PERIODS = ("Today", "Past7Days", "CurrentMonth", "PastMonth", "CurrentYear", "PastYear")


def is_energy_period(did_name: str, sub: str) -> bool:
    return sub in ENERGY_PERIODS and (
        did_name.startswith("EnergyConsumption")
        or (did_name.startswith("Generated") and did_name.endswith("Output"))
    )
