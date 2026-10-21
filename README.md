# E3onCAN for Home Assistant

Passively reads **Viessmann E3** devices from the CAN bus and turns their data into Home Assistant sensors – **read-only, nothing is ever sent to the bus**.

E3 devices broadcast much of their data unasked ("Collect" protocol). This integration listens to those broadcasts. That makes it useful where active reading (e.g. with [open3e](https://github.com/open3e/open3e)) is rejected – for example a **Vitocharge VX3** that answers UDS requests with `ConditionsNotCorrect`.

It is a Home Assistant port of [E3onCAN](https://github.com/MyHomeMyData/E3onCAN) by MyHomeMyData and reuses its data point definitions and codecs (Apache-2.0).

## Supported devices

| Device | Type | Default CAN ID |
|---|---|---|
| Vitocharge VX3 (inverter / battery) | `vx3` | 0x451 |
| Vitocal (heat pump) | `vcal` | 0x693 |
| Vitoair (ventilation) | `vair` | 0x451 |
| Vitodens (gas boiler) | `vdens` | 0x451 |
| Energy meter E380 CA | `e380` | 0x250–0x25D |
| Energy meter E3100CB | `e3100cb` | 0x569 |

As in E3onCAN: data of a *slave* device (e.g. the VX3) is usually broadcast on the **external** CAN bus, data of the *master* (e.g. Vitocal) on the internal one.

## Requirements

- A SocketCAN adapter (e.g. innomaker USB2CAN) connected to the E3 CAN bus.
- The CAN interface must be **up at 250 kbit/s**. This integration does not configure the interface. If you run the [open3e app](https://github.com/flecke-m/ha-addons/tree/main/open3e), it already does this. Otherwise: `ip link set can0 up type can bitrate 250000`.
- Home Assistant OS or another installation where Home Assistant can see the CAN interface (host network).

## Installation

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/christiangoltz/ha-e3oncan` as *Integration*.
2. Install **E3onCAN**, restart Home Assistant.
3. *Settings → Devices & services → Add integration → E3onCAN*.
4. Choose the device type and CAN interface. Add one entry per device you want to listen to.

## Finding out what your bus broadcasts

Add an entry with device type **Bus scan**. It listens to all CAN IDs and creates one diagnostic sensor per CAN ID that carries Collect data, listing the data points seen there (attribute `data_points`), plus *Active CAN IDs* with frame counts per ID. Use it to pick the right CAN ID for each device, then remove the scan entry.

## What you get

- Sensors are **created automatically** as data points arrive, with units, device and state classes (power, energy, temperature, …), so they work in the energy dashboard.
- Raw/unknown parts, enum IDs and month/year matrices are created **disabled** – enable them if you need them. Bus topology data is not exposed at all.
- Diagnostic sensors: *CAN frames received* and *Unknown data points* (DIDs on the bus without a codec, with their raw data as attribute – useful for improving the definitions upstream).
- Option *minimum time between updates of a data point* (default 10 s) keeps the database small; devices repeat their data many times per minute.

## Notes

- Entity names are derived from the open3e data point names (English).
- The data point tables are a snapshot of E3onCAN; see `custom_components/e3oncan/e3/__init__.py` for the commit.

## License

Apache License 2.0 – see [LICENSE](LICENSE) and [NOTICE](NOTICE).
