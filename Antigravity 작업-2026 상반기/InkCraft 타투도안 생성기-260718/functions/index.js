// InkCraft AI 프로덕션 백엔드 (Firebase Functions v2, 프로젝트: headjim-ai)
//
// 과금: HEADJIM 공용 지갑(wallets/{uid}.balance, 1코인=₩1) — WALLET_API.md 규약.
//   PrintCraft·ColorCraft·오마주앱과 같은 지갑. 충전은 앱 내 모달(기존 headjimweb 함수) 이용.
//
// ⚠️ 배포 주의:
//   - codebase "inkcraft" 로 격리 (printcraft·colorcraft·headjimweb 함수 보호)
//   - 함수명은 ik* 접두사 (generateDesign 등 타 codebase 함수명과 충돌 방지)
//   - firebase deploy --only functions:inkcraft
const { onCall, HttpsError } = require('firebase-functions/v2/https');
const { defineSecret } = require('firebase-functions/params');
const admin = require('firebase-admin');

admin.initializeApp();
const db = admin.firestore();

const CF_API_TOKEN = defineSecret('CF_API_TOKEN');
const CF_ACCOUNT_ID = defineSecret('CF_ACCOUNT_ID');
const GEMINI_API_KEY = defineSecret('GEMINI_API_KEY');

const sharp = require('sharp');

const SERVICE = 'inkcraft';

// ── 과금 기준 (1코인=₩1) ──
const PRICING = {
  DESIGN_FREE_PER_DAY: 3, // 기본 도안 무료 3장/일 (무료 미끼)
  DESIGN_COST: 10,        // 초과분 10코인
  PREMIUM_COST: 150,      // 프리미엄 도안(Gemini) 150코인
  SHEET_FREE_PER_DAY: 1,  // 플래시 시트 PDF 무료 1회/일
  SHEET_COST: 300,        // 이후 300코인
  MANUAL_APPLY_FREE_PER_DAY: 3, // 수동 시착 무료 3회/일
  MANUAL_APPLY_COST: 30,        // 이후 30코인
  TRYON_AI_COST: 150,           // AI 시착(Gemini) 150코인, 실패 시 환불
  MODEL_VIEW_COST: 100,         // 가상 모델 뷰 1프레임 (8방향 = 800코인)
  MODEL_APPLY_COST: 100,        // 모델 타투 적용 1프레임 (8방향 = 800코인)
};

// 스타일별 타투 도안 프롬프트 — server/index.js와 동일하게 유지할 것. c = true면 컬러 모드.
const TATTOO_BASE_BW =
  'isolated tattoo flash design drawn on plain white paper, clean stencil linework, black ink only, no text, no watermark';
const TATTOO_BASE_COLOR =
  'isolated tattoo flash design drawn on plain white paper, clean linework filled with vibrant tattoo ink colors, no text, no watermark';
