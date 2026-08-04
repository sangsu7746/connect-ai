const functions = require("firebase-functions");
const admin = require("firebase-admin");
const cors = require("cors")({ origin: true });
const { EdgeTTS } = require("edge-tts-universal");

admin.initializeApp();
const db = admin.firestore();

// 가입 시 1회 지급하는 웰컴 코인 — headjim 공용 지갑 스케일(1,500코인 = $1) 기준.
// 프리미엄 영상 2~3개를 바로 체험할 수 있는 양으로, "무료 영구 + 코인" 모델의 온보딩 장치다.
const WELCOME_COINS = 3000;

/**
 * Cloud Functions: 신규 Firebase Auth 계정 생성 시 1회만 실행되는 트리거.
 * 1) 가입일(createdAt)을 서버에서 정확히 1번만 기록한다 — 클라이언트 계산에 맡기면 조작 가능.
 * 2) 웰컴 코인을 공용 지갑(wallets/{uid})에 지급한다 — 지갑 Worker(headjim-wallet)와 같은
 *    스키마(balance + ledger/{refId})로 쓰고, ledger 문서 존재 여부로 멱등 처리해 트리거가
 *    재시도돼도 이중 지급되지 않는다. Firestore 규칙은 클라이언트의 지갑 쓰기를 전면 차단하므로
 *    Admin SDK(여기)와 지갑 Worker만이 잔액을 만질 수 있다.
 */
exports.onUserCreate = functions.auth.user().onCreate(async (user) => {
  try {
    await db.collection('users').doc(user.uid).set({
      createdAt: admin.firestore.FieldValue.serverTimestamp(),
    }, { merge: true });
  } catch (e) {
    console.error(`Failed to stamp createdAt for new user ${user.uid}:`, e);
  }

  // ── 매크로 가입 방어 ──
  // 이메일/비밀번호 가입은 생성 시점에 emailVerified=false 이므로 즉시 지급하지 않는다.
  // (스크립트로 가짜 이메일 계정을 무한 생성해 웰컴 코인을 수집하는 공격 차단)
  // 이런 계정은 이메일 인증을 마친 뒤 headjimweb codebase의 claimWelcomeBonus
  // 콜러블로 청구하며, 멱등 키(wallets/{uid}/ledger/welcome-{uid})를 공유해
  // 두 경로가 중복 지급하지 않는다. Google 가입은 이메일이 항상 인증돼 있어 즉시 지급.
  const viaGoogle = (user.providerData || []).some((p) => p.providerId === 'google.com');
  if (!viaGoogle && !user.emailVerified) {
    console.log(`Welcome coins deferred (email not verified yet): ${user.uid}`);
    return;
  }

  try {
    const walletRef = db.collection('wallets').doc(user.uid);
    const ledgerRef = walletRef.collection('ledger').doc(`welcome-${user.uid}`);
    await db.runTransaction(async (tx) => {
      const ledgerSnap = await tx.get(ledgerRef);
      if (ledgerSnap.exists) return; // 이미 지급됨 (트리거 재시도 등) — 멱등
      const walletSnap = await tx.get(walletRef);
      const balance = walletSnap.exists ? (walletSnap.data().balance || 0) : 0;
      tx.set(walletRef, {
        balance: balance + WELCOME_COINS,
        updatedAt: admin.firestore.FieldValue.serverTimestamp(),
      }, { merge: true });
      tx.set(ledgerRef, {
        delta: WELCOME_COINS,
        app: 'homage-video',
        reason: 'welcome_bonus',
        createdAt: admin.firestore.FieldValue.serverTimestamp(),
      });
    });
    console.log(`Welcome coins granted: ${user.uid} +${WELCOME_COINS}`);
  } catch (e) {
    // 지급 실패는 로그만 남긴다 — 지갑 Worker의 /admin/grant로 수동 지급해 보전할 수 있다
    console.error(`Failed to grant welcome coins to ${user.uid}:`, e);
  }
});

