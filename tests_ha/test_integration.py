import struct
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.e3oncan.const import DOMAIN

PATCH_CHECK = "custom_components.e3oncan.config_flow.check_interface"
PATCH_START = "custom_components.e3oncan.collector.CanCollector.start"
PATCH_STOP = "custom_components.e3oncan.collector.CanCollector.stop"


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(PATCH_CHECK):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"device": "vx3", "can_interface": "can0", "can_id": "", "min_interval": 10},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vitocharge VX3 (can0)"
    assert result["data"] == {"can_interface": "can0", "device": "vx3"}
    assert result["options"] == {"min_interval": 10}


async def test_config_flow_errors(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(PATCH_CHECK, side_effect=OSError("No such device")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"device": "vx3", "can_interface": "can9", "can_id": "", "min_interval": 10},
        )
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device": "vx3", "can_interface": "can0", "can_id": "zzz", "min_interval": 10},
    )
    assert result["errors"] == {"can_id": "invalid_can_id"}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"can_interface": "can0", "device": "vx3"},
        options={"min_interval": 0},
        unique_id="can0_vx3_0x451",
    )
    entry.add_to_hass(hass)
    with patch(PATCH_START), patch(PATCH_STOP):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_values_create_sensors(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    # what the collector thread would deliver
    hub._on_payload("1834", struct.pack("<hH", 3863, 0))
    hub._on_payload("1831", struct.pack("<iii", 1200, 800, 0))
    hub._on_payload("9999", b"\x01\x02\x03")
    await hass.async_block_till_done()

    reg = er.async_get(hass)
    entities = {e.unique_id.split("_", 1)[1]: e for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    soe = entities["1834.4/StateOfEnergy"]
    state = hass.states.get(soe.entity_id)
    assert state.state == "3863.0"
    assert state.attributes["unit_of_measurement"] == "Wh"
    assert state.attributes["device_class"] == "energy_storage"

    pv = hass.states.get(entities["1831.12/String1"].entity_id)
    assert pv.state == "1200.0" and pv.attributes["device_class"] == "power"

    # raw/unknown parts are created but disabled by default
    assert entities["1834.4/Unknown"].disabled_by is er.RegistryEntryDisabler.INTEGRATION

    unknown = hass.states.get(entities["diag_unknown"].entity_id)
    assert unknown.state == "1"
    assert "9999.3" in unknown.attributes["data_points"]

    # update keeps the same entity
    hub._on_payload("1834", struct.pack("<hH", 3000, 0))
    await hass.async_block_till_done()
    assert hass.states.get(soe.entity_id).state == "3000.0"

    # restart: entity is restored from the registry and unavailable until data arrives
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)
    with patch(PATCH_START), patch(PATCH_STOP):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(soe.entity_id).state == "unavailable"
    entry.runtime_data._on_payload("1834", struct.pack("<hH", 3100, 0))
    await hass.async_block_till_done()
    assert hass.states.get(soe.entity_id).state == "3100.0"
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with patch(PATCH_START), patch(PATCH_STOP):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"min_interval": 30})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"min_interval": 30}
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_bus_scan_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"can_interface": "can0", "device": "scan"}, options={"min_interval": 0}, unique_id="can0_scan"
    )
    entry.add_to_hass(hass)
    with patch(PATCH_START), patch(PATCH_STOP):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    hub = entry.runtime_data
    hub.collector.router.frames.update({0x451: 10, 0x693: 5, 0x680: 3})
    hub._on_payload("0x451/1834", struct.pack("<hH", 1, 0))
    hub._on_payload("0x451/1836", struct.pack("<i", 1))
    hub._on_payload("0x693/268", bytes(9))
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    ents = {e.unique_id.split("_", 1)[1]: e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    s451 = hass.states.get(ents["scan_0x451"])
    assert s451.state == "2"
    assert s451.attributes["data_points"]["1834.4"] == "ElectricalEnergyStorageStateOfEnergy"
    assert hass.states.get(ents["scan_0x693"]).attributes["data_points"]["268.9"] == "FlowTemperatureSensor"
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_old_topology_entities_are_removed(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"can_interface": "can0", "device": "vx3"}, options={"min_interval": 0})
    entry.add_to_hass(hass)
    from custom_components.e3oncan.decoder import Decoder

    key = next(k for k, c in Decoder("vx3").table.items() if "BusTopology" in c.id)
    reg = er.async_get(hass)
    old = reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_{key}/Count", config_entry=entry)
    with patch(PATCH_START), patch(PATCH_STOP):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert reg.async_get(old.entity_id) is None
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_read_mode_vitocal(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"can_interface": "can0", "device": "vcal_read"}, options={"min_interval": 10}, unique_id="can0_vcal_read_0x680"
    )
    entry.add_to_hass(hass)
    with patch("custom_components.e3oncan.poller.UdsPoller.start"), patch("custom_components.e3oncan.poller.UdsPoller.stop"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        hub = entry.runtime_data
        assert hub.ecu == 0x680 and type(hub.collector).__name__ == "UdsPoller"
        # FlowTemperatureSensor 24.9 °C, then an unconnected sensor (-3276.8)
        hub._on_payload("268", struct.pack("<hhhhB", 249, 160, 711, 250, 0))
        hub._on_payload("284", struct.pack("<hhhhB", -32768, -32768, -32768, -32768, 0))
        await hass.async_block_till_done()
        reg = er.async_get(hass)
        ents = {e.unique_id.split("_", 1)[1]: e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
        flow = hass.states.get(ents["268.9/Actual"])
        assert flow.state == "24.9" and flow.attributes["device_class"] == "temperature"
        assert hass.states.get(ents["284.9/Actual"]).state == "unknown"
        dev = __import__("homeassistant.helpers.device_registry", fromlist=["x"]).async_get(hass)
        model = next(iter(dev.devices.values())).model
        assert "read-only polling of ECU 0x680" in model
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_e380_names_two_meters(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"can_interface": "can0", "device": "e380"}, options={"min_interval": 0})
    entry.add_to_hass(hass)
    with patch(PATCH_START), patch(PATCH_STOP):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    hub = entry.runtime_data
    data = struct.pack("<hhhh", 1, 2, 3, 6)
    hub._on_payload(str(0x250), data)
    hub._on_payload(str(0x251), data)
    hub._on_payload(str(0x25C), bytes(8))
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    ents = {e.unique_id.split("_", 1)[1]: e for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    from homeassistant.helpers import device_registry as dr

    devreg = dr.async_get(hass)
    m1 = devreg.async_get(ents[f"{0x250}.8/Total"].device_id)
    m2 = devreg.async_get(ents[f"{0x251}.8/Total"].device_id)
    assert m1.name == "Energy meter E380 1" and m2.name == "Energy meter E380 2"
    assert m1.id != m2.id
    assert hass.states.get(ents[f"{0x250}.8/Total"].entity_id).name == "Energy meter E380 1 Grid Active Power Total"
    assert ents[f"{0x25C}.8/ImportCumulated"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    with patch(PATCH_STOP):
        assert await hass.config_entries.async_unload(entry.entry_id)