const STYLE_PROMPTS = {
  oldschool: (t, c) =>
    `${t}, american traditional old school tattoo design, bold thick black outlines, vintage flash style, ${
      c ? 'classic bold color palette of red, yellow, green and navy, ' : 'solid black shading, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  fineline: (t, c) =>
    `${t}, fine line tattoo design, delicate thin single-needle linework, ${
      c ? 'soft watercolor washes of color, ' : 'elegant subtle stippling, '
    }graceful composition, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  minimal: (t, c) =>
    `${t}, minimalist tattoo design, simple clean continuous lines, small iconic symbol, ${
      c ? 'one or two flat accent colors, ' : ''
    }lots of negative space, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  geometric: (t, c) =>
    `${t}, geometric tattoo design, sacred geometry, precise symmetric shapes and lines, ${
      c ? 'jewel-toned color fills, ' : 'dotwork stippling shading, '
    }mandala ornament elements, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  tribal: (t, c) =>
    `${t}, tribal tattoo design, bold ${
      c ? 'polynesian inspired patterns in deep black and red tones' : 'solid black polynesian inspired patterns'
    }, flowing curved shapes, strong silhouette, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  irezumi: (t, c) =>
    `${t}, japanese irezumi style tattoo design, traditional japanese motifs with waves clouds and wind bars, dynamic flowing composition, ${
      c ? 'rich traditional irezumi colors of red, orange, teal and gold with black outlines, ' : 'black and grey ink shading, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  realism: (t, c) =>
    `${t}, ${
      c ? 'hyper realistic color tattoo design, lifelike natural colors, ' : 'hyper realistic black and grey tattoo design, '
    }photorealistic soft shading, smooth fine gradients, detailed lifelike texture, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  neotrad: (t, c) =>
    `${t}, neo-traditional tattoo design, bold clean outlines, ornate decorative details, elegant flowing composition, ${
      c ? 'rich saturated color palette with smooth blends, ' : 'dramatic black shading with depth, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  watercolor: (t, c) =>
    `${t}, watercolor tattoo design, soft paint splashes and drips, flowing ${
      c ? 'color washes' : 'black ink washes'
    } without hard outlines, artistic brush strokes, ${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  anime: (t, c) =>
    `${t}, anime manga style tattoo design, clean cel-shaded illustration, expressive dynamic linework, ${
      c ? 'vibrant anime colors, ' : 'black screentone shading, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  trashpolka: (t, c) =>
    `${t}, trash polka tattoo design, chaotic collage of realistic elements with abstract brush strokes, smears and geometric slashes, ${
      c ? 'strictly black and vivid red palette only, ' : 'high contrast black ink strokes, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  sketch: (t, c) =>
    `${t}, sketch style tattoo design, loose expressive pencil-like lines, rough hatching, artistic unfinished look, ${
      c ? 'subtle colored pencil accents, ' : ''
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  dotwork: (t, c) =>
    `${t}, dotwork tattoo design, entirely stippled dot shading, smooth dot-density gradients, ornamental composition, ${
      c ? 'dots in deep colored inks, ' : ''
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
  celtic: (t, c) =>
    `${t}, celtic nordic tattoo design, intricate interwoven knotwork patterns, viking ornamental motifs, ${
      c ? 'muted earthy color palette, ' : 'bold black knot lines, '
    }${c ? TATTOO_BASE_COLOR : TATTOO_BASE_BW}`,
};

// ─────────────────────────────────────────────
// 공용 지갑 (WALLET_API.md 원장 규약, refId 멱등)
// ─────────────────────────────────────────────
async function debitWallet(uid, coins, reason, refId) {
  const walletRef = db.collection('wallets').doc(uid);
  const ledgerRef = db.collection('walletTransactions').doc(`${SERVICE}_${refId}`);
  return db.runTransaction(async (tx) => {
    const [ledger, w] = await Promise.all([tx.get(ledgerRef), tx.get(walletRef)]);
    const balance = w.data()?.balance || 0;
    if (ledger.exists) return { alreadySpent: true, balance };
    if (balance < coins) {
      throw new HttpsError(
        'failed-precondition',
        `INSUFFICIENT_BALANCE: balance=${balance}, required=${coins}`
      );
    }
    tx.set(walletRef, { balance: balance - coins }, { merge: true });
    tx.set(ledgerRef, {
      userId: uid,
      type: 'spend',
      coins,
      balanceAfter: balance - coins,
      service: SERVICE,
      reason,
      refId,
      source: 'inkcraft-functions',
      createdAt: admin.firestore.FieldValue.serverTimestamp(),
    });
    return { alreadySpent: false, balance: balance - coins };
  });
}

async function refundWallet(uid, coins, reason, refId) {
  const walletRef = db.collection('wallets').doc(uid);
  const ledgerRef = db.collection('walletTransactions').doc(`${SERVICE}_refund_${refId}`);
  await db.runTransaction(async (tx) => {
    const [ledger, w] = await Promise.all([tx.get(ledgerRef), tx.get(walletRef)]);
    if (ledger.exists) return;
    const balance = (w.data()?.balance || 0) + coins;
    tx.set(walletRef, { balance }, { merge: true });
    tx.set(ledgerRef, {
      userId: uid,
      type: 'refund',
      coins,
      balanceAfter: balance,
      service: SERVICE,
      reason,
      refId,
      source: 'inkcraft-functions',
      createdAt: admin.firestore.FieldValue.serverTimestamp(),
    });
  });
}

// 일일 무료 쿼터 (inkcraftUsage/{uid}, UTC 날짜 기준)
const DAILY_FIELDS = ['design', 'sheet', 'manual'];
async function takeFreeQuota(uid, field, limit) {
  const ref = db.collection('inkcraftUsage').doc(uid);
  const today = new Date().toISOString().slice(0, 10);
  return db.runTransaction(async (tx) => {
    const s = await tx.get(ref);
    const u = s.exists ? s.data() : {};
    if (u.date !== today) {
      for (const f of DAILY_FIELDS) delete u[f];
      u.date = today;
    }
    const used = u[field] || 0;
    if (used >= limit) return { ok: false, used, limit };
    u[field] = used + 1;
    tx.set(ref, u);
    return { ok: true, used: used + 1, limit };
  });
}

function newRefId(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ─────────────────────────────────────────────
// AI 호출
// ─────────────────────────────────────────────
async function translateKoreanToEnglish(text, accountId, token) {
  const r = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/ai/run/@cf/meta/llama-3.1-8b-instruct`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: [
          {
            role: 'system',
            content:
              'You translate Korean tattoo-subject descriptions into natural English. Output ONLY the English translation — no quotes, no explanations.',
          },
          { role: 'user', content: text },
        ],
        max_tokens: 200,
      }),
    }
  );
  const d = await r.json();
  const out = d?.result?.response?.trim();
  if (!r.ok || !out) throw new Error('translation failed');
  return out;
}

