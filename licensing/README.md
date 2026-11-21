# Outloud licensing (FastAPI)

A separate sandbox service, built for Python Workers with D1. The existing local
workspace API remains unchanged. Live purchases are NOT switched to this service.

## Payment and license lifecycle

1. `POST /api/purchase/start` creates a Stripe-hosted one-time $99.99 Checkout.
   A random, HttpOnly browser claim cookie is bound to that Checkout in D1.
2. Stripe's signed webhook fulfills paid sessions, including delayed successful
   payments. Unique database constraints make issuance safe under retries.
3. The return page asks `GET /api/purchase/license?session_id=...`. The cookie
   must match. Stripe's server API confirms payment; a return URL alone proves
   nothing. This call also handles a return arriving before the webhook.
4. The buyer copies the key or downloads `Outloud-License.txt`. No email sender
   is needed. Unpaid, unrelated, wrong-mode and revoked payments reveal no key.
5. Keys are versioned HMAC-derived 120-bit pseudorandom values in the format
   `OL-XXXXXX-XXXXXX-XXXXXX-XXXXXX`. D1 stores only their SHA-256 hashes. Keep the
   issuer-v1 secret backed up securely: it reproduces original keys for recovery.
6. A pre-order is `reserved`; it does not unlock the app or start its year.
   The protected admin release operation marks actual usable-access delivery.
   It sets 12 calendar months once and does not extend dates on retries.
7. Activation checks the key online, status and expiry, with two installations
   allowed. The app stores only an opaque device session in macOS Keychain.
   Expired or revoked sessions fail online verification. No automatic renewal.
8. Full/partial refunds and disputes conservatively revoke the license. Risk
   events arriving before fulfillment also prevent a usable license.

## Recovery

Ask the buyer to email support from the receipt address with their Stripe receipt.
Verify the receipt/order in Stripe before using the admin recovery endpoint with
both the Checkout session ID and email. The endpoint requires ADMIN_SECRET and
returns the original key, not a newly issued license. Do not recover keys on the
basis of an email address alone. Never paste keys in shared logs.

## Configuration

Non-secret config lives in `wrangler.toml`; replace the placeholder database ID
before deploying. Run `uv sync`, then `uv run pywrangler dev` / `deploy`.
Local tools require Node/npm/npx and uv in PATH. The current development machine
uses a temporary npx shim to its existing, pinned Wrangler installation.

Secrets: STRIPE_SECRET_KEY (test restricted key preferred), STRIPE_WEBHOOK_SECRET,
LICENSE_ISSUER_V1, GATEWAY_SECRET and ADMIN_SECRET. Use Cloudflare secret storage.
Never add them to source or `NEXT_PUBLIC_*`. `.dev.vars` is ignored, mode 600.
The website needs matching LICENSE_GATEWAY_SECRET and LICENSE_SANDBOX service
binding. The public sandbox routes use this binding; app verification uses the
licensing Worker URL. Set SITE_URL to the exact deployed website origin.

`tools/configure_sandbox.py` accepts a test key using a hidden prompt, validates
Stripe's `livemode:false`, and creates ignored local secrets. Rotate the test
key shared in chat. Its publishable counterpart is unnecessary for hosted Checkout.
`tools/listen_sandbox.py` uses STRIPE_API_KEY in the child environment, forwards
signed test events locally and captures the signing secret without printing it.

## Checks

`uv run pytest -q` tests unpaid checkouts, cookie ownership, issuance/retries,
mode/amount validation, release dates, device limits, expiry and refund ordering.
Test cards belong only in sandbox: 4242 4242 4242 4242, future expiry, any CVC.

## Native app

`Licensing.swift` supplies activation and Keychain session storage. Manage License
opens it from workspace settings. Debug builds retain the existing local-workspace
preview and allow a test URL via OUTLOUD_LICENSE_API_URL. Release builds use the
license gate and require an HTTPS OutloudLicenseServerURL in the app bundle plus
`environment: live` from the server. No production endpoint is configured yet:
release builds fail closed until live licensing is configured and tested.

## Hosted sandbox (deployed 30 October 2026)

- Buyer test page: https://tryoutloud.pages.dev/checkout-test/
- FastAPI Worker: https://outloud-license-sandbox.wirebuilds-outloud.workers.dev
- D1: outloud-licenses-sandbox, isolated from live order storage.
- Signed Stripe sandbox webhook: /webhooks/stripe on the Worker.
- Website purchase buttons currently route to the clearly labelled test checkout.
- Hosted end-to-end checks passed: test card payment, browser-bound license
  download, reserved-before-release status, owner release, activation, online
  check, then a genuine test refund and signed-webhook revocation.
- Cloudflare stores the Worker and Pages gateway secrets. Local .dev.vars.remote
  is ignored and mode 600; never commit or print it. hosted-sandbox.json contains
  only the public URL, test mode and non-secret webhook endpoint ID.
- Account workers.dev namespace: wirebuilds-outloud (no custom domain required).

Before accepting real payments through this licensing flow, configure a separate
live service/database, live restricted key and webhook, then verify that flow.
The old live Payment Link still exists, but no website purchase button links to
it while testing. Native Release configuration still fails closed until its
production licensing endpoint is explicitly configured.

## Founding inventory (150 licenses)

Apply `inventory.sql` after `schema.sql` before deploying this version. It seeds
150 D1 slots and backfills existing non-refunded licenses. Checkout atomically
reserves a slot before calling Stripe, with a 31-minute Stripe expiry. Completed
payments mark that slot issued; duplicate events never consume another place.
Refunds/revocations return a place. Signed `checkout.session.expired` and
`checkout.session.async_payment_failed` events release unpaid holds. Never recycle
a hold using only a local clock: a late payment webhook may still arrive.

`GET /api/purchase/availability` is gateway-protected and exposed through the Pages
proxy. It returns total, issued, held and remaining counts, with no customer data.
The website refreshes it every five seconds and on focus. Server-side capacity is
authoritative even if a browser has stale data. Sandbox inventory is labelled as
test availability and must never be presented as real sales.

For a new live environment, create a separate D1 database and apply both SQL files;
do not copy test licenses or counters. Configure the matching live Stripe webhook
and secrets before changing purchase mode. The old live Payment Link does not
share this inventory; it must remain unlinked and be disabled before live launch.

The current website purchase buttons open hosted Stripe sandbox Checkout directly.
The early Mac root verifies a reserved license, persists a device token in Keychain
and shows only the launch countdown. It does not deliver the marketing workspace
or start the access year. The flat activation design is awaiting visual review;
no downloadable DMG with the rejected card design has been published.
