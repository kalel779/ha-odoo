"""Odoo Home Assistant integration: revenue, orders and real-time new-order notifications."""
from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components import persistent_notification, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

import homeassistant.util.dt as dt_util

from .const import (
    ATTR_AMOUNT,
    ATTR_CUSTOMER,
    ATTR_DATETIME,
    ATTR_ORDER_REF,
    ATTR_ORDER_TYPE,
    ATTR_TIME,
    CONF_AMOUNT_TYPE,
    CONF_API_KEY,
    CONF_DB,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_AMOUNT_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SIGNAL_NEW_ORDER,
)
from .coordinator import OdooSalesCoordinator
from .odoo_client import OdooClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the entry: Odoo client, coordinator, platforms and webhook."""
    client = OdooClient(
        entry.data[CONF_URL],
        entry.data[CONF_DB],
        entry.data[CONF_USERNAME],
        entry.data[CONF_API_KEY],
    )

    amount_type = entry.data.get(CONF_AMOUNT_TYPE, DEFAULT_AMOUNT_TYPE)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = OdooSalesCoordinator(hass, entry, client, amount_type, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_webhook(hass, entry)
    _notify_webhook_url(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _notify_webhook_url(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show the webhook URL in a persistent notification after (re)install."""
    base_url = hass.config.external_url or hass.config.internal_url or "https://YOUR-HOME-ASSISTANT"
    webhook_url = f"{base_url}/api/webhook/{entry.entry_id}"
    persistent_notification.async_create(
        hass,
        (
            f"Configure this webhook in Odoo to get new-order notifications "
            f"in real time:\n\n`{webhook_url}`\n\n"
            "See the Odoo integration README for the Odoo automation rule "
            "example to copy."
        ),
        title="Odoo – Webhook URL",
        notification_id=f"{DOMAIN}_{entry.entry_id}_webhook_url",
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    webhook.async_unregister(hass, entry.entry_id)

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the inbound webhook: /api/webhook/<entry_id>."""

    async def handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            _LOGGER.warning("Received an Odoo webhook with an invalid JSON body")
            return web.Response(status=400, text="invalid JSON")

        order = _normalize_payload(payload)
        if order is None:
            _LOGGER.warning("Received an Odoo webhook without a usable amount: %s", payload)
            return web.Response(status=400, text="missing 'amount'")

        _LOGGER.debug("New order received via webhook: %s", order)

        # Instantly update the "Last Order" sensor if possible.
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        last_order_entity = entry_data.get("last_order_entity")
        if last_order_entity is not None:
            last_order_entity.push_order(order)

        # Trigger the "New Order" binary_sensor.
        async_dispatcher_send(hass, f"{SIGNAL_NEW_ORDER}_{entry.entry_id}", order)

        # Generic HA event, usable in any automation.
        hass.bus.async_fire(f"{DOMAIN}_new_order", order)

        return web.Response(status=200, text="ok")

    webhook.async_register(
        hass,
        DOMAIN,
        "Odoo - new order",
        entry.entry_id,
        handle_webhook,
    )


def _normalize_payload(payload: dict) -> dict | None:
    """Normalize the JSON sent by Odoo into the internal attribute format."""
    if ATTR_AMOUNT not in payload and "amount_total" in payload:
        payload[ATTR_AMOUNT] = payload["amount_total"]

    if ATTR_AMOUNT not in payload:
        return None

    try:
        amount = float(payload[ATTR_AMOUNT])
    except (TypeError, ValueError):
        return None

    order_datetime = payload.get(ATTR_DATETIME) or payload.get("date_order")
    if not order_datetime:
        order_datetime = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

    order_time = (
        order_datetime.split(" ")[1] if " " in str(order_datetime) else str(order_datetime)
    )

    return {
        ATTR_ORDER_TYPE: payload.get(ATTR_ORDER_TYPE) or payload.get("type") or "unknown",
        ATTR_ORDER_REF: payload.get(ATTR_ORDER_REF)
        or payload.get("name")
        or payload.get("reference"),
        ATTR_CUSTOMER: payload.get(ATTR_CUSTOMER)
        or payload.get("partner_name")
        or payload.get("customer"),
        ATTR_AMOUNT: amount,
        ATTR_DATETIME: order_datetime,
        ATTR_TIME: order_time,
    }