// Cloudflare NSFW 필터가 확률적으로 오탐하므로 실패 시 1회 재시도한다.
async function generateWithFlux(prompt, accountId, token, attempts = 2) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    const r = await fetch(
      `https://api.cloudflare.com/client/v4/accounts/${accountId}/ai/run/@cf/black-forest-labs/flux-1-schnell`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, steps: 4 }),
      }
    );
    const d = await r.json();
    if (r.ok && d.success) return { mime: 'image/jpeg', b64: d.result.image };
    lastErr = new Error((d?.errors || []).map((e) => e.message).join('; ') || 'flux generation failed');
  }
  throw lastErr;
}

// Gemini는 간헐적으로 이미지 없이 STOP을 반환하므로 최대 3회 재시도한다.
async function callGemini(parts, apiKey, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    const r = await fetch(
      'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent',
      {
        method: 'POST',
        headers: { 'x-goog-api-key': apiKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts }] }),
      }
    );
    const d = await r.json();
    if (!r.ok) throw new Error(d?.error?.message || `Gemini error (${r.status})`);
    const part = d?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData || p.inline_data);
    const inline = part?.inlineData || part?.inline_data;
    if (inline?.data) return { mime: inline.mimeType || inline.mime_type || 'image/png', b64: inline.data };
    lastErr = new Error('Gemini returned no image.');
  }
  throw lastErr;
}

async function generateWithGemini(prompt, apiKey) {
  return callGemini([{ text: prompt }], apiKey);
}

// 시착(AI 타투 적용) 프롬프트 — server/index.js와 동일하게 유지할 것
const BODY_PART_HINTS = {
  arm: 'an arm (forearm, upper arm or wrist)',
  leg: 'a leg (thigh, calf or ankle)',
  upper: 'an upper body (chest, back, shoulder or neck)',
  full: 'a full body',
};
function tattooApplyInstruction(bodyPart) {
  const where = BODY_PART_HINTS[bodyPart] || 'a body part';
  return (
    `The first image is a photo of ${where} of a real person. ` +
    'The second image is a tattoo design on white paper. Preserve the original ink colors of the design. ' +
    'Apply the tattoo design onto the skin in the first photo as a realistic, freshly healed tattoo: ' +
    'follow the natural curvature and contours of the body part, wrap the design around muscles and limbs, ' +
    'render the ink as pigment settled under the skin (slightly soft edges, natural saturation, subtle skin sheen over it), ' +
    'match the perspective and lighting of the photo, and choose a natural placement and size for that body part. ' +
    'Ignore the white paper background of the design — only the artwork becomes the tattoo. ' +
    'Keep the person, pose, clothing and background completely unchanged. Output only the edited photo.'
  );
}

// ─────────────────────────────────────────────
// AI 가상 모델 (8방향 회전) — server/index.js와 프롬프트 동일하게 유지할 것
//    각도·부위는 id로만 받아 서버에서 문구로 변환한다 (프롬프트 주입 방지).
// ─────────────────────────────────────────────
const MODEL_ANGLE_HINTS = {
  0: 'directly from the front',
  1: 'from the front-right, three-quarter view',
  2: "from the model's right side, full profile",
  3: 'from the back-right, three-quarter rear view',
  4: 'directly from behind',
  5: 'from the back-left, three-quarter rear view',
  6: "from the model's left side, full profile",
  7: 'from the front-left, three-quarter view',
};
const MODEL_GENDER_PROMPTS = {
  female: 'a fictional AI-generated young woman wearing a simple grey sports bra and grey athletic shorts',
  male: 'a fictional AI-generated young man, shirtless, wearing grey athletic running shorts with a 3-inch inseam so most of the thigh is visible',
};
const MODEL_PART_LABELS = {
  leftarm: 'left arm (forearm and upper arm)',
  rightarm: 'right arm (forearm and upper arm)',
  chest: 'chest',
  back: 'upper back',
  leftleg: 'left thigh and calf',
  rightleg: 'right thigh and calf',
};