// corsProxy가 중계할 수 있는 호스트 목록.
// 이게 없으면 이 함수는 "아무 URL이나 대신 호출해주는" 공개 릴레이(SSRF)가 되어,
// 내부망 주소나 제3자 서버를 우리 함수 이름으로 때리는 데 악용될 수 있다.
const PROXY_ALLOWED_HOSTS = [
  'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com',   // Alibaba
  'generativelanguage.googleapis.com',                        // Gemini · Veo
  'api-singapore.klingai.com', 'api.klingai.com',             // Kling
  'api.minimax.io', 'api.minimaxi.com', 'api.minimax.chat',   // Hailuo(MiniMax)
  'ark.ap-southeast.bytepluses.com',                          // Seedance(ModelArk)
  'www.kaggle.com',                                           // Kaggle(LTX)
  'image.pollinations.ai',                                    // 무료 이미지 폴백
];

/** 요청 endpoint가 허용 호스트인지 — 서브도메인 몰래 끼워넣기를 막으려 정확히 일치만 허용한다. */
function isAllowedProxyTarget(endpoint) {
  try {
    const url = new URL(endpoint);
    if (url.protocol !== 'https:') return false;
    if (PROXY_ALLOWED_HOSTS.includes(url.hostname)) return true;
    // Veo 결과 파일은 googleapis.com 하위의 서명된 다운로드 주소로 리다이렉트된다
    return url.hostname.endsWith('.googleapis.com');
  } catch {
    return false;
  }
}

/**
 * Cloud Functions: CORS 차단 API 우회 프록시
 *
 * ⚠️ 이 함수는 사용자의 유료 API 키를 받아 외부로 중계한다. 그래서 두 가지를 반드시 지킨다:
 *  1) 로그인 검증 — 아무나 호출해 남의 Functions 비용을 쓰거나 릴레이로 악용하지 못하게
 *  2) 목적지 화이트리스트 — 임의 URL을 때리는 SSRF 통로가 되지 않게
 * (edgeTTS 등 다른 함수는 이미 1)을 하고 있었는데 이 함수만 빠져 있었다)
 */
exports.corsProxy = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') {
      return res.status(405).send('Method Not Allowed');
    }

    const uid = await verifyBearer(req);
    if (!uid) {
      return res.status(401).send('AI 기능은 로그인 후 이용할 수 있어요.');
    }

    const fetch = (...args) => import('node-fetch').then(({default: f}) => f(...args));
    const { provider, apiKey, method, endpoint, headers = {}, payload } = req.body;

    if (!provider || !apiKey || !endpoint) {
      return res.status(400).send('Missing required fields (provider, apiKey, endpoint)');
    }

    if (!isAllowedProxyTarget(endpoint)) {
      console.warn(`corsProxy: 허용되지 않은 대상 차단 uid=${uid} endpoint=${endpoint}`);
      return res.status(400).send('허용되지 않은 API 주소예요.');
    }

    try {
      const fetchHeaders = { ...headers };

      // 제공자별 인증 헤더 자동 매핑
      if (provider === 'alibaba') {
        fetchHeaders['Authorization'] = `Bearer ${apiKey}`;
        fetchHeaders['Content-Type'] = 'application/json';
      } else if (provider === 'kling') {
        fetchHeaders['Authorization'] = `Bearer ${apiKey}`;
        fetchHeaders['Content-Type'] = 'application/json';
      } else if (provider === 'hailuo') {
        fetchHeaders['Authorization'] = `Bearer ${apiKey}`;
        fetchHeaders['Content-Type'] = 'application/json';
      } else if (provider === 'gemini') {
        // Gemini는 Authorization 헤더가 아니라 endpoint의 key 쿼리파라미터로 인증한다
        fetchHeaders['Content-Type'] = 'application/json';
      } else if (provider === 'kaggle') {
        // Kaggle API는 Basic 인증(base64(username:key))을 쓴다. 단, 커널 output의 파일 URL은
        // 서명된 스토리지 주소라 Authorization 헤더를 붙이면 서명 검증과 충돌할 수 있어
        // kaggle.com API 호출에만 인증을 붙인다.
        if (endpoint.startsWith('https://www.kaggle.com/')) {
          fetchHeaders['Authorization'] = `Basic ${apiKey}`;
        }
        fetchHeaders['Content-Type'] = 'application/json';
      } else {
        fetchHeaders['Authorization'] = `Bearer ${apiKey}`;
      }

      const fetchOptions = {
        method: method || 'POST',
        headers: fetchHeaders,
      };

      if (payload && (method === 'POST' || method === 'PUT')) {
        fetchOptions.body = JSON.stringify(payload);
      }

      console.log(`Proxying request for ${provider} to ${endpoint}`);
      const apiRes = await fetch(endpoint, fetchOptions);
      const contentType = apiRes.headers.get('content-type') || '';

      if (contentType.includes('application/json')) {
        const data = await apiRes.json();
        res.status(apiRes.status).json(data);
      } else if (
        contentType.startsWith('video/') ||
        contentType.includes('octet-stream') ||
        contentType.startsWith('audio/') ||
        contentType.startsWith('image/')
      ) {
        // 바이너리 응답(Kaggle 커널 출력 mp4 등)은 텍스트로 읽으면 깨지므로 base64로 감싸 전달한다
        const buf = Buffer.from(await apiRes.arrayBuffer());
        res.status(apiRes.status).json({ base64: buf.toString('base64'), contentType });
      } else {
        const text = await apiRes.text();
        res.status(apiRes.status).send(text);
      }
    } catch (err) {
      console.error('CORS Proxy internal error:', err);
      res.status(500).send(err.message);
    }
  });
});

