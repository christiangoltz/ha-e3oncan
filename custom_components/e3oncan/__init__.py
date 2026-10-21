"""E3onCAN: passively read Viessmann E3 devices from the CAN bus."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .hub import E3Hub

PLATFORMS = [Platform.SENSOR]

type E3ConfigEntry = ConfigEntry[E3Hub]


async def async_setup_entry(hass: HomeAssistant, entry: E3ConfigEntry) -> bool:
    """Start listening on the CAN interface."""
    hub = await hass.async_add_executor_job(E3Hub, hass, entry)
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: E3ConfigEntry) -> bool:
    """Stop listening."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.stop)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: E3ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
