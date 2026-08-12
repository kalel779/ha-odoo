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
from .odoo_client import OdooClient, OdooConnectionError

# Fields fetched back from Odoo to enrich a webhook payload, per model.
_ENRICH_FIELDS = ["display_name", "amount_total", "date_order", "partner_id"]
_MODEL_TO_TYPE = {"sale.order": "website", "pos.order": "pos"}

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

        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        coordinator = entry_data.get("coordinator")

        order = None
        record_id = payload.get("id") or payload.get("_id")
        model = payload.get("_model")
        if coordinator is not None and record_id and model:
            try:
                order = await hass.async_add_executor_job(
                    _fetch_order_from_odoo, coordinator.client, model, int(record_id)
                )
            except (OdooConnectionError, ValueError, TypeError):
                _LOGGER.warning(
                    "Could not fetch order #%s from Odoo to enrich the webhook, "
                    "falling back to the raw payload",
                    record_id,
                    exc_info=True,
                )

        if order is None:
            # Fallback: parse whatever Odoo put directly in the payload
            # (used by the "Execute Python Code" automation approach, or if
            # the Odoo call above failed).
            order = _normalize_payload(payload)

        if order is None:
            _LOGGER.warning("Received an Odoo webhook without a usable amount: %s", payload)
            return web.Response(status=400, text="missing 'amount'")

        _LOGGER.debug("New order received via webhook: %s", order)

        # Instantly update the "Last Order" sensor if possible.
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


def _fetch_order_from_odoo(client: OdooClient, model: str, record_id: int) -> dict | None:
    """Re-read the order straight from Odoo via XML-RPC (blocking call).

    Used instead of trusting the webhook payload's field values, because
    Odoo's native "Send a webhook notification" action does not reliably
    resolve many2one fields (e.g. partner_id) to a display name — it may
    just send the raw ID. XML-RPC's search_read always returns many2one
    fields as [id, "Display Name"], which _unwrap() then resolves.
    """
    if model not in _MODEL_TO_TYPE:
        return None

    rows = client.search_read(
        model, [("id", "=", record_id)], _ENRICH_FIELDS, limit=1
    )
    if not rows:
        return None

    row = rows[0]
    order_datetime = row.get("date_order") or dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
    order_time = (
        order_datetime.split(" ")[1] if " " in str(order_datetime) else str(order_datetime)
    )

    return {
        ATTR_ORDER_TYPE: _MODEL_TO_TYPE[model],
        ATTR_ORDER_REF: row.get("display_name"),
        ATTR_CUSTOMER: _unwrap(row.get("partner_id")),
        ATTR_AMOUNT: row.get("amount_total"),
        ATTR_DATETIME: order_datetime,
        ATTR_TIME: order_time,
    }


def _unwrap(value):
    """Odoo many2one fields are often sent as [id, "Display Name"]; keep the name."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return value[1]
    return value


def _first_value(payload: dict, *keys: str):
    """Return the first non-empty value found among the given payload keys."""
    for key in keys:
        if key in payload and payload[key] not in (None, "", False):
            return _unwrap(payload[key])
    return None


def _normalize_payload(payload: dict) -> dict | None:
    """Normalize the JSON sent by Odoo into the internal attribute format.

    Supports two payload shapes:
    - The custom JSON documented in the README (amount/reference/customer/
      datetime/type), used with a "Execute Python Code" automation action.
    - Odoo's native "Send a webhook notification" automation action, whose
      payload always includes _model/_action/id plus whatever fields were
      picked in the "Fields" selector, under their raw technical name
      (e.g. amount_paid, amount_total, name, partner_id, date_order...).
    """
    raw_amount = _first_value(
        payload, ATTR_AMOUNT, "amount", "amount_total", "amount_paid"
    )
    if raw_amount is None:
        return None

    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        return None

    order_datetime = _first_value(
        payload, ATTR_DATETIME, "datetime", "date_order", "create_date"
    )
    if not order_datetime:
        order_datetime = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

    order_time = (
        order_datetime.split(" ")[1] if " " in str(order_datetime) else str(order_datetime)
    )

    order_type = _first_value(payload, ATTR_ORDER_TYPE, "type", "type_name")
    if not order_type:
        model = payload.get("_model")
        order_type = {"sale.order": "website", "pos.order": "pos"}.get(model, "unknown")

    return {
        ATTR_ORDER_TYPE: order_type,
        ATTR_ORDER_REF: _first_value(
            payload, ATTR_ORDER_REF, "reference", "display_name", "name"
        )
        or payload.get("id"),
        ATTR_CUSTOMER: _first_value(
            payload, ATTR_CUSTOMER, "customer", "partner_name", "partner_id"
        ),
        ATTR_AMOUNT: amount,
        ATTR_DATETIME: order_datetime,
        ATTR_TIME: order_time,
    }