function modelFrontInstruction(gender) {
  return (
    `Photorealistic full-body studio photograph of ${MODEL_GENDER_PROMPTS[gender] || MODEL_GENDER_PROMPTS.female}, ` +
    'standing straight facing the camera in a relaxed A-pose with arms slightly away from the body, hair tied back in a neat low bun, ' +
    'entire body visible from head to feet, centered. The FULL body including the top of the head and both feet must be completely inside the frame with generous empty margin above the head and below the feet — never crop any part of the body. ' +
    'Plain light grey seamless studio background, soft even lighting, ' +
    'no tattoos on the skin, natural skin texture. Output only the photo.'
  );
}
function modelViewInstruction(angleHint) {
  return (
    'The attached image is a full-body studio photo of a fictional AI-generated model. ' +
    'Generate the exact same person — same face, same hair, same body, same outfit, same relaxed A-pose, ' +
    `same plain light grey studio background and lighting — photographed ${angleHint}. ` +
    'Entire body visible from head to feet, centered. The FULL body including the top of the head and both feet must be completely inside the frame with generous empty margin above the head and below the feet — never crop any part of the body. Output only the photo.'
  );
}
// 사진 기반 모델 3단계 파이프라인 (검증된 방식):
// ① 신원 이식 → ② 쇼츠 단축·줌아웃 편집 → ③ 패딩 후 발 아웃페인팅
// 템플릿 이미지를 함께 넣으면 인물이 템플릿에 잡아먹히므로 텍스트 편집만 사용한다.
function modelPhotoStep1Instruction() {
  return (
    'The attached image is a photo of a person (it may be cropped or partially framed). ' +
    'Generate a photorealistic full-body studio photograph of the EXACT SAME person — same face, same hairstyle, ' +
    'glasses if any, same body shape, build and proportions — now dressed for a tattoo fitting session: ' +
    'a man is shirtless wearing grey athletic running shorts, a woman wears a grey sports bra and short athletic shorts. ' +
    'Standing straight facing the camera in a relaxed A-pose, entire body visible from head to feet, centered, ' +
    'plain light grey seamless studio background, soft even lighting, no tattoos on the skin. Output only the photo.'
  );
}
function modelPhotoStep2Instruction() {
  return (
    'Edit this photo with exactly two changes and nothing else: ' +
    '(1) shorten the shorts into very short athletic running shorts — the hem must end high on the upper thigh ' +
    'so most of the thigh is bare (for a woman keep the sports bra and make the shorts short and fitted); ' +
    '(2) zoom out slightly so the entire body is in frame with both feet fully visible. ' +
    'Keep the SAME person — same face, glasses, hair and body build — same pose, background and lighting. ' +
    'Output only the edited photo.'
  );
}
function modelPhotoStep3Instruction() {
  return (
    'This photo has been extended with blank grey space at the top and bottom. ' +
    'Fill in the blank areas naturally and seamlessly: continue the studio background, and complete the model body — ' +
    'finish the lower legs, ankles and BOTH FEET standing naturally on the studio floor inside the frame. ' +
    'Do not change anything about the person, outfit, pose or lighting in the existing part of the photo. ' +
    'Output only the completed photo.'
  );
}

// 수동 배치 정제: 얹어둔 도안 그래픽을 그 자리·그 크기 그대로 실제 타투처럼 다듬는다
function modelRefineInstruction() {
  return (
    'The image is a full-body studio photo of a fictional model with a tattoo graphic pasted flat on the skin like a sticker. ' +
    'Preserve the original ink colors of the design. ' +
    'Re-render that graphic as a REAL tattoo in the same spot at the same size: warp and wrap the design onto the 3D curvature ' +
    'and perspective of that body part — it must follow the surface like ink in the skin, with natural foreshortening where ' +
    'the limb curves away. Remove any flat rectangular patch, halo or paper-like artifact around the design. ' +
    'Render the ink as pigment settled under the skin with natural saturation and a subtle skin sheen, matching the lighting of the photo. ' +
    'The ink must stay strictly within the silhouette of the skin: never draw any part of the tattoo outside the body outline, ' +
    'over the background, or over clothing — trim the design at the edge of the body part if needed. ' +
    'Keep the person, pose, outfit, background and everything else completely unchanged. Output only the edited photo.'
  );
}