// (제거됨) paypalWebhook — 구독 결제가 코인 전용 모델로 전환되며 내려갔다. 웹훅 서명 검증이
// 없어서 아무나 POST 한 번으로 entitlements를 pro로 바꿀 수 있는 보안 구멍이기도 했다.
// 코인 결제 검증·적립은 지갑 Worker(headjim-wallet)의 /payments/paypal/credit이 서버측에서
// PayPal 주문을 직접 조회해 처리한다. 구독을 재도입할 땐 반드시 웹훅 서명 검증부터 붙일 것.

// 플랜별 월간 음성 생성(TTS) 한도 — Pro는 무제한(Infinity는 Firestore에 못 쓰므로 한도 검사 자체를 건너뜀)
// ⚠️ 광고 영상은 씬 1개당 TTS 1회를 쓴다(6씬 광고 = 6회). 예전 값(free:30)은 월 5편이면 소진돼
// 제작 자체가 막혔고, 초과분이 조용히 무음 씬으로 떨어져 원인 파악도 어려웠다.
// edgeTTS는 API 요금이 없고 Cloud Functions 호출 비용만 드는 무료 경로라 한도를 넉넉히 잡는다.
const TTS_MONTHLY_LIMIT = { free: 300, basic: 1000 };

/**
 * Cloud Functions: Edge TTS(Microsoft Edge 브라우저의 무료 TTS 서비스, 비공식 API) 대사 음성 합성.
 * edge-tts-universal 라이브러리로 웹소켓 프로토콜을 대신 처리한다 — 키 불필요, 무료.
 * 이 호출 자체는 Firebase Functions 비용을 발생시키는 지점이라, 로그인한 사용자만 쓸 수 있게 하고
 * 플랜별 월간 한도를 서버(Admin SDK)에서 직접 세어 확인한다 — 클라이언트가 임의로 조작 못 하게
 * usage/{uid}/tts/{yyyy-mm} 문서는 firestore.rules에서 클라이언트 쓰기를 막아뒀다.
 */
