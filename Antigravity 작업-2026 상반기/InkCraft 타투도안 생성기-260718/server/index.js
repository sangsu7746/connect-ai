// InkCraft AI — 로컬 개발용 프록시 서버
// 브라우저에 API 키가 노출되지 않도록 서버에서 대신 호출한다. (과금 없음, IP 일일한도만)
import 'dotenv/config';
import express from 'express';
import sharp from 'sharp';

const { CF_ACCOUNT_ID, CF_API_TOKEN, GEMINI_API_KEY } = process.env;
const PORT = Number(process.env.PORT || 8789);
const DAILY_LIMIT = Number(process.env.DAILY_LIMIT || 30);

if (!CF_ACCOUNT_ID || !CF_API_TOKEN) {
  console.error('❌ .env에 CF_ACCOUNT_ID / CF_API_TOKEN을 설정하세요. (.env.example 참고)');
  process.exit(1);
}

// 스타일별 타투 도안 프롬프트 — 이 서비스의 핵심 노하우.
// 공통 원칙: 순백 배경, 도안 단독, 글자/워터마크 금지. c = true면 컬러 모드.
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

// 한국어 소재 → 영어 번역 (Cloudflare 무료 LLM)
async function translateKoreanToEnglish(text) {
  const r = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${CF_API_TOKEN}`,
        'Content-Type': 'application/json',
      },
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

// Gemini는 간헐적으로 이미지 없이 STOP을 반환하므로 최대 3회 재시도한다.
async function callGeminiParts(parts, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    const r = await fetch(
      'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent',
      {
        method: 'POST',
        headers: { 'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts }] }),
      }
    );
    const d = await r.json();
    if (!r.ok) throw new Error(d?.error?.message || `Gemini error (${r.status})`);
    const part = d?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData || p.inline_data);
    const inline = part?.inlineData || part?.inline_data;
    if (inline?.data) return `data:${inline.mimeType || inline.mime_type || 'image/png'};base64,${inline.data}`;
    lastErr = new Error('Gemini returned no image.');
  }
  throw lastErr;
}

// 프리미엄: Gemini 2.5 Flash Image (한국어 원어 이해, 더 정돈된 구도·선)
async function generateWithGemini(prompt) {
  return callGeminiParts([{ text: prompt }]);
}

// 시착(AI 타투 적용) 프롬프트 — 부위 힌트별 문구
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

// ── AI 가상 모델 (8방향 회전) ──────────────────
// 각도·부위는 id로만 받아 서버에서 문구로 변환한다 (프롬프트 주입 방지).
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

const IMG_RE = /^data:image\/(jpeg|png|webp);base64,(.+)$/;
function toInline(m) {
  return { inline_data: { mime_type: `image/${m[1]}`, data: m[2] } };
}

const app = express();
app.use(express.json({ limit: '20mb' }));

// 가상 모델 뷰 생성: angle 0(정면)은 텍스트(또는 사용자 사진), 1~7은 정면 사진을 기준으로 회전 뷰 생성
app.post('/api/model-view', async (req, res) => {
  if (!GEMINI_API_KEY) {
    return res.status(400).json({ error: 'AI model requires GEMINI_API_KEY in server/.env.' });
  }
  const { gender, angle, refImage, userPhoto } = req.body || {};
  const hint = MODEL_ANGLE_HINTS[Number(angle)];
  if (!hint) return res.status(400).json({ error: `Unknown angle: ${angle}` });

  try {
    let image;
    if (Number(angle) === 0 && userPhoto) {
      // 사용자 전신사진 기반 정면 뷰 (얼굴·체형 유지, 사진은 저장하지 않음)
      const mUser = IMG_RE.exec(userPhoto);
      if (!mUser) return res.status(400).json({ error: 'userPhoto must be an image data URL.' });
      // ① 신원 이식
      const s1 = await callGeminiParts([{ text: modelPhotoStep1Instruction() }, toInline(mUser)]);
      // ② 쇼츠 단축 + 줌아웃 (텍스트 편집 — 템플릿 이미지를 넣으면 인물이 바뀌므로 금지)
      const s2 = await callGeminiParts([{ text: modelPhotoStep2Instruction() }, toInline(IMG_RE.exec(s1))]);
      // ③ 위·아래 패딩 후 발/여백 아웃페인팅 (발 잘림 방지 확정 처리)
      const buf = Buffer.from(IMG_RE.exec(s2)[2], 'base64');
      const meta = await sharp(buf).metadata();
      const padded = await sharp(buf)
        .extend({
          top: Math.round(meta.height * 0.06),
          bottom: Math.round(meta.height * 0.18),
          background: { r: 224, g: 224, b: 224 },
        })
        .jpeg({ quality: 92 })
        .toBuffer();
      image = await callGeminiParts([
        { text: modelPhotoStep3Instruction() },
        { inline_data: { mime_type: 'image/jpeg', data: padded.toString('base64') } },
      ]);
    } else if (Number(angle) === 0) {
      image = await callGeminiParts([{ text: modelFrontInstruction(gender) }]);
    } else {
      const mRef = IMG_RE.exec(refImage || '');
      if (!mRef) return res.status(400).json({ error: 'refImage (front view) is required for rotated views.' });
      image = await callGeminiParts([{ text: modelViewInstruction(hint) }, toInline(mRef)]);
    }
    res.json({ image });
  } catch (err) {
    console.error('model-view failed:', err.message);
    res.status(500).json({ error: 'Model view generation failed.' });
  }
});

// 가상 모델 프레임에 타투 적용 — 3가지 모드
//   part(기본): 부위 지정 자동 배치 / refine: 수동 배치 합성본을 실제 타투처럼 정제
//   follow: 기준 각도 결과를 다른 각도에 같은 위치·크기로 전파
app.post('/api/model-apply', async (req, res) => {
  if (!GEMINI_API_KEY) {
    return res.status(400).json({ error: 'AI model requires GEMINI_API_KEY in server/.env.' });
  }
  const { mode, photo, design, part, angle, reference, refAngle } = req.body || {};
  const mPhoto = IMG_RE.exec(photo || '');
  if (!mPhoto) return res.status(400).json({ error: 'photo must be an image data URL.' });

  try {
    let parts;
    if (mode === 'refine') {
      parts = [{ text: modelRefineInstruction() }, toInline(mPhoto)];
    } else if (mode === 'follow') {
      const hint = MODEL_ANGLE_HINTS[Number(angle)];
      const refHint = MODEL_ANGLE_HINTS[Number(refAngle)];
      const mRef = IMG_RE.exec(reference || '');
      if (!hint || !refHint) return res.status(400).json({ error: 'Unknown angle.' });
      if (!mRef) return res.status(400).json({ error: 'reference must be an image data URL.' });
      const mDesignF = IMG_RE.exec(design || '');
      if (!mDesignF) return res.status(400).json({ error: 'design must be an image data URL.' });
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
      if (!hint) return res.status(400).json({ error: `Unknown angle: ${angle}` });
      if (!partLabel) return res.status(400).json({ error: `Unknown part: ${part}` });
      if (!mDesign) return res.status(400).json({ error: 'design must be an image data URL.' });
      parts = [{ text: modelApplyInstruction(partLabel, hint) }, toInline(mPhoto), toInline(mDesign)];
    }
    const image = await callGeminiParts(parts);
    res.json({ image });
  } catch (err) {
    console.error('model-apply failed:', err.message);
    res.status(500).json({ error: 'Model tattoo apply failed.' });
  }
});

// 시착: 내 사진(팔/다리/상체/온몸)에 도안을 실제 타투처럼 합성 (Gemini 멀티 이미지 편집)
app.post('/api/apply-tattoo', async (req, res) => {
  if (!GEMINI_API_KEY) {
    return res.status(400).json({
      error: 'AI try-on requires GEMINI_API_KEY in server/.env (free key at aistudio.google.com).',
    });
  }
  const { photo, design, bodyPart } = req.body || {};
  const mPhoto = IMG_RE.exec(photo || '');
  const mDesign = IMG_RE.exec(design || '');
  if (!mPhoto || !mDesign) {
    return res.status(400).json({ error: 'photo and design must be image data URLs.' });
  }

  try {
    const image = await callGeminiParts([
      { text: tattooApplyInstruction(bodyPart) },
      toInline(mPhoto),
      toInline(mDesign),
    ]);
    res.json({ image });
  } catch (err) {
    console.error('apply-tattoo failed:', err.message);
    res.status(500).json({ error: 'AI try-on failed.' });
  }
});

const usage = new Map();
function checkQuota(ip) {
  const today = new Date().toISOString().slice(0, 10);
  const rec = usage.get(ip);
  if (!rec || rec.date !== today) usage.set(ip, { date: today, count: 0 });
  return usage.get(ip);
}

app.post('/api/generate', async (req, res) => {
  const { subject, style } = req.body || {};
  const isColor = req.body?.color === 'color';
  if (!subject || typeof subject !== 'string' || subject.trim().length < 2 || subject.length > 300) {
    return res.status(400).json({ error: 'Subject is required (2–300 chars).' });
  }
  const composer = STYLE_PROMPTS[style];
  if (!composer) return res.status(400).json({ error: `Unknown style: ${style}` });

  const engine = req.body?.engine === 'premium' ? 'premium' : 'standard';
  if (engine === 'premium' && !GEMINI_API_KEY) {
    return res.status(400).json({
      error: 'Premium engine not configured. Set GEMINI_API_KEY in server/.env.',
    });
  }

  const ip = req.ip || 'local';
  const rec = checkQuota(ip);
  if (rec.count >= DAILY_LIMIT) {
    return res.status(429).json({
      error: `Daily free limit reached (${DAILY_LIMIT}/day). Try again tomorrow!`,
      quota: { used: rec.count, limit: DAILY_LIMIT },
    });
  }

  try {
    if (engine === 'premium') {
      const image = await generateWithGemini(composer(subject.trim(), isColor));
      rec.count += 1;
      return res.json({
        image,
        quota: { used: rec.count, limit: DAILY_LIMIT },
        translatedPrompt: null,
        engine,
      });
    }

    let finalSubject = subject.trim();
    let translatedPrompt = null;
    if (/[가-힣]/.test(finalSubject)) {
      try {
        translatedPrompt = await translateKoreanToEnglish(finalSubject);
        finalSubject = translatedPrompt;
      } catch {
        console.warn('translation failed, using original subject');
      }
    }

    // Cloudflare NSFW 필터가 확률적으로 오탐하므로 실패 시 1회 재시도한다.
    let data = null;
    let lastMsg = '';
    for (let attempt = 0; attempt < 2; attempt++) {
      const cfRes = await fetch(
        `https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${CF_API_TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ prompt: composer(finalSubject, isColor), steps: 4 }),
        }
      );
      const d = await cfRes.json();
      if (cfRes.ok && d.success) { data = d; break; }
      lastMsg = d?.errors?.map((e) => e.message).join('; ') || `Cloudflare error (${cfRes.status})`;
    }
    if (!data) {
      console.error('Cloudflare API error:', lastMsg);
      return res.status(502).json({ error: lastMsg });
    }

    rec.count += 1;
    res.json({
      image: `data:image/jpeg;base64,${data.result.image}`,
      quota: { used: rec.count, limit: DAILY_LIMIT },
      translatedPrompt,
      engine,
    });
  } catch (err) {
    console.error('Generation failed:', err);
    res.status(500).json({ error: 'Generation failed. Check server logs.' });
  }
});

app.listen(PORT, () => {
  console.log(`✅ InkCraft proxy running at http://localhost:${PORT}`);
  console.log(`   Daily limit: ${DAILY_LIMIT} designs/IP`);
});
