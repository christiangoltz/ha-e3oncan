"""Config flow for E3onCAN."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .collector import check_interface
from .const import (
    CONF_CAN_ID,
    CONF_CAN_INTERFACE,
    CONF_DEVICE,
    CONF_MIN_INTERVAL,
    DEFAULT_CAN_INTERFACE,
    DEFAULT_MIN_INTERVAL,
    DEVICE_E380,
    DEVICE_E3100CB,
    DEVICE_NAMES,
    DEVICE_VX3,
    DEVICES,
    DOMAIN,
    E3_DEFAULT_CAN_ID,
)

_LOGGER = logging.getLogger(__name__)

_INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=3600, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
    )
)


def _parse_can_id(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    can_id = int(value, 0)
    if not 0 <= can_id <= 0x7FF:
        raise ValueError(value)
    return can_id


class E3onCANConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up listening for one device type on one CAN interface."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input[CONF_DEVICE]
            interface = user_input[CONF_CAN_INTERFACE].strip()
            can_id: int | None = None
            try:
                can_id = _parse_can_id(user_input.get(CONF_CAN_ID, ""))
            except ValueError:
                errors[CONF_CAN_ID] = "invalid_can_id"
            if can_id is not None and device in (DEVICE_E380, DEVICE_E3100CB):
                errors[CONF_CAN_ID] = "can_id_not_allowed"

            if not errors:
                try:
                    await self.hass.async_add_executor_job(check_interface, interface)
                except Exception as err:  # noqa: BLE001 - python-can raises various errors
                    _LOGGER.warning("Cannot open CAN interface %s: %s", interface, err)
                    errors["base"] = "cannot_connect"

            if not errors:
                effective_id = can_id if can_id is not None else E3_DEFAULT_CAN_ID.get(device)
                suffix = f"_{effective_id:#05x}" if effective_id is not None else ""
                await self.async_set_unique_id(f"{interface}_{device}{suffix}")
                self._abort_if_unique_id_configured()
                data = {CONF_CAN_INTERFACE: interface, CONF_DEVICE: device}
                if can_id is not None:
                    data[CONF_CAN_ID] = hex(can_id)
                return self.async_create_entry(
                    title=f"{DEVICE_NAMES[device]} ({interface})",
                    data=data,
                    options={CONF_MIN_INTERVAL: int(user_input[CONF_MIN_INTERVAL])},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE, default=DEVICE_VX3): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DEVICES,
                        translation_key="device",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_CAN_INTERFACE, default=DEFAULT_CAN_INTERFACE): str,
                vol.Optional(CONF_CAN_ID, default=""): str,
                vol.Required(CONF_MIN_INTERVAL, default=DEFAULT_MIN_INTERVAL): _INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> E3onCANOptionsFlow:
        return E3onCANOptionsFlow()


class E3onCANOptionsFlow(OptionsFlow):
    """Change how often a data point may update."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_MIN_INTERVAL: int(user_input[CONF_MIN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_MIN_INTERVAL, default=current): _INTERVAL_SELECTOR}
            ),
        )