// 기준 각도에 적용된 타투를 다른 각도 프레임에 같은 위치·크기로 전파
// 3이미지 참조: ①대상 프레임 ②앵커 적용본(위치·크기 기준) ③원본 도안(디자인 충실도 기준)
// — 체인 전파의 변형 증폭을 막기 위해 항상 앵커+원본을 직접 참조한다.
function modelFollowInstruction(angleHint, refAngleHint) {
  return (
    `The first image is a full-body studio photo of a fictional model photographed ${angleHint}. ` +
    `The second image is the SAME model photographed ${refAngleHint}, showing the model's ONLY tattoo. ` +
    'The third image is the exact tattoo artwork on white paper. ' +
    'Task: apply that exact tattoo onto the first image, at the same anatomical body location and the same ' +
    'size relative to the body as shown in the second image. ' +
    'Reproduce the artwork of the third image faithfully — same design, same colors. Do NOT redesign it, ' +
    'do NOT enlarge it, do NOT add any extra decorative elements. The model has exactly ONE tattoo. ' +
    'The second image is already oriented to match this camera direction: place the tattoo on the SAME SIDE ' +
    'of the image and at the same height on the body as shown in the second image. ' +
    'Render it realistically: warp it onto the 3D curvature of the body with correct perspective and ' +
    'foreshortening for this camera angle, ink as pigment settled under the skin with natural saturation, ' +
    'matching the lighting. Never paste it flat like a sticker. ' +
    'The ink must stay strictly within the silhouette of the skin — never over background or clothing. ' +
    'Judge honestly, based on real human anatomy, how much of that exact body location can actually be seen from ' +
    "this camera angle: (a) if it is fully visible, render the complete tattoo; (b) if the body has rotated so " +
    'only part of that location remains toward the camera (e.g. the near edge of a shoulder or side torso at a ' +
    'three-quarter angle), render ONLY that naturally visible sliver, correctly foreshortened by the curvature — ' +
    'do not stretch it to look complete; (c) if that location is entirely on the far side of the body from this ' +
    'angle (for example a front-of-shoulder or front-of-chest placement viewed from directly behind), it is fully ' +
    'occluded — in this case output the first image completely unchanged, with no tattoo drawn anywhere on it, ' +
    'and leave that skin bare. Drawing the tattoo somewhere it cannot actually be seen from this angle is a failure. ' +
    'Keep the person, pose, outfit, background and everything else completely unchanged. Output only the edited photo.'
  );
}

function modelApplyInstruction(partLabel, angleHint) {
  return (
    `The first image is a full-body studio photo of a fictional model photographed ${angleHint}. ` +
    'The second image is a tattoo design on white paper. Preserve the original ink colors of the design. ' +
    `Apply the tattoo design onto the model's ${partLabel} as a realistic tattoo: follow the natural curvature of the body, ` +
    'render the ink as pigment settled under the skin with natural saturation and a subtle skin sheen, match the lighting, ' +
    'and choose a natural size for that body part. Ignore the white paper background of the design. ' +
    "IMPORTANT: 'left' and 'right' refer to the model's own anatomical sides, not the sides of the image — " +
    "in a front-facing view the model's left arm appears on the RIGHT side of the image, and in a rear view on the LEFT side. " +
    'Never place the tattoo on the opposite limb or side. ' +
    'In a full profile (side) view only the limb nearest to the camera is visible: if the specified limb is on the far side of the body, ' +
    'it is occluded — in that case output the first photo exactly as it is, with no tattoo anywhere. Adding the tattoo to the wrong limb is a failure. ' +
    `If the ${partLabel} is partially turned away from the camera at this angle, show only the naturally visible portion of the tattoo; ` +
    'if it is completely hidden from this angle, return the photo unchanged. ' +
    'Keep the person, pose, outfit, background and everything else completely unchanged. Output only the edited photo.'
  );
}

