# Odoo — Home Assistant integration

Exposes Odoo sales data in Home Assistant: revenue, order counts, and
real-time new-order notifications (POS sales + website / eCommerce sales).

Built to grow beyond sales into other Odoo areas over time (inventory,
purchasing, accounting…) — the current release ships the sales module.

## Entities created

**Revenue** — 3 sources × 6 periods = 18 sensors:
- Sources: `POS`, `Website`, `Total`
- Periods: `Today`, `Yesterday`, `This Week`, `This Month`, `This Quarter`, `This Year`
- e.g. `sensor.odoo_revenue_pos_today`

**Website order count** — 4 sensors:
- `Today`, `This Month`, `This Quarter`, `This Year`

**Orders to process**
- `sensor.odoo_orders_to_process`: confirmed website orders not yet
  locked/closed in Odoo (a live snapshot, not tied to a period).

**Last order**
- `sensor.odoo_last_order`: state = amount of the last order (POS or
  website). Attributes: `reference`, `customer`, `type`, `datetime`, `time`.
- Updated on every polling cycle **and** instantly via the webhook.

**New order (real time)**
- `binary_sensor.odoo_new_order`: turns `on` as soon as the Odoo webhook is
  received, turns back `off` after a configurable delay (30 s by default).
  Perfect for triggering an automation (notification, sound, light…).
- An `odoo_new_order` event is also fired with the same attributes, usable
  directly as an automation event trigger (no dependency on the
  binary_sensor).

All entities belong to a single "Odoo" device in Home Assistant.

## Installation via HACS

1. Push this folder (`odoo_repo`) as-is to a GitHub repository (keep
   `custom_components/odoo/` at that exact path, with `hacs.json` at the
   repo root).
2. In Home Assistant: **HACS > (⋮ menu) > Custom repositories**, add the
   repository URL, category **Integration**.
3. Search for "Odoo" in HACS and install it.
4. Restart Home Assistant.
5. **Settings > Devices & Services > Add Integration** → search for "Odoo".

*(Without HACS: just copy `custom_components/odoo` into
`config/custom_components/` and restart.)*

## Configuration

You'll need an **Odoo API key** (not your password):
Odoo > profile icon > **Preferences** > **Account Security** > **API Keys**
> New API Key.

Fill in the integration setup form with:
- Odoo URL (e.g. `https://mysite.odoo.com`)
- Database name
- Username / e-mail
- API key
- Currency (e.g. `EUR`)
- Amounts in tax-included or tax-excluded

Options (editable later via the "Configure" button on the integration):
- **Revenue refresh interval** (default: 15 min / 900 s, minimum 60 s) —
  tune this to avoid hammering your Odoo instance.
- **"New Order" binary_sensor active duration** (default: 30 s)

## Webhook — real-time new-order notification

When the integration is added, a **persistent notification** in Home
Assistant shows the webhook URL to configure on the Odoo side:

```
https://<your-home-assistant>/api/webhook/<generated-id>
```

### Odoo-side setup (works on every version)

Create an **Automated Action** (Settings > Technical > Automation >
Automated Actions, developer mode required):

- **Model**: `Sales Order` (`sale.order`) — duplicate the action for
  `Point of Sale Order` (`pos.order`) if you also want in-store sales.
- **Trigger**: on creation, or on update with condition "State = Confirmed".
- **Action to Do**: "Execute Python Code", for example:

```python
import requests

WEBHOOK_URL = "https://<your-home-assistant>/api/webhook/<generated-id>"

for order in records:
    payload = {
        "type": "website" if order._name == "sale.order" else "pos",
        "reference": order.name,
        "customer": order.partner_id.name,
        "amount": order.amount_total,
        "datetime": (order.date_order or fields.Datetime.now()).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception:
        pass
```

> Odoo 17+ has a native "Outgoing Webhook" trigger type in Automations,
> which avoids writing Python code — configure it with the same URL and an
> equivalent JSON body (`reference`, `customer`, `amount`, `datetime`,
> `type`).

The endpoint also accepts a plain `amount_total` instead of `amount`
(compatible with a raw Odoo export).

## Technical notes

- Connects via Odoo's **standard XML-RPC API** (`/xmlrpc/2/common` and
  `/xmlrpc/2/object`): no third-party module to install on the Odoo side.
- "Website" revenue filters `sale.order` records with `website_id` set and
  state `Confirmed`/`Locked`. "POS" revenue filters `pos.order` records
  that are paid/done/invoiced.
- Sums are computed server-side in Odoo via `read_group` (no transfer of
  individual order lines).
