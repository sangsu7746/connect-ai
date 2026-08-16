import { NextRequest, NextResponse } from 'next/server';
import { GoogleGenAI } from '@google/genai';
import { DAILY_IP_LIMIT, MODES, ROOM_TYPES, STYLES, buildInstruction } from '@/lib/constants';
import { isAdminEnabled, verifyBearer } from '@/lib/firebase/admin';
import { consumeCredit, refundCredit } from '@/lib/firebase/credits';

export const runtime = 'nodejs';
export const maxDuration = 60;

// Per-IP daily limit for anonymous demo usage.
// key: IP address, value: { count, resetAt }
const ipLimits = new Map<string, { count: number; resetAt: number }>();

function getIpUsage(ip: string): { allowed: boolean } {
  const now = Date.now();
  const limit = ipLimits.get(ip);

  // First request, or the 24h window has elapsed
  if (!limit || now > limit.resetAt) {
    ipLimits.set(ip, { count: 0, resetAt: now + 24 * 60 * 60 * 1000 });
    return { allowed: true };
  }

  return { allowed: limit.count < DAILY_IP_LIMIT };
}

// Only successful generations consume demo quota
function consumeIpUsage(ip: string) {
  const limit = ipLimits.get(ip);
  if (limit) limit.count += 1;
}

export async function POST(req: NextRequest) {
  let creditConsumedFor: string | null = null;

  try {
    // Request size guard (~8MB)
    const contentLength = req.headers.get('content-length');
    if (contentLength && parseInt(contentLength, 10) > 8 * 1024 * 1024) {
      return NextResponse.json(
        { error: 'Upload exceeds the 8MB limit. Please use a smaller image.' },
        { status: 413 }
      );
    }

    const { image, roomTypeId, styleId, modeId } = await req.json();

    if (!image || typeof image !== 'string') {
      return NextResponse.json(
        { error: 'Please upload a photo of your room first.' },
        { status: 400 }
      );
    }

    const mode = MODES.find((m) => m.id === modeId) ?? MODES[0];
    const roomType = ROOM_TYPES.find((r) => r.id === roomTypeId);
    const style = STYLES.find((s) => s.id === styleId);
    if ((mode.needsRoomType && !roomType) || (mode.needsStyle && !style)) {
      return NextResponse.json(
        { error: 'Please select a room type and a design style.' },
        { status: 400 }
      );
    }

    const ip =
      req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
      req.headers.get('x-real-ip') ||
      '127.0.0.1';

    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey || apiKey === 'your_gemini_api_key_here') {
      return NextResponse.json(
        { error: 'The server is missing its GEMINI_API_KEY. Please contact support.' },
        { status: 500 }
      );
    }

    // Signed-in users spend account credits; anonymous users use the IP-capped demo.
    const identity = isAdminEnabled()
      ? await verifyBearer(req.headers.get('authorization'))
      : null;

    if (identity) {
      const ok = await consumeCredit(identity.uid);
      if (!ok) {
        return NextResponse.json(
          { error: "You're out of credits. Grab a credit pack to keep designing — packs start at $9." },
          { status: 402 }
        );
      }
      creditConsumedFor = identity.uid;
    } else if (!getIpUsage(ip).allowed) {
      return NextResponse.json(
        {
          error: `Daily free limit reached (${DAILY_IP_LIMIT} per day). Sign in to get free credits, or purchase a credit pack for unlimited access.`,
        },
        { status: 429 }
      );
    }

    // Parse base64 payload + mime type
    let mimeType = 'image/jpeg';
    let base64Image = image;

    if (image.startsWith('data:')) {
      const match = image.match(/^data:([^;]+);base64,(.*)$/);
      if (match) {
        mimeType = match[1];
        base64Image = match[2];
      }
    }

    // Decoded-size guard (~8MB)
    if (base64Image.length > 8 * 1024 * 1024 * 1.33) {
      return NextResponse.json(
        { error: 'The image is larger than 8MB. Please upload a smaller one.' },
        { status: 413 }
      );
    }

    const instruction = buildInstruction(mode.id, roomType?.prompt ?? '', style?.prompt ?? '');

    const ai = new GoogleGenAI({ apiKey });
    const res = await ai.models.generateContent({
      model: 'gemini-3.1-flash-image-preview',
      contents: [
        {
          role: 'user',
          parts: [{ inlineData: { mimeType, data: base64Image } }, { text: instruction }],
        },
      ],
    });

    const candidate = res.candidates?.[0];

    if (candidate?.finishReason === 'SAFETY') {
      if (creditConsumedFor) await refundCredit(creditConsumedFor);
      return NextResponse.json(
        { error: 'Generation was blocked by the safety policy. Please try a different photo.' },
        { status: 400 }
      );
    }

    const part = candidate?.content?.parts?.find((p) => p.inlineData);
    const imageBase64 = part?.inlineData?.data;

    if (!imageBase64) {
      if (creditConsumedFor) await refundCredit(creditConsumedFor);
      return NextResponse.json(
        { error: 'Generation failed. Please try a different room type or style.' },
        { status: 400 }
      );
    }

    if (!identity) consumeIpUsage(ip);

    return NextResponse.json({ image: imageBase64 });
  } catch (error) {
    console.error('Gemini Generate API Error:', error);
    if (creditConsumedFor) {
      try {
        await refundCredit(creditConsumedFor);
      } catch (refundError) {
        console.error('Credit refund failed:', refundError);
      }
    }
    const errMsg = error instanceof Error ? error.message : '';

    if (errMsg.includes('RESOURCE_EXHAUSTED') || errMsg.includes('quota') || errMsg.includes('429')) {
      return NextResponse.json(
        { error: 'The service is at capacity right now. Please try again in a moment.' },
        { status: 429 }
      );
    }

    if (errMsg.includes('SAFETY') || errMsg.includes('safety') || errMsg.includes('blocked')) {
      return NextResponse.json(
        { error: 'Generation was declined by the safety filter. Please try a different photo or style.' },
        { status: 400 }
      );
    }

    return NextResponse.json(
      { error: `Generation failed: ${errMsg || 'unknown server error'}` },
      { status: 500 }
    );
  }
}
