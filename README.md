# Checkout.com (`checkout`)

Accept payments via Checkout.com.

## Overview

| | |
|---|---|
| Addon ID | `checkout` |
| Category | payment |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Only **one** payment addon can be active at a time.

## Enable and configure

1. Install this package under `app/addons/payments/checkout/`
2. Open **Admin → Payments → Checkout.com** at `/admin/payments/checkout`
3. Enter credentials and enable **Enable this payment processor**

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `secret_key` | secret | Checkout.com secret API key |
| `webhook_secret` | secret | Webhook signing secret |
| `processing_channel_id` | string | Processing channel ID |
| `environment` | string | `sandbox` or `live` |
| `success_url` | string | Redirect on success |
| `failure_url` | string | Redirect on failure |

Secrets are stored in `addon_configs`, not in `.env`.

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/payments/checkout/checkout` | Start checkout (optional; prefer generic order checkout) |
| POST | `/api/v1/payments/checkout/webhook` | PSP webhook endpoint |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/payments/checkout` | Config form |
| POST | `/admin/payments/checkout/save` | Save config |

## Core integration

- **Storefront checkout:** `POST /api/v1/orders/{order_id}/checkout` → `PaymentAddon.create_payment()` → redirect URL
- **Webhook:** `POST /api/v1/payments/checkout/webhook` → `parse_webhook()` → core `process_payment_webhook()`
- **Amounts:** smallest currency unit (cents)

## Provider setup

Register webhook URL (replace `{PUBLIC_APP_URL}` with your public base URL):

```
{PUBLIC_APP_URL}/api/v1/payments/checkout/webhook
```

Webhook signature header: **`cko-signature`**

1. Obtain API keys from the Checkout.com Dashboard.
2. Register a webhook endpoint with the signing secret.
3. Set the processing channel ID for your account.

## Package layout

```
checkout/
├── README.md
├── addon.py
├── routes.py
└── templates/
```

## See also

- [Payment addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