// ─────────────────────────────────────────────
// 1) 타투 도안 생성 — 기본(무료3/일→10코인) / 프리미엄(150코인) · color: 'bw'|'color'
// ─────────────────────────────────────────────
exports.ikGenerateDesign = onCall(
  { secrets: [CF_API_TOKEN, CF_ACCOUNT_ID, GEMINI_API_KEY], timeoutSeconds: 90, memory: '256MiB' },
  async (request) => {
    if (!request.auth) throw new HttpsError('unauthenticated', 'Sign in required.');
    const uid = request.auth.uid;
    const { subject, style } = request.data || {};
    const engine = request.data?.engine === 'premium' ? 'premium' : 'standard';

    if (!subject || typeof subject !== 'string' || subject.trim().length < 2 || subject.length > 300) {
      throw new HttpsError('invalid-argument', 'Invalid subject.');
    }
    const isColor = request.data?.color === 'color';
    const composer = STYLE_PROMPTS[style];
    if (!composer) throw new HttpsError('invalid-argument', `Unknown style: ${style}`);

    const refId = newRefId('design');
    let charged = 0;
    let quota = null;

    if (engine === 'premium') {
      await debitWallet(uid, PRICING.PREMIUM_COST, '프리미엄 타투 도안', refId);
      charged = PRICING.PREMIUM_COST;
    } else {
      const q = await takeFreeQuota(uid, 'design', PRICING.DESIGN_FREE_PER_DAY);
      quota = { used: q.used, limit: q.limit };
      if (!q.ok) {
        await debitWallet(uid, PRICING.DESIGN_COST, '타투 도안 생성', refId);
        charged = PRICING.DESIGN_COST;
      }
    }

    try {
      let image, translatedPrompt = null;
      if (engine === 'premium') {
        const out = await generateWithGemini(composer(subject.trim(), isColor), GEMINI_API_KEY.value().trim());
        image = `data:${out.mime};base64,${out.b64}`;
      } else {
        let finalSubject = subject.trim();
        if (/[가-힣]/.test(finalSubject)) {
          try {
            translatedPrompt = await translateKoreanToEnglish(
              finalSubject, CF_ACCOUNT_ID.value().trim(), CF_API_TOKEN.value().trim()
            );
            finalSubject = translatedPrompt;
          } catch {
            console.warn('translation failed, using original subject');
          }
        }
        const out = await generateWithFlux(
          composer(finalSubject, isColor), CF_ACCOUNT_ID.value().trim(), CF_API_TOKEN.value().trim()
        );
        image = `data:${out.mime};base64,${out.b64}`;
      }
      return { image, quota, charged, translatedPrompt, engine };
    } catch (e) {
      if (charged > 0) await refundWallet(uid, charged, '생성 실패 환불', refId);
      console.error('generation failed:', e.message);
      throw new HttpsError('internal', 'Generation failed. You were not charged.');
    }
  }
);

// ─────────────────────────────────────────────
// 2) AI 시착 — 내 사진에 도안을 실제 타투처럼 합성 (150코인, 실패 시 환불)
// ─────────────────────────────────────────────
exports.ikApplyTattooAI = onCall(
  { secrets: [GEMINI_API_KEY], timeoutSeconds: 90, memory: '512MiB' },
  async (request) => {
    if (!request.auth) throw new HttpsError('unauthenticated', 'Sign in required.');
    const uid = request.auth.uid;
    const { photo, design, bodyPart } = request.data || {};
    const mPhoto = /^data:image\/(jpeg|png|webp);base64,(.+)$/.exec(photo || '');
    const mDesign = /^data:image\/(jpeg|png|webp);base64,(.+)$/.exec(design || '');
    if (!mPhoto || !mDesign) {
      throw new HttpsError('invalid-argument', 'photo and design must be image data URLs.');
    }

    const refId = newRefId('tryon');
    await debitWallet(uid, PRICING.TRYON_AI_COST, 'AI 타투 시착', refId);

    try {
      const out = await callGemini(
        [
          { text: tattooApplyInstruction(bodyPart) },
          { inline_data: { mime_type: `image/${mPhoto[1]}`, data: mPhoto[2] } },
          { inline_data: { mime_type: `image/${mDesign[1]}`, data: mDesign[2] } },
        ],
        GEMINI_API_KEY.value().trim()
      );
      return { image: `data:${out.mime};base64,${out.b64}`, charged: PRICING.TRYON_AI_COST };
    } catch (e) {
      await refundWallet(uid, PRICING.TRYON_AI_COST, '시착 실패 환불', refId);
      console.error('ikApplyTattooAI failed:', e.message);
      throw new HttpsError('internal', 'AI try-on failed. You were not charged.');
    }
  }
);