exports.edgeTTS = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') {
      return res.status(405).send('Method Not Allowed');
    }

    const { text, voice, rate, pitch, volume } = req.body || {};
    if (!text || !voice) {
      return res.status(400).send('Missing required fields (text, voice)');
    }

    // 1. 로그인 확인 — 비로그인 사용자는 사용량을 추적할 방법이 없어 음성 생성을 제공하지 않는다
    // (호출부는 이미 음성 합성 실패 시 자막만으로 우아하게 진행하도록 돼 있어 서비스 전체는 안 막힌다)
    const authHeader = req.headers.authorization || '';
    const idToken = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
    if (!idToken) {
      return res.status(401).send('음성 생성은 로그인 후 이용할 수 있어요.');
    }
    let uid;
    try {
      uid = (await admin.auth().verifyIdToken(idToken)).uid;
    } catch (e) {
      return res.status(401).send('로그인 정보가 유효하지 않아요. 다시 로그인해주세요.');
    }

    // 2. 플랜별 월간 사용량 한도 확인 및 기록
    try {
      const entitlementSnap = await db.collection('entitlements').doc(uid).get();
      const data = entitlementSnap.exists ? entitlementSnap.data() : null;
      const isExpired = data?.expiresAt && data.expiresAt.toDate().getTime() < Date.now();
      const plan = (!data || isExpired) ? 'free' : (data.plan || 'free');
      const limit = TTS_MONTHLY_LIMIT[plan]; // pro는 목록에 없어 undefined → 한도 검사 생략

      if (limit !== undefined) {
        const monthId = new Date().toISOString().slice(0, 7); // "2026-07"
        const usageRef = db.collection('usage').doc(uid).collection('tts').doc(monthId);
        const usageSnap = await usageRef.get();
        const currentCount = usageSnap.exists ? (usageSnap.data().count || 0) : 0;

        if (currentCount >= limit) {
          return res.status(429).send(
            `이번 달 음성 생성 한도(${limit}회)를 모두 사용했어요. 다음 달에 초기화되거나, 플랜을 업그레이드하면 더 많이 쓸 수 있어요.`
          );
        }

        await usageRef.set({
          count: admin.firestore.FieldValue.increment(1),
          limit,
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        }, { merge: true });
      }
    } catch (e) {
      // 사용량 확인 자체가(일시적 DB 문제 등으로) 실패해도 TTS 서비스 전체를 막지는 않는다
      console.error('TTS usage check failed (요청은 계속 진행):', e);
    }

    // 3. 실제 TTS 합성
    try {
      const tts = new EdgeTTS(text, voice, {
        rate: rate || '+0%',
        pitch: pitch || '+0Hz',
        volume: volume || '+0%',
      });
      const result = await tts.synthesize();
      const audioBuffer = Buffer.from(await result.audio.arrayBuffer());
      res.setHeader('Content-Type', result.audio.type || 'audio/mpeg');
      res.status(200).send(audioBuffer);
    } catch (err) {
      console.error('Edge TTS error:', err);
      res.status(500).send(err.message);
    }
  });
});

// ════════════════════════════════════════════════════════════════
// AdStudio — 제품 자료 분석 + 광고 영상 생성
// 오마주 패턴 그대로: API 키는 서버에만, 클라이언트는 ID 토큰 인증,
// 코인 차감은 wallets/{uid} 트랜잭션 + ledger 멱등 기록.
// ⚠️ functions 배포는 한 저장소에서만 — 배포 전 오마주 원본 저장소 functions와 병합할 것.
// ════════════════════════════════════════════════════════════════

// 광고 생성 단가 (코인) — AI 배우(LTX)는 GPU 비용이 커서 사진 배우(로컬 CV)보다 비싸다
const AD_COST = { ai: 100, photo: 50 };

/** Bearer ID 토큰 검증 공통부 — 실패 시 null */
async function verifyBearer(req) {
  const authHeader = req.headers.authorization || '';
  const idToken = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
  if (!idToken) return null;
  try {
    return (await admin.auth().verifyIdToken(idToken)).uid;
  } catch (e) {
    return null;
  }
}

/**
 * AdStudio: 제품 자료 분석 — 텍스트 또는 URL을 받아 서버의 Gemini 키로 분석하고
 * 광고 컨셉 JSON(제품명·특징·타겟·나레이션 등)을 돌려준다.
 */
