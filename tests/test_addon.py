"""Minimal unit tests for the checkout addon."""

from app.addons.payments.checkout.addon import CheckoutAddon


def test_addon_identity():
    assert CheckoutAddon.addon_id == "checkout"
    assert CheckoutAddon.addon_category == "payment"
