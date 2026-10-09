# Mirror App Store subscriptions

Prepared 2026-10-09. The purchase integration is implemented; live server configuration and end-to-end Sandbox validation remain.

## Confirmed product direction

- No Mirror account creation or custom password.
- Three subscription tiers: 1, 2 or 3 generations per day.
- Offer both monthly and weekly billing for each daily generation tier. Monthly price amounts, in tier order: 6.99 / 12.99 / 16.99. Weekly price amounts: 1.99 / 3.59 / 4.99. Base currency is confirmed as USD (US dollars).
- Monthly subscriptions offer an Apple-managed three-day introductory free trial to eligible customers after subscription consent, followed by automatic paid renewal. Weekly subscriptions have no introductory free trial and are charged upon purchase, then renew weekly.
- Keep photos and OpenAI credentials out of purchase metadata and the iPhone binary.

## Decisions needed before enabling purchases

- Tier display names. Base currency (USD), monthly and weekly billing periods and their price amounts are confirmed; daily generation limits are confirmed as 1 / 2 / 3.
- Monthly trial allowance is confirmed: same as the selected tier (1 / 2 / 3 generations per day). Weekly subscriptions have no trial.
- All six App Store Connect subscription product records have been created. The user confirmed prices and monthly trial offers are configured; remaining setup includes server credentials, availability verification and review materials. App record is confirmed: bundle identifier `com.makeuptutor.app`, Apple ID `6821052986`, SKU `mirror-ios-001`; subscription group ID `22459343`. Proposed product identifiers for creation are listed below.

## Account-free entitlement design

StoreKit provides App Store purchase transactions, not an application's general access to a person's Apple Account email or password. The customer uses the Apple purchase sheet; Mirror needs no signup screen. Anonymous purchase identity and an entitlement ledger are still needed on the backend.

For Apple-managed trials, put all six products (three allowance tiers, each with monthly and weekly billing) into one subscription group; rank the largest entitlement at level 1 and place both billing periods for the same allowance at the same subscription level. Configure three-day introductory offers only on the three monthly products in App Store Connect; configure no introductory offers on weekly products. Use StoreKit eligibility and localized product information. Eligibility applies across the group; changing tiers does not grant a second introductory trial. Never display a trial offer for ineligible customers. Read actual pricing and renewal periods from StoreKit rather than hardcoding displayed prices.

An app-managed signup-free trial is not part of the selected product direction. Do not start a trial merely on first app launch; require the Apple subscription purchase flow and eligible introductory offer.

## Daily allowance rules

- Enforce 1 / 2 / 3 generations per day on the server, not in UserDefaults.
- Use a stable UTC daily boundary across devices to prevent clock/time-zone changes creating extra allowances; communicate the next reset time in the user interface.
- Unused daily allowance does not roll over. Restoring a purchase does not reset consumed allowance.
- Reserve an allowance atomically before chargeable generation, with request idempotency to avoid duplicate submissions. Existing comparison/guidance should not consume another image generation.
- Keep refundable preflight failures distinct from chargeable generation attempts; finalize this policy and show it clearly before launch.
- Monthly trial daily allowance matches the selected tier: 1 / 2 / 3; a three-day trial permits up to 3 / 6 / 9 generation requests. Weekly purchases begin paid access immediately without a trial.

## Implementation work

1. Add StoreKit 2 product loading, verified purchases, current entitlements and transaction-update listening to the SwiftUI client. Include user-initiated restore purchases and Apple's manage-subscriptions flow. Handle cancellation, pending purchases, unverified transactions, offline state and expiration.
2. Add server verification of Apple-signed transactions, expected bundle/product/environment checks, subscription-status lookup and a durable entitlement ledger. Reject client-supplied tier names, expiry dates and purchase flags as authority. Keep signing keys in server environment configuration.
3. Apply tier/trial generation budgets atomically on the backend. Make purchase and renewal handling idempotent, prevent transaction replay from creating additional budgets, and define upgrade, renewal, cancellation, refund, revocation and billing-grace behavior. Support purchase restoration across devices without issuing duplicate allowances.
4. Add App Store Server Notifications V2 handling with signature verification and idempotent processing, plus reconciliation using Apple's server API. Keep purchase verification independent of the public web anonymous quota.
5. Add a bilingual subscription screen that states the tier benefit, allowance, localized price, billing period, eligible monthly trial duration and post-trial automatic renewal; weekly products must show immediate payment and weekly automatic renewal without trial messaging. Link privacy policy and Terms of Use, and provide restore/manage actions. Do not promise unavailable/unlimited features.
6. Add local StoreKit test configuration after product IDs and tier definitions are finalized; test purchases, trial eligibility, tier changes, renewal, expiration, refund, restore and server failure. TestFlight/Sandbox testing is also required before submission.

## Release preparation

The developer account is joined. Still required: final signing/bundle setup, App Store Connect app and subscription records, required commerce agreements/tax/banking setup, privacy and support URLs, App Privacy disclosures, screenshots, app description, review notes, signed archive and TestFlight validation. Signing and publishing are not performed by this specification.

## Current repository findings

The SwiftUI client in `ios/MakeupTutor/MakeupTutorApp.swift` calls the Vercel generation endpoint. `src/makeup_refine/vercel_app.py` enforces anonymous visitor quotas. Both now enforce StoreKit purchase entitlements for native subscription requests. Public web anonymous quotas remain separate.

