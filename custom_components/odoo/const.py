"""Constants for the Odoo integration."""
from __future__ import annotations

DOMAIN = "odoo"
PLATFORMS = ["sensor", "binary_sensor"]

# Configuration
CONF_URL = "url"
CONF_DB = "db"
CONF_USERNAME = "username"
CONF_API_KEY = "api_key"
CONF_CURRENCY = "currency"
CONF_AMOUNT_TYPE = "amount_type"  # "tax_incl" or "tax_excl"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_RESET_DELAY = "reset_delay"
CONF_ACTIVITY_KEYWORD = "activity_keyword"

DEFAULT_CURRENCY = "EUR"
DEFAULT_AMOUNT_TYPE = "tax_incl"
DEFAULT_SCAN_INTERVAL = 900  # seconds (15 min)
DEFAULT_RESET_DELAY = 30  # seconds before the binary_sensor turns back off
# Empty by default = count orders with ANY open activity. Set this (in the
# integration's options) to the exact "Summary" text your Odoo automation
# uses (e.g. "Nouvelle commande à traiter") to only count that specific
# activity instead of every activity ever logged on the order.
DEFAULT_ACTIVITY_KEYWORD = ""

AMOUNT_TYPES = ["tax_incl", "tax_excl"]

# Revenue sources
SOURCE_POS = "pos"
SOURCE_WEBSITE = "website"
SOURCE_TOTAL = "total"
SOURCES = [SOURCE_POS, SOURCE_WEBSITE, SOURCE_TOTAL]

SOURCE_LABELS = {
    SOURCE_POS: "POS",
    SOURCE_WEBSITE: "Website",
    SOURCE_TOTAL: "Total",
}

# Periods
PERIOD_TODAY = "today"
PERIOD_YESTERDAY = "yesterday"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_YEAR = "year"
PERIODS = [
    PERIOD_TODAY,
    PERIOD_YESTERDAY,
    PERIOD_WEEK,
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_YEAR,
]

PERIOD_LABELS = {
    PERIOD_TODAY: "Today",
    PERIOD_YESTERDAY: "Yesterday",
    PERIOD_WEEK: "This Week",
    PERIOD_MONTH: "This Month",
    PERIOD_QUARTER: "This Quarter",
    PERIOD_YEAR: "This Year",
}

# Periods for the website order-count sensors (explicitly requested:
# today / month / quarter / year — no yesterday or week)
COUNT_PERIODS = [PERIOD_TODAY, PERIOD_MONTH, PERIOD_QUARTER, PERIOD_YEAR]

# Odoo states considered "confirmed" / sold
POS_ORDER_STATES = ["paid", "done", "invoiced"]
SALE_ORDER_STATES = ["sale", "done"]

# Internal dispatcher signals
SIGNAL_NEW_ORDER = f"{DOMAIN}_new_order"

# Webhook
WEBHOOK_EVENT_NEW_ORDER = f"{DOMAIN}_new_order"

# Attributes exposed for the last order / webhook payload
ATTR_ORDER_TYPE = "type"
ATTR_ORDER_REF = "reference"
ATTR_CUSTOMER = "customer"
ATTR_AMOUNT = "amount"
ATTR_DATETIME = "datetime"
ATTR_TIME = "time"
