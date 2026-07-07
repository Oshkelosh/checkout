"""Checkout.com addon routes — thin delegates to shared payment route factory."""

from __future__ import annotations

from typing import Any

from app.addons.payments.shared_routes import build_payment_routers


def _parse_checkout_config_form(form: Any) -> tuple[dict[str, Any], bool]:
    return (
        {
            "secret_key": form.get("secret_key", ""),
            "webhook_secret": form.get("webhook_secret", ""),
            "processing_channel_id": form.get("processing_channel_id", ""),
            "environment": form.get("environment", "sandbox"),
            "success_url": form.get("success_url", ""),
            "failure_url": form.get("failure_url", ""),
        },
        form.get("is_enabled") == "on",
    )


admin_router, api_router, jinja_env = build_payment_routers(
    "checkout",
    template_name="checkout_config.html",
    page_title="Checkout.com Settings",
    secret_keys=("secret_key", "webhook_secret"),
    signature_header="cko-signature",
    parse_config_form=_parse_checkout_config_form,
)
