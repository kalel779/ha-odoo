"""Binary sensor: turns 'on' briefly when a new order arrives (webhook)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import CONF_RESET_DELAY, DEFAULT_RESET_DELAY, DOMAIN, SIGNAL_NEW_ORDER


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    reset_delay = entry.options.get(CONF_RESET_DELAY, DEFAULT_RESET_DELAY)
    async_add_entities([OdooNewOrderBinarySensor(entry, reset_delay)])


class OdooNewOrderBinarySensor(BinarySensorEntity):
    """Turns on when the Odoo webhook signals a new order."""

    _attr_has_entity_name = True
    _attr_name = "New Order"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bell-ring-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, reset_delay: int) -> None:
        self._entry = entry
        self._reset_delay = reset_delay
        self._attr_unique_id = f"{entry.entry_id}_new_order"
        self._attr_is_on = False
        self._unsub_reset = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Odoo",
            manufacturer="Odoo",
            model="Sales module (XML-RPC)",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_NEW_ORDER}_{self._entry.entry_id}",
                self._handle_new_order,
            )
        )

    @callback
    def _handle_new_order(self, _order: dict) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

        if self._unsub_reset:
            self._unsub_reset()

        @callback
        def _reset(_now) -> None:
            self._attr_is_on = False
            self._unsub_reset = None
            self.async_write_ha_state()

        self._unsub_reset = async_call_later(self.hass, self._reset_delay, _reset)
