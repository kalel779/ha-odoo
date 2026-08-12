"""Odoo sensors: revenue, order counts, last order."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AMOUNT,
    ATTR_CUSTOMER,
    ATTR_DATETIME,
    ATTR_ORDER_REF,
    ATTR_ORDER_TYPE,
    ATTR_TIME,
    CONF_CURRENCY,
    COUNT_PERIODS,
    DEFAULT_CURRENCY,
    DOMAIN,
    PERIOD_LABELS,
    PERIODS,
    SOURCE_LABELS,
    SOURCES,
)
from .coordinator import OdooSalesCoordinator


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Odoo",
        manufacturer="Odoo",
        model="Sales module (XML-RPC)",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: OdooSalesCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    currency = entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)

    entities: list[SensorEntity] = []

    for source in SOURCES:
        for period in PERIODS:
            entities.append(
                OdooRevenueSensor(coordinator, entry, source, period, currency)
            )

    for period in COUNT_PERIODS:
        entities.append(OdooOrderCountSensor(coordinator, entry, period))

    last_order_sensor = OdooLastOrderSensor(coordinator, entry, currency)
    entities.append(last_order_sensor)
    entities.append(OdooOrdersToProcessSensor(coordinator, entry))

    async_add_entities(entities)

    # Kept so the webhook handler (__init__.py) can push an immediate update
    # without waiting for the next polling cycle.
    hass.data[DOMAIN][entry.entry_id]["last_order_entity"] = last_order_sensor


class OdooRevenueSensor(CoordinatorEntity[OdooSalesCoordinator], SensorEntity):
    """Revenue sensor for a given source and period."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: OdooSalesCoordinator,
        entry: ConfigEntry,
        source: str,
        period: str,
        currency: str,
    ) -> None:
        super().__init__(coordinator)
        self._source = source
        self._period = period
        self.entity_description = SensorEntityDescription(
            key=f"revenue_{source}_{period}",
            name=f"Revenue {SOURCE_LABELS[source]} {PERIOD_LABELS[period]}",
        )
        self._attr_unique_id = f"{entry.entry_id}_revenue_{source}_{period}"
        self._attr_native_unit_of_measurement = currency
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.revenue.get(self._source, {}).get(self._period)


class OdooOrderCountSensor(CoordinatorEntity[OdooSalesCoordinator], SensorEntity):
    """Number of website orders for a given period."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "orders"
    _attr_icon = "mdi:cart-check"

    def __init__(
        self, coordinator: OdooSalesCoordinator, entry: ConfigEntry, period: str
    ) -> None:
        super().__init__(coordinator)
        self._period = period
        self.entity_description = SensorEntityDescription(
            key=f"order_count_website_{period}",
            name=f"Website Orders {PERIOD_LABELS[period]}",
        )
        self._attr_unique_id = f"{entry.entry_id}_order_count_website_{period}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.order_count.get(self._period)


class OdooLastOrderSensor(CoordinatorEntity[OdooSalesCoordinator], SensorEntity):
    """Last order received (POS or website): amount, time, customer…

    Updated on every polling cycle AND instantly when an Odoo webhook is
    received (see __init__.py).
    """

    _attr_has_entity_name = True
    _attr_name = "Last Order"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cart-arrow-down"

    def __init__(
        self, coordinator: OdooSalesCoordinator, entry: ConfigEntry, currency: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_last_order"
        self._attr_native_unit_of_measurement = currency
        self._attr_device_info = _device_info(entry)
        self._override: dict | None = None

    def push_order(self, order: dict) -> None:
        """Called from the webhook handler to update the state instantly."""
        self._override = order
        self.async_write_ha_state()

    @property
    def _order(self) -> dict | None:
        if self._override is not None:
            return self._override
        if self.coordinator.data:
            return self.coordinator.data.last_order
        return None

    @property
    def native_value(self) -> float | None:
        order = self._order
        return order.get(ATTR_AMOUNT) if order else None

    @property
    def extra_state_attributes(self) -> dict:
        order = self._order
        if not order:
            return {}
        return {
            ATTR_ORDER_TYPE: order.get(ATTR_ORDER_TYPE),
            ATTR_ORDER_REF: order.get(ATTR_ORDER_REF),
            ATTR_CUSTOMER: order.get(ATTR_CUSTOMER),
            ATTR_DATETIME: order.get(ATTR_DATETIME),
            ATTR_TIME: order.get(ATTR_TIME),
        }

    def _handle_coordinator_update(self) -> None:
        # Polling remains the background source of truth; the webhook
        # override is cleared on the next successful full refresh.
        self._override = None
        super()._handle_coordinator_update()


class OdooOrdersToProcessSensor(CoordinatorEntity[OdooSalesCoordinator], SensorEntity):
    """Number of confirmed website orders still awaiting processing."""

    _attr_has_entity_name = True
    _attr_name = "Orders To Process"
    _attr_native_unit_of_measurement = "orders"
    _attr_icon = "mdi:truck-fast-outline"

    def __init__(self, coordinator: OdooSalesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_orders_to_process"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.orders_to_process
