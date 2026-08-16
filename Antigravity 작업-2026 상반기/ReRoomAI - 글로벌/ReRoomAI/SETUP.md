# ReRoom AI — Launch Setup Guide

The app has three feature tiers that unlock progressively as you configure env vars:

| Tier | What works | Required env vars |
|---|---|---|
| Demo | Anonymous use, 2 free tries + 10/day per IP | `GEMINI_API_KEY` |
| Accounts | Google sign-in, 5 signup credits, share pages | + `NEXT_PUBLIC_FIREBASE_*`, `FIREBASE_SERVICE_ACCOUNT` |
| Payments | Credit packs via PayPal | + `NEXT_PUBLIC_PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV` |

Nothing crashes when a tier is unconfigured — the related UI simply hides itself
(sign-in button, share button, buy buttons show "Coming soon").

---

## 1. Firebase (accounts, credits, share pages)

1. Create a project at https://console.firebase.google.com (Analytics optional).
2. **Authentication → Sign-in method → Google → Enable.**
3. **Firestore Database → Create database** (production mode). Collections used:
   - `users/{uid}` — credit balances (server-managed)
   - `orders/{orderId}` — webhook idempotency log
   - `shares/{id}` — public before/after pages
   Client SDK never touches Firestore (all access is server-side via Admin SDK),
   so you can leave security rules as deny-all:
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /{document=**} { allow read, write: if false; }
     }
   }
   ```
4. **Storage → Get started.** Share images are uploaded server-side and made
   public per-file; deny-all rules are fine here too.
5. **Project settings → General → Your apps → Add web app.** Copy the config into
   `NEXT_PUBLIC_FIREBASE_API_KEY`, `_AUTH_DOMAIN`, `_PROJECT_ID`, `_APP_ID`.
6. **Project settings → Service accounts → Generate new private key.** Put the
   whole JSON (or its base64) into `FIREBASE_SERVICE_ACCOUNT`.
   - On Vercel, paste the raw JSON as the env value — it handles multiline fine.
7. Add your production domain under **Authentication → Settings → Authorized domains.**

## 2. PayPal (payments)

No product setup is needed in PayPal — the credit packs and prices live in
`lib/constants.ts` (`CREDIT_PACKS`), and the server creates each order with the
exact amount, so buyers can never tamper with the price.

1. Go to https://developer.paypal.com → **Apps & Credentials**.
2. Sandbox testing first: under the **Sandbox** tab, use the default app (or
   create one) and copy its **Client ID** → `NEXT_PUBLIC_PAYPAL_CLIENT_ID` and
   **Secret** → `PAYPAL_CLIENT_SECRET`. Set `PAYPAL_ENV=sandbox`.
3. Test the flow with a sandbox personal account
   (**Testing Tools → Sandbox Accounts**): sign in → click a pack → pay →
   credits should appear in the header immediately.
4. Go live: switch to the **Live** tab, create a live app (requires a verified
   PayPal Business account), swap in the live Client ID/Secret and set
   `PAYPAL_ENV=live`.
5. Payment flow (all server-verified, no webhook needed):
   - `POST /api/paypal/create-order` — server creates the order with the pack's
     price and tags it with the buyer's uid
   - PayPal popup — buyer pays with PayPal balance or card
   - `POST /api/paypal/capture-order` — server captures, verifies amount +
     buyer identity, adds credits (idempotent per capture ID via the
     `orders` collection)
6. Note: unlike a Merchant-of-Record, PayPal does not remit sales tax/VAT for
   you. Early on this is usually manageable, but check your tax obligations as
   revenue grows.

## 3. Deploy (Vercel)

1. Push the repo to GitHub and import it into Vercel.
2. Add all env vars from `.env.example` in **Project → Settings → Environment Variables.**
3. Build command: `next build --webpack` if you hit Turbopack issues, otherwise default.
4. After the first deploy, update `metadataBase` in `app/layout.tsx` to your real domain.

## 4. Known local-dev notes (this machine)

- The Korean characters in the project path can crash Turbopack — run
  `npm run dev -- --webpack` / `npm run build -- --webpack`.
- `node_modules` was originally copied from macOS; if native-binary errors appear,
  delete `node_modules` and run a fresh `npm install`.

## 5. Launch checklist

- [ ] `GEMINI_API_KEY` set (paid tier recommended — demo traffic burns quota fast)
- [ ] Firebase auth + Firestore + Storage enabled, env vars set
- [ ] PayPal live app credentials set (`PAYPAL_ENV=live`), sandbox flow tested first
- [ ] Test the full loop in production: sign in → generate → buy Starter pack →
      credits appear → create share link → open it in an incognito window
- [ ] Set up rate-limit persistence if traffic grows: the per-IP demo limiter is
      in-memory and resets per serverless instance (see `app/api/generate/route.ts`)
