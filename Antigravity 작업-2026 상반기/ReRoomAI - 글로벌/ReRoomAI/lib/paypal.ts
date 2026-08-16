// Server-side PayPal Orders API v2 client.
// Env: NEXT_PUBLIC_PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_ENV (sandbox | live)

const API_BASE =
  process.env.PAYPAL_ENV === 'live'
    ? 'https://api-m.paypal.com'
    : 'https://api-m.sandbox.paypal.com';

export const isPayPalEnabled = () =>
  Boolean(process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID && process.env.PAYPAL_CLIENT_SECRET);

async function getAccessToken(): Promise<string> {
  const auth = Buffer.from(
    `${process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID}:${process.env.PAYPAL_CLIENT_SECRET}`
  ).toString('base64');

  const res = await fetch(`${API_BASE}/v1/oauth2/token`, {
    method: 'POST',
    headers: {
      Authorization: `Basic ${auth}`,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: 'grant_type=client_credentials',
    cache: 'no-store',
  });

  if (!res.ok) {
    throw new Error(`PayPal auth failed (${res.status})`);
  }
  const data = await res.json();
  return data.access_token;
}

/** Creates an order for a credit pack. custom_id carries "uid:packId" for capture-time verification. */
export async function createPayPalOrder(params: {
  uid: string;
  packId: string;
  usd: number;
  description: string;
}): Promise<string> {
  const token = await getAccessToken();
  const res = await fetch(`${API_BASE}/v2/checkout/orders`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      intent: 'CAPTURE',
      purchase_units: [
        {
          custom_id: `${params.uid}:${params.packId}`,
          description: params.description,
          amount: { currency_code: 'USD', value: params.usd.toFixed(2) },
        },
      ],
    }),
  });

  if (!res.ok) {
    console.error('PayPal create order failed:', res.status, await res.text());
    throw new Error('Could not create the PayPal order.');
  }
  const data = await res.json();
  return data.id as string;
}

export type CaptureResult = {
  captureId: string;
  status: string;
  customId: string;
  amountValue: string;
  currency: string;
};

/** Captures an approved order and returns the verified capture details. */
export async function capturePayPalOrder(orderId: string): Promise<CaptureResult> {
  const token = await getAccessToken();
  const res = await fetch(`${API_BASE}/v2/checkout/orders/${encodeURIComponent(orderId)}/capture`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  const data = await res.json();
  if (!res.ok) {
    console.error('PayPal capture failed:', res.status, JSON.stringify(data));
    throw new Error('Payment capture failed.');
  }

  const unit = data.purchase_units?.[0];
  const capture = unit?.payments?.captures?.[0];
  if (!capture) {
    throw new Error('Payment capture returned no capture record.');
  }

  return {
    captureId: capture.id,
    status: capture.status,
    customId: capture.custom_id ?? unit?.custom_id ?? '',
    amountValue: capture.amount?.value ?? '',
    currency: capture.amount?.currency_code ?? '',
  };
}