exports.analyzeProduct = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

    const uid = await verifyBearer(req);
    if (!uid) return res.status(401).send('분석은 로그인 후 이용할 수 있어요.');

    const { text, url, imageDataUrl } = req.body || {};
    if (!text && !url && !imageDataUrl) return res.status(400).send('text, url 또는 imageDataUrl이 필요해요.');

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) return res.status(500).send('서버에 Gemini API 키가 설정되지 않았어요.');

    const fetch = (...args) => import('node-fetch').then(({ default: f }) => f(...args));

    try {
      // 스크린샷 이미지면 Gemini Vision 멀티모달 파트로 구성한다
      let imagePart = null;
      if (imageDataUrl) {
        const m = String(imageDataUrl).match(/^data:(image\/[\w.+-]+);base64,(.+)$/);
        if (!m) return res.status(400).send('이미지 형식이 잘못됐어요. 스크린샷을 다시 올려주세요.');
        imagePart = { inlineData: { mimeType: m[1], data: m[2] } };
      }

      // URL 입력이면 서버가 대신 가져와 본문 텍스트를 추출한다 (클라이언트 CORS 우회)
      let sourceText = text || '';
      if (!imagePart && url) {
        const pageRes = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (AdStudio bot)' } });
        const html = await pageRes.text();
        sourceText = html
          .replace(/<script[\s\S]*?<\/script>/gi, ' ')
          .replace(/<style[\s\S]*?<\/style>/gi, ' ')
          .replace(/<[^>]+>/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
      }
      sourceText = sourceText.slice(0, 8000); // 프롬프트 비용 상한

      // 스크립트로만 그려지는 SPA는 HTML 본문이 거의 비어 있다 — Gemini에 넘겨봐야
      // 지어낸 답이 오므로 여기서 명확한 안내로 끊는다
      if (!imagePart && url && sourceText.length < 80) {
        return res.status(422).send(
          '이 페이지는 읽을 수 있는 텍스트가 거의 없어요. 텍스트 탭에 제품 소개를 붙여넣어 주세요.'
        );
      }

      const prompt = [
        '당신은 광고 영상 기획 전문가입니다. 아래 제품/기업 자료를 분석해 광고 컨셉을 만들어주세요.',
        '',
        imagePart
          ? '자료: 첨부한 이미지는 제품/기업 소개 페이지의 스크린샷입니다. 이미지 속 텍스트·상품 정보를 읽으세요.'
          : '자료:',
        imagePart ? '' : sourceText,
        '',
        '다음 JSON 형식으로만 답하세요 (한국어, 다른 텍스트 금지):',
        '{"productName":"제품명","description":"한 문장 설명","keyFeatures":["기능1","기능2","기능3"],',
        '"targetAudience":"타겟 고객층","mainBenefit":"핵심 이점 한 문장",',
        '"narration":"광고 나레이션 스크립트 (약 30초 분량, 자연스러운 구어체)",',
        '"callToAction":"행동 유도 문구","tone":"energetic|calm|professional 중 하나"}',
      ].join('\n');

      const parts = imagePart ? [{ text: prompt }, imagePart] : [{ text: prompt }];
      // 모델을 하나로 하드코딩하면 Google의 모델 폐기 때 서버 폴백까지 죽는다 — 최신부터 차례로
      // 시도하고, 404(모델 없음)일 때만 다음 후보로 넘어간다 (2026-07 기준 최신 순)
      const GEMINI_MODELS = ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-1.5-flash'];
      let gemData = null;
      for (const model of GEMINI_MODELS) {
        const gemRes = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${geminiApiKey}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              contents: [{ parts }],
              generationConfig: { temperature: 0.7, maxOutputTokens: 1024 },
            }),
          }
        );
        gemData = await gemRes.json();
        if (gemRes.ok) break;
        if (gemRes.status !== 404) break;
        console.warn(`Gemini 모델 ${model} 사용 불가(404) — 다음 후보로 시도`);
      }
      const content = gemData.candidates?.[0]?.content?.parts?.[0]?.text || '';
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        console.error('Gemini 응답 파싱 실패:', content.slice(0, 300));
        return res.status(502).send('분석 결과를 이해하지 못했어요. 다시 시도해주세요.');
      }

      // 서버 비용이 드는 호출이므로 월간 사용량을 서버가 집계한다 (edgeTTS와 같은 패턴)
      // 기록 실패가 분석 응답 자체를 막지는 않는다 (에뮬레이터 등 자격증명 없는 환경 포함)
      try {
        const monthId = new Date().toISOString().slice(0, 7);
        await db.collection('usage').doc(uid).collection('gemini').doc(monthId).set({
          count: admin.firestore.FieldValue.increment(1),
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        }, { merge: true });
      } catch (usageErr) {
        console.error('Gemini usage 기록 실패 (응답은 계속 진행):', usageErr.message);
      }

      res.json(JSON.parse(jsonMatch[0]));
    } catch (err) {
      console.error('analyzeProduct error:', err);
      res.status(500).send('분석 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.');
    }
  });
});

