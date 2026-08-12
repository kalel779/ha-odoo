"""DataUpdateCoordinator: queries Odoo and computes revenue / counters."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_AMOUNT,
    ATTR_CUSTOMER,
    ATTR_DATETIME,
    ATTR_ORDER_REF,
    ATTR_ORDER_TYPE,
    ATTR_TIME,
    COUNT_PERIODS,
    DOMAIN,
    PERIODS,
    POS_ORDER_STATES,
    SALE_ORDER_STATES,
    SOURCE_POS,
    SOURCE_TOTAL,
    SOURCE_WEBSITE,
)
from .odoo_client import OdooClient, OdooConnectionError
from .period_utils import period_domain

_LOGGER = logging.getLogger(__name__)


@dataclass
class OdooSalesData:
    """Data produced on every refresh cycle."""

    revenue: dict[str, dict[str, float]] = field(default_factory=dict)
    order_count: dict[str, int] = field(default_factory=dict)
    last_order: dict[str, Any] | None = None
    orders_to_process: int = 0


class OdooSalesCoordinator(DataUpdateCoordinator[OdooSalesData]):
    """Periodic update coordinator for the sales module."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OdooClient,
        amount_type: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.client = client
        self.amount_type = amount_type  # "tax_incl" or "tax_excl"

    async def _async_update_data(self) -> OdooSalesData:
        try:
            return await self.hass.async_add_executor_job(self._fetch_all)
        except OdooConnectionError as err:
            raise UpdateFailed(f"Error connecting to Odoo: {err}") from err

    # -- blocking calls executed in the executor -----------------------------

    def _pos_revenue(self, period: str) -> float:
        domain = [("state", "in", POS_ORDER_STATES)] + period_domain(
            period, "date_order"
        )
        total = self.client.sum_field("pos.order", domain, "amount_total")
        if self.amount_type == "tax_excl":
            tax = self.client.sum_field("pos.order", domain, "amount_tax")
            return round(total - tax, 2)
        return round(total, 2)

    def _website_revenue(self, period: str) -> float:
        domain = [
            ("state", "in", SALE_ORDER_STATES),
            ("website_id", "!=", False),
        ] + period_domain(period, "date_order")
        field_name = (
            "amount_total" if self.amount_type == "tax_incl" else "amount_untaxed"
        )
        return round(self.client.sum_field("sale.order", domain, field_name), 2)

    def _website_order_count(self, period: str) -> int:
        domain = [
            ("state", "in", SALE_ORDER_STATES),
            ("website_id", "!=", False),
        ] + period_domain(period, "date_order")
        return self.client.search_count("sale.order", domain)

    def _orders_to_process(self) -> int:
        """Customer orders that still have an open Activity attached.

        Matches the user's Odoo workflow: an automation adds an Activity
        (activity_ids) on the sale.order as soon as the customer pays.
        Counting orders with a non-empty activity_ids therefore reflects
        "orders that still need to be processed", regardless of their
        sales state. Cancelled orders are excluded.
        """
        domain = [("activity_ids", "!=", False), ("state", "!=", "cancel")]
        return self.client.search_count("sale.order", domain)

    def _last_order(self) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []

        pos_rows = self.client.search_read(
            "pos.order",
            [("state", "in", POS_ORDER_STATES)],
            ["name", "amount_total", "date_order", "partner_id"],
            order="date_order desc",
            limit=1,
        )
        for row in pos_rows:
            candidates.append(
                {
                    ATTR_ORDER_TYPE: "pos",
                    ATTR_ORDER_REF: row.get("name"),
                    ATTR_CUSTOMER: (row.get("partner_id") or [None, "Walk-in customer"])[1],
                    ATTR_AMOUNT: row.get("amount_total"),
                    "date_order": row.get("date_order"),
                }
            )

        sale_rows = self.client.search_read(
            "sale.order",
            [("state", "in", SALE_ORDER_STATES), ("website_id", "!=", False)],
            ["name", "amount_total", "date_order", "partner_id"],
            order="date_order desc",
            limit=1,
        )
        for row in sale_rows:
            candidates.append(
                {
                    ATTR_ORDER_TYPE: "website",
                    ATTR_ORDER_REF: row.get("name"),
                    ATTR_CUSTOMER: (row.get("partner_id") or [None, "Web customer"])[1],
                    ATTR_AMOUNT: row.get("amount_total"),
                    "date_order": row.get("date_order"),
                }
            )

        if not candidates:
            return None

        latest = max(candidates, key=lambda c: c["date_order"] or "")
        latest = dict(latest)
        odoo_dt = latest.pop("date_order")
        latest[ATTR_DATETIME] = odoo_dt
        latest[ATTR_TIME] = odoo_dt.split(" ")[1] if odoo_dt and " " in odoo_dt else odoo_dt
        return latest

    def _fetch_all(self) -> OdooSalesData:
        revenue: dict[str, dict[str, float]] = {
            SOURCE_POS: {},
            SOURCE_WEBSITE: {},
            SOURCE_TOTAL: {},
        }
        for period in PERIODS:
            pos_value = self._pos_revenue(period)
            website_value = self._website_revenue(period)
            revenue[SOURCE_POS][period] = pos_value
            revenue[SOURCE_WEBSITE][period] = website_value
            revenue[SOURCE_TOTAL][period] = round(pos_value + website_value, 2)

        order_count = {
            period: self._website_order_count(period) for period in COUNT_PERIODS
        }

        last_order = self._last_order()
        orders_to_process = self._orders_to_process()

        return OdooSalesData(
            revenue=revenue,
            order_count=order_count,
            last_order=last_order,
            orders_to_process=orders_to_process,
        )
