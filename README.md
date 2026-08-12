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
- `sensor.odoo_orders_to_process`: customer orders (`sale.order`, any
  channel) that still have an open **Activity** attached, excluding
  cancelled orders (a live snapshot, not tied to a period). This matches a
  workflow where an Odoo automation adds an Activity on the order as soon
  as the customer pays — the activity is cleared once the order has been
  processed/shipped.
- By default this counts orders with **any** open activity. If you also use
  Odoo Activities for unrelated things (calls, follow-ups…), set the
  **"Activity summary to match"** option (see Options below) to the exact
  Summary text your automation uses (e.g. `Nouvelle commande à traiter`) so
  only that specific activity is counted.

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
- **Activity summary to match** for "Orders to process" (default: empty =
  any activity counts)

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

> Odoo 17+ has a native **"Send a webhook notification"** action in
> Automation Rules, which avoids writing Python code entirely. Every
> webhook triggered this way automatically includes `_model` and `id` —
> that's all the integration needs: on receipt, it calls back to Odoo via
> XML-RPC using that `id` to fetch the order's reference, customer name,
> amount and date directly (`search_read`), rather than trusting whatever
> Odoo serialized in the JSON body. This avoids relying on how Odoo
> formats a many2one field like `partner_id` in the payload (it may send a
> raw ID instead of a resolved name).
>
> You can still add fields under **Fields** (e.g. `amount_paid`) — they're
> only used as a fallback if the callback to Odoo fails (network issue,
> wrong credentials, etc.).

The endpoint also accepts a plain `amount_total` or `amount_paid` instead
of `amount` (compatible with a raw Odoo export or as a fallback for the
native webhook action).

## Example: mobile notification on new order

Once the webhook is wired up, create a Home Assistant automation that
listens to the `odoo_new_order` event and sends a notification with the
order amount:

```yaml
alias: "Odoo – notify on new order"
trigger:
  - platform: event
    event_type: odoo_new_order
action:
  - service: notify.mobile_app_<your_phone>
    data:
      title: "New order 🛒"
      message: >
        {{ trigger.event.data.amount }} {{ trigger.event.data.reference }}
        — {{ trigger.event.data.customer }} ({{ trigger.event.data.type }})
```

`trigger.event.data` contains `type`, `reference`, `customer`, `amount`,
`datetime` and `time` — whatever the webhook payload provided.

## Technical notes

- Connects via Odoo's **standard XML-RPC API** (`/xmlrpc/2/common` and
  `/xmlrpc/2/object`): no third-party module to install on the Odoo side.
- "Website" revenue filters `sale.order` records with `website_id` set and
  state `Confirmed`/`Locked`. "POS" revenue filters `pos.order` records
  that are paid/done/invoiced.
- Sums are computed server-side in Odoo via `read_group` (no transfer of
  individual order lines).
