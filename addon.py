"""
Checkout.com payment integration.

Collects payments via Checkout.com payment sessions and handles webhooks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import effective_redirect_url, extract_order_id, mock_checkout
from schemas.payment import PaymentWebhookOutcome
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config

CheckoutEnvironment = Literal["sandbox", "live"]

_API_BASES: dict[CheckoutEnvironment, str] = {
    "sandbox": "https://api.sandbox.checkout.com",
    "live": "https://api.checkout.com",
}


class CheckoutConfig(BaseModel):
    secret_key: SecretStr = Field(default=..., description="Checkout.com secret API key")
    webhook_secret: SecretStr = Field(
        default=...,
        description="Webhook signature key",
    )
    processing_channel_id: str = Field(
        default=...,
        description="Processing channel ID for payments",
    )
    environment: CheckoutEnvironment = Field(default="sandbox")
    success_url: str = Field(
        default="",
        description="Optional override for success redirect (leave blank to use Site URL)",
    )
    failure_url: str = Field(
        default="",
        description="Optional override for failure/cancel redirect (leave blank to use Site URL)",
    )

    @classmethod
    def config_model(cls):
        return cls


class CheckoutAddon(PaymentAddon):
    addon_id: str = "checkout"
    addon_name: str = "Checkout.com"
    addon_description: str = "Accept payments via Checkout.com."
    addon_category: str = "payment"
    version: str = "1.0.0"
    is_enabled: bool = False

    _config: Dict[str, Any] | None = None
    _secret_key: str | None = None
    _webhook_secret: str | None = None
    _processing_channel_id: str | None = None
    _environment: CheckoutEnvironment = "sandbox"
    _success_url: str = ""
    _failure_url: str = ""
    _api_base: str = _API_BASES["sandbox"]

    @classmethod
    def config_schema(cls):
        return CheckoutConfig

    async def initialize(self, config: dict) -> None:
        validated = self.config_schema()(**config)
        self._config = dump_addon_config(validated)
        self._secret_key = validated.secret_key.get_secret_value()
        self._webhook_secret = validated.webhook_secret.get_secret_value()
        self._processing_channel_id = validated.processing_channel_id
        self._environment = validated.environment
        self._success_url = validated.success_url
        self._failure_url = validated.failure_url
        self._api_base = _API_BASES[self._environment]
        self.is_enabled = True
        info("Checkout", "Initialized (environment={})", self._environment)

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        secret_key = validated.secret_key.get_secret_value()
        if not secret_key:
            return
        api_base = _API_BASES[validated.environment]
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base}/payments",
                headers={"Authorization": f"Bearer {secret_key}"},
                params={"limit": 1},
            )
        if resp.status_code == 401:
            raise ValidationError(message="Invalid secret key — check your credentials")
        if resp.status_code == 403:
            raise ValidationError(
                message="Secret key is valid but missing required permissions: payments:read"
            )
        if resp.status_code >= 400:
            raise ValidationError(message="Checkout.com rejected the secret key")

    async def shutdown(self) -> None:
        self._secret_key = None
        self._webhook_secret = None
        self.is_enabled = False

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        *,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Dict[str, Any]:
        if not self._secret_key or not self._processing_channel_id:
            return mock_checkout("checkout", order_id, amount, currency)

        body: dict[str, Any] = {
            "amount": amount,
            "currency": currency.upper(),
            "reference": order_id,
            "processing_channel_id": self._processing_channel_id,
            "success_url": effective_redirect_url(
                self._success_url, fallback=return_url or ""
            ),
            "failure_url": effective_redirect_url(
                self._failure_url, fallback=cancel_url or ""
            ),
            "metadata": {"order_id": order_id},
        }
        if customer_email:
            body["customer"] = {"email": customer_email}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self._api_base}/payment-sessions",
                    headers=self._auth_headers(),
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                session_id = data.get("id", "")
                return {
                    "success": True,
                    "payment_id": session_id,
                    "session_id": session_id,
                    "url": data.get("_links", {}).get("redirect", {}).get("href", ""),
                    "order_id": order_id,
                }
        except Exception as exc:
            warning("Checkout", "create_payment error: {}", exc)
            return mock_checkout("checkout", order_id, amount, currency)

    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        status = await self.get_payment_status(payment_id)
        if status.get("status") == "error":
            return {"success": False, "error": status.get("detail", "Unknown error")}
        return {
            "success": True,
            "payment_id": payment_id,
            "status": status.get("status", "unknown"),
            "amount": status.get("amount", 0),
        }

    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        if not self._secret_key:
            return {"success": False, "error": "Checkout.com credentials not configured"}

        body = {"amount": amount, "reference": f"refund_{payment_id}"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self._api_base}/payments/{payment_id}/refunds",
                    headers=self._auth_headers(),
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "success": True,
                    "refund_id": data.get("action_id", data.get("id", "")),
                    "amount": amount,
                    "status": data.get("status", "Pending"),
                }
        except Exception as exc:
            warning("Checkout", "refund_payment({}) error: {}", payment_id, exc)
            return {"success": False, "error": str(exc)}

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not self._secret_key:
            return {"payment_id": payment_id, "status": "error", "detail": "Not configured"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{self._api_base}/payments/{payment_id}",
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "payment_id": payment_id,
                    "status": data.get("status", "unknown"),
                    "amount": data.get("amount", 0),
                    "currency": data.get("currency", "usd"),
                }
        except Exception as exc:
            warning("Checkout", "get_payment_status({}) error: {}", payment_id, exc)
            return {"payment_id": payment_id, "status": "error", "detail": str(exc)}

    def webhook_signature_header(self) -> str:
        return "cko-signature"

    async def parse_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> PaymentWebhookOutcome:
        try:
            event_type = payload.get("type", "")
            event_data = payload.get("data", payload)
            event_id = str(payload.get("id", event_data.get("id", "")))
            info("Checkout", "Webhook received: {}", event_type)

            if event_type in ("payment_approved", "payment_captured"):
                order_id = extract_order_id(event_data.get("metadata"))
                payment_id = event_data.get("id") or event_data.get("payment_id")
                return PaymentWebhookOutcome(
                    handled=True,
                    event_id=event_id,
                    event_type=event_type,
                    mark_paid=order_id is not None,
                    order_id=order_id,
                    payment_id=str(payment_id) if payment_id else None,
                )

            return PaymentWebhookOutcome(
                handled=True,
                event_id=event_id,
                event_type=event_type,
            )
        except Exception as exc:
            warning("Checkout", "parse_webhook error: {}", exc)
            return PaymentWebhookOutcome(handled=False, error=str(exc))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.payments.checkout.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.payments.checkout.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
