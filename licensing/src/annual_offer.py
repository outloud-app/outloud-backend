"""New annual offer; legacy one-time licenses retain their original contract.

Use a standard 199.99 recurring Price and a currency-specific 100.00
amount-off Coupon with duration=once for the ten introductory purchases.
Stripe, rather than an application timer, collects subsequent annual invoices.
This module does not create live Stripe resources or alter legacy inventory.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

OFFER_ID = "outloud-annual-mvp-2026"
INTRO_CAPACITY = 10
INTRO_AMOUNT = 9999
ANNUAL_AMOUNT = 19999


@dataclass(frozen=True)
class AnnualCatalog:
    prices: dict[str, str]
    coupons: dict[str, str]

    def checkout(self, currency: str, introductory: bool, site: str, claim: str):
        if currency != "gbp":
            raise ValueError("Unsupported storefront currency")
        if not self.prices.get(currency) or (introductory and not self.coupons.get(currency)):
            raise ValueError("Annual Stripe catalog is not configured")
        parsed = urlsplit(site)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("A secure storefront URL is required")
        data = {
            "mode": "subscription",
            "adaptive_pricing[enabled]": "false",
            "line_items[0][price]": self.prices[currency],
            "line_items[0][quantity]": "1",
            "success_url": site.rstrip("/") + "/purchase/?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": site.rstrip("/") + "/#pricing",
            "client_reference_id": claim,
            "metadata[outloud_offer]": OFFER_ID,
            "subscription_data[metadata][outloud_offer]": OFFER_ID,
            "custom_text[submit][message]": (
                f"{'99.99' if introductory else '199.99'} {currency.upper()} for 12 months. "
                f"Renews automatically at 199.99 {currency.upper()}/year. Cancel before renewal."
            ),
        }
        if introductory:
            data["discounts[0][coupon]"] = self.coupons[currency]
        return data


def introductory_coupon(currency: str):
    if currency not in ("usd", "gbp", "eur"):
        raise ValueError("Unsupported storefront currency")
    return {"currency": currency, "amount_off": ANNUAL_AMOUNT - INTRO_AMOUNT,
            "duration": "once", "name": "Outloud first-year offer"}