// ─────────────────────────────────────────────
// 3) 가상 모델 뷰 1프레임 (100코인, 실패 시 환불)
//    angle 0: 텍스트(가상 모델) 또는 userPhoto(내 사진 기반) / 1~7: 정면 사진 참조 회전
// ─────────────────────────────────────────────
exports.ikModelView = onCall(
  { secrets: [GEMINI_API_KEY], timeoutSeconds: 180, memory: '512MiB' },
  async (request) => {
    if (!request.auth) throw new HttpsError('unauthenticated', 'Sign in required.');
    const uid = request.auth.uid;
    const { gender, angle, refImage, userPhoto } = request.data || {};
    const hint = MODEL_ANGLE_HINTS[Number(angle)];
    if (!hint) throw new HttpsError('invalid-argument', `Unknown angle: ${angle}`);

    // 사진 기반 정면 뷰 — 3단계 파이프라인 (신원 이식 → 쇼츠 단축·줌아웃 → 발 아웃페인팅)
    if (Number(angle) === 0 && userPhoto) {
      const mUser = /^data:image\/(jpeg|png|webp);base64,(.+)$/.exec(userPhoto);
      if (!mUser) throw new HttpsError('invalid-argument', 'userPhoto must be an image data URL.');

      const refId0 = newRefId('mview0');
      await debitWallet(uid, PRICING.MODEL_VIEW_COST, '가상 모델 뷰 (0, 사진)', refId0);
      try {
        const key = GEMINI_API_KEY.value().trim();
        let out = await callGemini(
          [{ text: modelPhotoStep1Instruction() }, { inline_data: { mime_type: `image/${mUser[1]}`, data: mUser[2] } }],
          key
        );
        out = await callGemini(
          [{ text: modelPhotoStep2Instruction() }, { inline_data: { mime_type: out.mime, data: out.b64 } }],
          key
        );
        const buf = Buffer.from(out.b64, 'base64');
        const meta = await sharp(buf).metadata();
        const padded = await sharp(buf)
          .extend({
            top: Math.round(meta.height * 0.06),
            bottom: Math.round(meta.height * 0.18),
            background: { r: 224, g: 224, b: 224 },
          })
          .jpeg({ quality: 92 })
          .toBuffer();
        out = await callGemini(
          [{ text: modelPhotoStep3Instruction() }, { inline_data: { mime_type: 'image/jpeg', data: padded.toString('base64') } }],
          key
        );
        return { image: `data:${out.mime};base64,${out.b64}`, charged: PRICING.MODEL_VIEW_COST };
      } catch (e) {
        await refundWallet(uid, PRICING.MODEL_VIEW_COST, '모델 뷰 실패 환불', refId0);
        console.error('ikModelView(photo) failed:', e.message);
        throw new HttpsError('internal', 'Model view generation failed. You were not charged.');
      }
    }

    let parts;
    if (Number(angle) === 0) {
      parts = [{ text: modelFrontInstruction(gender) }];
    } else {
      const mRef = /^data:image\/(jpeg|png|webp);base64,(.+)$/.exec(refImage || '');
      if (!mRef) throw new HttpsError('invalid-argument', 'refImage (front view) is required.');
      parts = [
        { text: modelViewInstruction(hint) },
        { inline_data: { mime_type: `image/${mRef[1]}`, data: mRef[2] } },
      ];
    }

    const refId = newRefId(`mview${angle}`);
    await debitWallet(uid, PRICING.MODEL_VIEW_COST, `가상 모델 뷰 (${angle})`, refId);
    try {
      const out = await callGemini(parts, GEMINI_API_KEY.value().trim());
      return { image: `data:${out.mime};base64,${out.b64}`, charged: PRICING.MODEL_VIEW_COST };
    } catch (e) {
      await refundWallet(uid, PRICING.MODEL_VIEW_COST, '모델 뷰 실패 환불', refId);
      console.error('ikModelView failed:', e.message);
      throw new HttpsError('internal', 'Model view generation failed. You were not charged.');
    }
  }
);

// ─────────────────────────────────────────────
// 4) 모델 프레임에 타투 적용 1프레임 (100코인, 실패 시 환불) — 3가지 모드
//    part(기본): 부위 지정 자동 배치 / refine: 수동 배치 합성본을 실제 타투처럼 정제
//    follow: 기준 각도 결과를 다른 각도에 같은 위치·크기로 전파
// ─────────────────────────────────────────────
const IMG_RE = /^data:image\/(jpeg|png|webp);base64,(.+)$/;
function toInline(m) {
  return { inline_data: { mime_type: `image/${m[1]}`, data: m[2] } };
}