## Apple references

- https://developer.apple.com/app-store/subscriptions/
- https://developer.apple.com/help/app-store-connect/manage-subscriptions/set-up-introductory-offers-for-auto-renewable-subscriptions/
- https://developer.apple.com/documentation/storekit/transaction/originalid

## Subscription product identifiers for creation

All six identifiers below are confirmed as created in App Store Connect. The Plus and Premium products have English (U.S.) display names and daily-allowance descriptions. Prices and introductory offers in this table are the agreed target configuration, confirmed configured by the user, pending Sandbox verification.

| Daily generations | Billing | USD price | Product identifier | Introductory trial |
| --- | --- | --- | --- | --- |
| 1 | Monthly | 6.99 | com.makeuptutor.app.basic.monthly | 3 days for eligible users |
| 1 | Weekly | 1.99 | com.makeuptutor.app.basic.weekly | None |
| 2 | Monthly | 12.99 | com.makeuptutor.app.plus.monthly | 3 days for eligible users |
| 2 | Weekly | 3.59 | com.makeuptutor.app.plus.weekly | None |
| 3 | Monthly | 16.99 | com.makeuptutor.app.premium.monthly | 3 days for eligible users |
| 3 | Weekly | 4.99 | com.makeuptutor.app.premium.weekly | None |

Backend product record IDs: Basic Monthly `6821085696`, Basic Weekly `6821089804`, Plus Monthly `6821091695`, Plus Weekly `6821091995`, Premium Monthly `6821092424`, Premium Weekly `6821092291`. The user corrected the levels and provided a confirming screenshot: Premium=1, Plus=2, Basic=3, with monthly and weekly at the same tier level.

## Implemented integration and server setup (October 9)

StoreKit 2 client and Apple-verified backend enforcement are now implemented. Purchases are acknowledged only after server verification. Generation uses a one-hour signed session, atomic daily quota and a unique request ID. Pre-provider rejection refunds the reservation; an attempt that begins AI processing consumes it even if it fails. Cancellation preserves access until expiry. Expired, revoked, refunded and billing-retry subscriptions do not grant new generations. Billing grace access is currently disabled. Guidance for an already issued preview does not consume another generation.

Configure Vercel environment variables using `.env.example`:

- `MAKEUP_SUBSCRIPTIONS_ENABLED=1`
- `APPLE_IAP_PRIVATE_KEY`: complete private `.p8` PEM, server only.
- `APPLE_IAP_KEY_ID` and `APPLE_IAP_ISSUER_ID`: from App Store Connect → Users and Access → Integrations → In-App Purchase.
- `APPLE_ALLOW_SANDBOX=1` for TestFlight/Sandbox. Production remains supported with separate sandbox quotas.
- Stable `MAKEUP_VISITOR_SECRET`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`.
- `MAKEUP_SUBSCRIPTION_GLOBAL_DAILY_LIMIT`: paid service daily safety cap, default 1000, separate from anonymous web cap.

Configure App Store Server Notifications **V2** for production and sandbox at `https://mirror-makeup.vercel.app/api/apple/notifications`. The handler verifies Apple signatures and invalidates cached entitlement status. Current status is reconciled through Apple's API; access fails closed if reconciliation is unavailable. Backend routes: POST `/api/subscription/sync`, authenticated GET `/api/subscription`, and authenticated `/api/generate` and `/api/guidance`.

The public Apple G3 certificate is bundled from https://www.apple.com/certificateauthority/AppleRootCA-G3.cer. No Apple private key belongs in Git, Xcode, or chat. `.p8` files are ignored.

No real purchase or TestFlight entitlement has been validated yet. Deploy backend environment/configuration first, then test all six products using TestFlight Sandbox: buy, pending/cancel, trial, restore on another device, upgrade/downgrade, expiry, refund, and quota reset. Apple's Sandbox purchases do not charge the customer; actual AI requests still incur provider costs. Xcode local StoreKit receipts are deliberately rejected by this backend; use TestFlight/Sandbox for end-to-end tests. Choose your Developer Team in Xcode, retain the confirmed bundle ID, and archive/upload to TestFlight. Server credentials, signing, deployment, commerce agreements and review metadata remain external setup tasks.

`/privacy` is supplied by this deployment. Replace the draft public support contact with a suitable private contact before App Store release, and complete App Privacy disclosures based on actual providers/retention. The policy states current ledger retention honestly; define operational deletion procedures before public release.

## Temporary beta access

TestFlight build 3 adds an explicit developer-issued code entry, independent of StoreKit. `MAKEUP_TEST_CODE_SHA256` configures the SHA-256 digest of a randomly generated secret code. The plaintext is neither in Git nor the app. One code grants ten total shared attempts across all devices for seven days from first redemption. Redemption never resets expiry or quota. Atomic reservations, request replay prevention and one-time pre-provider refunds apply. Purpose-scoped beta sessions never authenticate as Apple subscriptions. Existing preview guidance remains included.

POST `/api/test-access/redeem` exchanges the code for a signed session; authenticated GET `/api/test-access` returns remaining attempts and expiry. Clear the digest and redeploy to disable all beta sessions. This temporary permission costs actual AI usage and does not validate purchases, Apple trial eligibility or commerce compliance. Remove it before public release. Production deployment/permission activation requires explicit approval.
