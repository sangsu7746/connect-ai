import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import { adminBucket, adminDb, isAdminEnabled, verifyBearer } from '@/lib/firebase/admin';
import { MODES, ROOM_TYPES, STYLES } from '@/lib/constants';

export const runtime = 'nodejs';
export const maxDuration = 30;

// Creates a public before/after share page at /s/{id}.
// Sign-in required so anonymous traffic can't fill the storage bucket.

function decodeDataUrl(dataUrl: string): { buffer: Buffer; contentType: string } | null {
  const match = dataUrl.match(/^data:(image\/[a-z+]+);base64,(.+)$/);
  if (!match) return null;
  const buffer = Buffer.from(match[2], 'base64');
  if (buffer.length > 6 * 1024 * 1024) return null;
  return { buffer, contentType: match[1] };
}

export async function POST(req: NextRequest) {
  if (!isAdminEnabled()) {
    return NextResponse.json({ error: 'Sharing is not enabled on this deployment.' }, { status: 501 });
  }

  const identity = await verifyBearer(req.headers.get('authorization'));
  if (!identity) {
    return NextResponse.json({ error: 'Please sign in to create a share link.' }, { status: 401 });
  }

  const { before, after, roomTypeId, styleId, modeId } = await req.json();

  const style = STYLES.find((s) => s.id === styleId);
  const room = ROOM_TYPES.find((r) => r.id === roomTypeId);
  const mode = MODES.find((m) => m.id === modeId) ?? MODES[0];
  if (
    typeof before !== 'string' ||
    typeof after !== 'string' ||
    (mode.needsStyle && !style) ||
    (mode.needsRoomType && !room)
  ) {
    return NextResponse.json({ error: 'Invalid share payload.' }, { status: 400 });
  }

  const beforeImg = decodeDataUrl(before);
  const afterImg = decodeDataUrl(after);
  if (!beforeImg || !afterImg) {
    return NextResponse.json({ error: 'Images must be data URLs under 6MB.' }, { status: 400 });
  }

  const id = crypto.randomBytes(8).toString('hex');
  const bucket = adminBucket();

  const upload = async (name: string, img: { buffer: Buffer; contentType: string }) => {
    const file = bucket.file(`shares/${id}/${name}`);
    await file.save(img.buffer, {
      contentType: img.contentType,
      metadata: { cacheControl: 'public, max-age=31536000, immutable' },
    });
    await file.makePublic();
    return `https://storage.googleapis.com/${bucket.name}/${file.name}`;
  };

  const [beforeUrl, afterUrl] = await Promise.all([
    upload('before.jpg', beforeImg),
    upload('after.png', afterImg),
  ]);

  await adminDb().collection('shares').doc(id).set({
    uid: identity.uid,
    beforeUrl,
    afterUrl,
    styleId: mode.needsStyle && style ? style.id : null,
    styleLabel: mode.needsStyle && style ? style.label : null,
    roomLabel: mode.needsRoomType && room ? room.label : null,
    modeId: mode.id,
    modeLabel: mode.label,
    createdAt: new Date(),
  });

  return NextResponse.json({ id, url: `/s/${id}` });
}