exports.ikModelApply = onCall(
  { secrets: [GEMINI_API_KEY], timeoutSeconds: 90, memory: '512MiB' },
  async (request) => {
    if (!request.auth) throw new HttpsError('unauthenticated', 'Sign in required.');
    const uid = request.auth.uid;
    const { mode, photo, design, part, angle, reference, refAngle } = request.data || {};
    const mPhoto = IMG_RE.exec(photo || '');
    if (!mPhoto) throw new HttpsError('invalid-argument', 'photo must be an image data URL.');

    let parts;
    if (mode === 'refine') {
      parts = [{ text: modelRefineInstruction() }, toInline(mPhoto)];
    } else if (mode === 'follow') {
      const hint = MODEL_ANGLE_HINTS[Number(angle)];
      const refHint = MODEL_ANGLE_HINTS[Number(refAngle)];
      const mRef = IMG_RE.exec(reference || '');
      if (!hint || !refHint) throw new HttpsError('invalid-argument', 'Unknown angle.');
      if (!mRef) throw new HttpsError('invalid-argument', 'reference must be an image data URL.');
      const mDesignF = IMG_RE.exec(design || '');
      if (!mDesignF) throw new HttpsError('invalid-argument', 'design must be an image data URL.');
      // 정면↔후면 계열 간 전파: 참조를 좌우 반전 — Gemini의 '2D 위치 복사' 습성이 해부학적으로 맞아떨어지게 한다
      const FRONTISH = [7, 0, 1];
      const BACKISH = [3, 4, 5];
      const needFlip =
        (FRONTISH.includes(Number(refAngle)) && BACKISH.includes(Number(angle))) ||
        (BACKISH.includes(Number(refAngle)) && FRONTISH.includes(Number(angle)));
      let refInline = toInline(mRef);
      if (needFlip) {
        const flipped = await sharp(Buffer.from(mRef[2], 'base64')).flop().jpeg({ quality: 92 }).toBuffer();
        refInline = { inline_data: { mime_type: 'image/jpeg', data: flipped.toString('base64') } };
      }
      parts = [{ text: modelFollowInstruction(hint, refHint) }, toInline(mPhoto), refInline, toInline(mDesignF)];
    } else {
      const hint = MODEL_ANGLE_HINTS[Number(angle)];
      const partLabel = MODEL_PART_LABELS[part];
      const mDesign = IMG_RE.exec(design || '');
      if (!hint) throw new HttpsError('invalid-argument', `Unknown angle: ${angle}`);
      if (!partLabel) throw new HttpsError('invalid-argument', `Unknown part: ${part}`);
      if (!mDesign) throw new HttpsError('invalid-argument', 'design must be an image data URL.');
      parts = [{ text: modelApplyInstruction(partLabel, hint) }, toInline(mPhoto), toInline(mDesign)];
    }

    const refId = newRefId(`mapply${mode || 'part'}${angle ?? ''}`);
    await debitWallet(uid, PRICING.MODEL_APPLY_COST, `모델 타투 적용 (${mode || 'part'} ${angle ?? ''})`, refId);
    try {
      const out = await callGemini(parts, GEMINI_API_KEY.value().trim());
      return { image: `data:${out.mime};base64,${out.b64}`, charged: PRICING.MODEL_APPLY_COST };
    } catch (e) {
      await refundWallet(uid, PRICING.MODEL_APPLY_COST, '모델 적용 실패 환불', refId);
      console.error('ikModelApply failed:', e.message);
      throw new HttpsError('internal', 'Model tattoo apply failed. You were not charged.');
    }
  }
);

// ─────────────────────────────────────────────
// 5) 부가 기능 과금 게이트 — 플래시 시트 PDF / 수동 시착
// ─────────────────────────────────────────────
exports.ikChargeFeature = onCall({ timeoutSeconds: 30 }, async (request) => {
  if (!request.auth) throw new HttpsError('unauthenticated', 'Sign in required.');
  const uid = request.auth.uid;
  const { feature } = request.data || {};
  const refId = newRefId(feature || 'feat');

  if (feature === 'sheet_export') {
    const q = await takeFreeQuota(uid, 'sheet', PRICING.SHEET_FREE_PER_DAY);
    if (q.ok) return { ok: true, charged: 0, quota: q };
    await debitWallet(uid, PRICING.SHEET_COST, '플래시 시트 내보내기', refId);
    return { ok: true, charged: PRICING.SHEET_COST, quota: q };
  }

  if (feature === 'manual_apply') {
    const q = await takeFreeQuota(uid, 'manual', PRICING.MANUAL_APPLY_FREE_PER_DAY);
    if (q.ok) return { ok: true, charged: 0, quota: q };
    await debitWallet(uid, PRICING.MANUAL_APPLY_COST, '수동 타투 시착', refId);
    return { ok: true, charged: PRICING.MANUAL_APPLY_COST, quota: q };
  }

  throw new HttpsError('invalid-argument', `Unknown feature: ${feature}`);
});