/**
 * AdStudio: 광고 영상 생성 요청 — 배우 모드(ai|photo)에 따라 코인을 차감하고 작업을 큐잉.
 * 실제 렌더링 연동(LTX Kaggle 커널 / extraction 무빙포토)은 adJobs/{jobId} 문서를 큐로 사용.
 */
exports.generateAd = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

    const uid = await verifyBearer(req);
    if (!uid) return res.status(401).send('영상 생성은 로그인 후 이용할 수 있어요.');

    const { mode, narration, productName, sceneHint, duration, musicMood, voice } = req.body || {};
    const cost = AD_COST[mode];
    if (!cost) return res.status(400).send('mode는 ai 또는 photo여야 해요.');
    if (!narration) return res.status(400).send('narration이 필요해요.');

    const jobId = `ad-${mode}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    try {
      // 코인 차감 — 잔액 확인과 차감·원장 기록을 단일 트랜잭션으로 (오마주 지갑 불변식)
      const walletRef = db.collection('wallets').doc(uid);
      await db.runTransaction(async (tx) => {
        const walletSnap = await tx.get(walletRef);
        const balance = walletSnap.exists ? (walletSnap.data().balance || 0) : 0;
        if (balance < cost) {
          throw new Error('INSUFFICIENT_COINS');
        }
        tx.set(walletRef, {
          balance: balance - cost,
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        }, { merge: true });
        tx.set(walletRef.collection('ledger').doc(jobId), {
          delta: -cost,
          app: 'adstudio',
          reason: mode === 'ai' ? 'ad_video_ai' : 'ad_video_photo',
          createdAt: admin.firestore.FieldValue.serverTimestamp(),
        });
      });

      // 작업 큐 문서 — 렌더 워커(LTX/extraction 연동)가 status를 갱신한다
      await db.collection('adJobs').doc(jobId).set({
        userId: uid,
        mode,
        productName: productName || '',
        narration,
        sceneHint: sceneHint || '',
        duration: duration || 30,
        musicMood: musicMood || 'energetic',
        voice: voice || 'female',
        cost,
        status: 'queued',
        progress: 0,
        createdAt: admin.firestore.FieldValue.serverTimestamp(),
      });

      res.json({ jobId, status: 'queued', estimatedTime: 240000, cost });
    } catch (err) {
      if (err.message === 'INSUFFICIENT_COINS') {
        return res.status(402).send(`코인이 부족해요. (필요: ${cost}코인) 충전 후 다시 시도해주세요.`);
      }
      console.error('generateAd error:', err);
      res.status(500).send('생성 요청 중 오류가 발생했어요.');
    }
  });
});

// ════════════════════════════════════════════════════════════════
// AdStudio 오마주: 유튜브 광고 검색
// ════════════════════════════════════════════════════════════════

/** 캐시 수명 7일 — 유튜브 약관이 캐시 데이터를 30일 내 갱신·삭제하도록 요구한다 */
const YT_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
/**
 * 한 번에 25개를 받아둔다. search.list 는 결과 개수와 무관하게 비용이 같으므로
 * (하루 약 100회 한도), 25개를 받아 5개씩 보여주면 "다른 후보 보기"가 공짜가 된다.
 */
const YT_MAX_RESULTS = 25;

/** 검색어 → 캐시 문서 id (Firestore 문서 id 제약을 피해 해시로 만든다) */
function ytCacheKey(q) {
  return require('crypto').createHash('sha1').update(q).digest('hex');
}

/** ISO8601 duration(PT1M30S) → 초. videos.list 가 이 형식으로 준다 */
function ytParseDuration(iso) {
  const m = /^P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso || '');
  if (!m) return 0;
  return (+(m[1] || 0)) * 3600 + (+(m[2] || 0)) * 60 + (+(m[3] || 0));
}

exports.youtubeSearch = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

    const uid = await verifyBearer(req);
    if (!uid) return res.status(401).send('검색은 로그인 후 이용할 수 있어요.');

    const apiKey = process.env.YOUTUBE_API_KEY;
    if (!apiKey) return res.status(503).send('서버에 YouTube API 키가 설정되지 않았어요.');

    const fetchFn = (...args) => import('node-fetch').then(({ default: f }) => f(...args));

    // ── 모드 2: 단일 영상 정보 조회 (직접 URL 입력 검증용) ──
    // videos.list 는 1유닛이라 search.list(100유닛)와 달리 부담이 없다.
    // 사용자가 2시간짜리 영상을 붙여넣으면 Gemini 무료 한도(하루 8시간 분량)를
    // 한 번에 태우므로, 분석 전에 길이를 먼저 확인한다.
    const videoId = String((req.body || {}).videoId || '').trim();
    if (videoId) {
      if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) return res.status(400).send('영상 id 형식이 올바르지 않아요.');
      try {
        const r = await fetchFn('https://www.googleapis.com/youtube/v3/videos'
          + `?part=snippet,contentDetails&id=${videoId}&key=${apiKey}`);
        if (!r.ok) return res.status(502).send('영상 정보를 가져오지 못했어요.');
        const d = await r.json();
        const item = (d.items || [])[0];
        if (!item) return res.status(404).send('영상을 찾을 수 없어요. 공개 영상인지 확인해주세요.');
        return res.json({
          videoId,
          title: item.snippet.title,
          channelTitle: item.snippet.channelTitle,
          thumbnailUrl: (item.snippet.thumbnails.medium || item.snippet.thumbnails.default || {}).url || '',
          durationSec: ytParseDuration(item.contentDetails.duration),
        });
      } catch (e) {
        console.error('youtubeSearch(videoId) 실패:', e);
        return res.status(502).send('영상 정보를 가져오지 못했어요.');
      }
    }

    // ── 모드 1: 검색 ──
    const q = String((req.body || {}).q || '').trim();
    if (!q) return res.status(400).send('검색어가 필요해요.');

    const db = admin.firestore();
    const ref = db.collection('youtubeSearchCache').doc(ytCacheKey(q));

    try {
      const snap = await ref.get();
      if (snap.exists) {
        const data = snap.data();
        if (data.fetchedAt && Date.now() - data.fetchedAt < YT_CACHE_TTL_MS) {
          return res.json({ items: data.items || [], cached: true });
        }
      }
    } catch (e) {
      console.warn('youtubeSearch: 캐시 조회 실패, 원본 호출로 진행', e);
    }

    const url = 'https://www.googleapis.com/youtube/v3/search'
      + `?part=snippet&type=video&videoEmbeddable=true&maxResults=${YT_MAX_RESULTS}`
      + `&q=${encodeURIComponent(q)}&key=${apiKey}`;

    try {
      const r = await fetchFn(url);
      if (r.status === 403) {
        // 쿼터 소진과 키 문제가 둘 다 403 으로 온다. 본문으로 구분한다.
        const body = await r.text();
        if (/quota/i.test(body)) {
          return res.status(429).send('오늘 자동검색 한도를 다 썼어요.');
        }
        console.error('youtubeSearch: 403', body.slice(0, 300));
        return res.status(503).send('유튜브 검색을 사용할 수 없어요.');
      }
      if (!r.ok) {
        console.error('youtubeSearch: HTTP', r.status);
        return res.status(502).send('유튜브 검색에 실패했어요.');
      }

      const data = await r.json();
      const items = (data.items || [])
        .filter(it => it.id && it.id.videoId)
        .map(it => ({
          videoId: it.id.videoId,
          title: it.snippet.title,
          channelTitle: it.snippet.channelTitle,
          thumbnailUrl: (it.snippet.thumbnails.medium || it.snippet.thumbnails.default || {}).url || '',
          publishedAt: it.snippet.publishedAt,
        }));

      try {
        await ref.set({ q, items, fetchedAt: Date.now() });
      } catch (e) {
        console.warn('youtubeSearch: 캐시 저장 실패 (응답은 정상 반환)', e);
      }

      return res.json({ items, cached: false });
    } catch (e) {
      console.error('youtubeSearch 실패:', e);
      return res.status(502).send('유튜브 검색에 실패했어요.');
    }
  });
});
