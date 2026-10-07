// ════════════════════════════════════════════════════════════════
// AdStudio 광고 컨셉 4축 분류체계
//   축1 카테고리(대→소) · 축2 강조 포인트(소구점, 최대 2개)
//   축3 스토리 구성(기승전결 템플릿 = 스토리보드 뼈대) · 축4 톤&무드
// 스토리 구성 id(ad_*)는 project.conceptId로 저장되어
// storyboardGenerator가 해당 씬 템플릿 풀을 찾는 키가 된다.
// ════════════════════════════════════════════════════════════════

// ── 축 1. 광고 카테고리 ──────────────────────────────────────────
export interface AdCategory {
  id: string
  emoji: string
  label: string
  subs: { id: string; label: string }[]
}

export const AD_CATEGORIES: AdCategory[] = [
  {
    id: 'corporate', emoji: '🏢', label: '기업 광고',
    subs: [
      { id: 'brand_awareness', label: '브랜드 인지도' },
      { id: 'philosophy', label: '기업 철학·비전' },
      { id: 'recruit', label: '채용' },
      { id: 'esg', label: 'ESG·사회공헌' },
      { id: 'rebranding', label: '리브랜딩' },
    ],
  },
  {
    id: 'tech', emoji: '⚙️', label: '기술 광고',
    subs: [
      { id: 'software', label: 'SW·앱·플랫폼' },
      { id: 'ai_data', label: 'AI·데이터' },
      { id: 'hardware', label: '하드웨어·장비' },
      { id: 'b2b', label: 'B2B 솔루션' },
      { id: 'patent', label: '특허·신기술' },
    ],
  },
  {
    id: 'beauty_health', emoji: '🧴', label: '제품 — 뷰티·헬스',
    subs: [
      { id: 'cosmetics', label: '화장품' },
      { id: 'supplement', label: '건강기능식품' },
      { id: 'medicine', label: '의약외품·약' },
      { id: 'personal_care', label: '퍼스널케어' },
    ],
  },
  {
    id: 'food', emoji: '🍎', label: '제품 — 식품',
    subs: [
      { id: 'fresh', label: '신선식품' },
      { id: 'natural', label: '자연식품·유기농' },
      { id: 'processed', label: '가공식품·간편식' },
      { id: 'beverage', label: '음료·카페' },
      { id: 'diet', label: '건강식·비건' },
    ],
  },
  {
    id: 'goods', emoji: '📦', label: '제품 — 공산품',
    subs: [
      { id: 'living', label: '생활용품' },
      { id: 'electronics', label: '가전·전자기기' },
      { id: 'furniture', label: '가구·인테리어' },
      { id: 'fashion', label: '패션·잡화' },
      { id: 'kids', label: '유아·키즈' },
      { id: 'pet', label: '반려동물' },
    ],
  },
  {
    id: 'service', emoji: '🛎️', label: '서비스 광고',
    subs: [
      { id: 'local', label: '매장·식당' },
      { id: 'education', label: '교육·클래스' },
      { id: 'travel', label: '여행·숙박' },
      { id: 'finance', label: '금융·보험' },
      { id: 'subscription', label: '구독 서비스' },
    ],
  },
  {
    id: 'promotion', emoji: '🎉', label: '프로모션 광고',
    subs: [
      { id: 'launch', label: '신제품 런칭' },
      { id: 'sale', label: '할인·기획전' },
      { id: 'season', label: '시즌 이벤트' },
      { id: 'popup', label: '팝업·오픈 안내' },
    ],
  },
]

// ── 축 2. 강조 포인트 (소구점) ───────────────────────────────────
export interface AdEmphasisGroup {
  label: string
  items: { id: string; label: string }[]
}

export const AD_EMPHASIS_GROUPS: AdEmphasisGroup[] = [
  {
    label: '제품 자체',
    items: [
      { id: 'ingredient', label: '원재료·성분' },
      { id: 'feature', label: '기능' },
      { id: 'performance', label: '성능·효과' },
      { id: 'design', label: '디자인' },
      { id: 'quality', label: '내구성·품질' },
      { id: 'usability', label: '사용 편의성' },
    ],
  },
  {
    label: '신뢰',
    items: [
      { id: 'certification', label: '인증·특허·수상' },
      { id: 'tradition', label: '전통·장인정신' },
      { id: 'origin', label: '원산지·생산과정' },
      { id: 'safety', label: '안전성' },
      { id: 'expert', label: '전문가 추천' },
    ],
  },
  {
    label: '공감',
    items: [
      { id: 'review', label: '고객 후기' },
      { id: 'before_after', label: 'Before/After 변화' },
      { id: 'lifestyle', label: '라이프스타일' },
      { id: 'brand_story', label: '브랜드 스토리' },
    ],
  },
  {
    label: '혜택',
    items: [
      { id: 'price', label: '가격·가성비' },
      { id: 'limited', label: '한정·희소성' },
      { id: 'gift', label: '사은·이벤트' },
      { id: 'trial', label: '무료 체험' },
    ],
  },
  {
    label: '가치',
    items: [
      { id: 'eco', label: '친환경·지속가능' },
      { id: 'innovation', label: '혁신·기술력' },
      { id: 'social', label: '사회적 가치' },
    ],
  },
]

export const AD_EMPHASIS_LABELS: Record<string, string> = Object.fromEntries(
  AD_EMPHASIS_GROUPS.flatMap(g => g.items.map(i => [i.id, i.label]))
)

// ── 축 3. 스토리 구성 (기승전결) ─────────────────────────────────
export interface AdStructure {
  id: string
  emoji: string
  label: string
  flow: string
  goodFor: string
}

export const AD_STRUCTURES: AdStructure[] = [
  { id: 'ad_problem', emoji: '💡', label: '문제 → 해결형', flow: '불편한 일상 → 제품 등장 → 해결 → CTA', goodFor: '기능·성능 강조' },
  { id: 'ad_beforeafter', emoji: '✨', label: 'Before/After형', flow: '사용 전 → 전환 → 사용 후 → CTA', goodFor: '화장품·다이어트·청소' },
  { id: 'ad_demo', emoji: '🔬', label: '시연/데모형', flow: '궁금증 → 실제 작동 → 결과 확대 → CTA', goodFor: '기술·가전·B2B' },
  { id: 'ad_origin', emoji: '🌾', label: '산지/과정형', flow: '산지·원료 → 만드는 과정 → 완성품 → CTA', goodFor: '신선식품·장인정신' },
  { id: 'ad_lifestyle', emoji: '🌅', label: '라이프스타일형', flow: '감성 무드 → 제품이 자연스럽게 → 여운 → CTA', goodFor: '뷰티·패션·카페' },
  { id: 'ad_testimonial', emoji: '💬', label: '증언/후기형', flow: '고객 고민 → 사용 경험담 → 만족 → CTA', goodFor: '건기식·교육·서비스' },
  { id: 'ad_brandstory', emoji: '📖', label: '브랜드 서사형', flow: '창업·철학 → 걸어온 길 → 약속 → 로고', goodFor: '기업 광고' },
  { id: 'ad_countdown', emoji: '⏰', label: '카운트다운형', flow: '티저 → 혜택 공개 → 마감 임박 → CTA', goodFor: '프로모션·런칭' },
]

// 카테고리별 기본 추천 스토리 구성 (Gemini 추천 실패 시 폴백)
export const CATEGORY_DEFAULT_STRUCTURE: Record<string, string> = {
  corporate: 'ad_brandstory',
  tech: 'ad_demo',
  beauty_health: 'ad_beforeafter',
  food: 'ad_origin',
  goods: 'ad_problem',
  service: 'ad_testimonial',
  promotion: 'ad_countdown',
}

// ── 축 4. 톤 & 무드 ─────────────────────────────────────────────
export interface AdTone {
  id: string
  label: string
  promptEn: string   // 키프레임 프롬프트에 덧붙는 무드 데코레이터
}

// 톤마다 "밝기 베이스라인"을 명시한다 — 이 앱의 목적은 기업·제품·기술의 부각이라
// 화면이 어두워 피사체가 안 읽히면 광고로서 실패한다. 프리미엄만 어두운 배경을 허용하되,
// 그 경우에도 제품에는 강한 라이팅을 걸어 "어둠"이 아니라 "대비"가 되게 한다.
export const AD_TONES: AdTone[] = [
  { id: 'energetic', label: '활기찬', promptEn: 'vibrant energetic mood, bright high-key lighting, saturated colors, dynamic composition' },
  { id: 'emotional', label: '감성적', promptEn: 'soft emotional mood, bright warm golden light, airy exposure, gentle bokeh' },
  { id: 'professional', label: '신뢰감', promptEn: 'clean professional look, bright neutral daylight, well-lit modern interior, precise composition' },
  { id: 'premium', label: '프리미엄', promptEn: 'luxurious premium aesthetic, deep elegant background with the subject brightly lit by dramatic key and rim lighting, gold accents, high contrast' },
  { id: 'humorous', label: '유머러스', promptEn: 'playful humorous mood, bright cheerful lighting, pop colors, quirky composition' },
  { id: 'warm', label: '따뜻한', promptEn: 'warm cozy family mood, bright soft daylight through windows, homely atmosphere' },
  { id: 'trendy', label: '트렌디', promptEn: 'trendy modern style, bright clean backdrop with neon accents, urban vibe, typography-friendly framing' },
]

/**
 * 모든 광고 키프레임에 붙는 "불변 요구사항" — 조명 스타일이 아니라 가독성만 규정한다.
 *
 * 광고의 목적은 제품·기업·기술의 부각이므로 피사체가 안 읽히면 실패다. 하지만 그게 곧
 * "무조건 밝게"를 뜻하지는 않는다 — 어두운 화면에서도 강한 키라이트·림라이트로 피사체를
 * 또렷하게 만들 수 있고, 그런 연출이 더 잘 맞는 브랜드·트렌드도 많다.
 * 그래서 여기서는 밝기를 지정하지 않고 "읽힐 것"만 요구하며, 실제 룩은 AD_VISUAL_STYLES가 정한다.
 */
export const AD_CLARITY_BASE = 'the product and subject clearly readable with well-defined focal lighting, sharp focus on the subject'

// ── 축 5. 비주얼 스타일 (룩) ────────────────────────────────────
// 조명·질감의 방향을 정하는 축. 밝기를 규칙으로 강제하는 대신 여기서 "의도된 선택"으로 만든다.
// (2025~26년 숏폼 브랜드 영상에서 실제로 통용되는 룩들을 폭넓게 담았다 — 어두운 연출도
//  '실수'가 아니라 선택지로 존재해야 창작이 막히지 않는다)
export interface AdVisualStyle {
  id: string
  label: string
  desc: string
  promptEn: string
}

export const AD_VISUAL_STYLES: AdVisualStyle[] = [
  {
    id: 'clean_bright', label: '클린 브라이트', desc: '밝고 깔끔한 기본형 · 제품 가독성 최상',
    promptEn: 'bright high-key commercial lighting, clean uncluttered background, crisp product photography look',
  },
  {
    id: 'ugc_raw', label: 'UGC 리얼', desc: '폰으로 찍은 듯한 자연스러움 · 광고 티가 덜 남',
    promptEn: 'authentic user-generated content look, handheld smartphone footage feel, natural available light, slightly imperfect framing, unpolished and relatable',
  },
  {
    id: 'cinematic', label: '시네마틱', desc: '얕은 심도·고대비 · 브랜드 필름 느낌',
    promptEn: 'cinematic film look, shallow depth of field, rich contrast with deep shadows and bright highlights, subtle film grain, anamorphic mood',
  },
  {
    id: 'editorial', label: '에디토리얼', desc: '잡지 화보풍 · 강한 그래픽 구성',
    promptEn: 'high-fashion editorial photography, bold graphic composition, strong directional studio lighting, striking color blocking',
  },
  {
    id: 'neon_night', label: '네온 나이트', desc: '도시 야경·네온 · 테크/게이밍에 강함',
    promptEn: 'night urban scene lit by vivid neon signage and screen glow, wet reflective surfaces, cyberpunk color palette of teal and magenta, the product illuminated as the brightest element',
  },
  {
    id: 'retro_flash', label: '레트로 플래시', desc: 'Y2K 직광 플래시·그레인 · 트렌디한 무드',
    promptEn: 'Y2K retro direct-flash photography, harsh on-camera flash against a darker background, visible grain, nostalgic point-and-shoot aesthetic',
  },
  {
    id: 'minimal_mono', label: '미니멀 모노', desc: '단색 배경·여백 · 프리미엄 테크',
    promptEn: 'minimalist monochrome set, single seamless backdrop, generous negative space, precise sculptural lighting on the product',
  },
]

export const DEFAULT_VISUAL_STYLE = 'clean_bright'

// Gemini 분석의 tone(energetic|calm|professional) → 광고 톤 기본 매핑
export const ANALYSIS_TONE_MAP: Record<string, string> = {
  energetic: 'energetic',
  calm: 'emotional',
  professional: 'professional',
}

// ── AI 가상 배우 기본 프로필 (배우 설정 [4]에서 AI 모드 선택 시) ──
// "AI에게 전부 맡기기"는 결과가 널뛰므로, 성별·연령대·이미지를 기본 선택하게 해
// 스토리보드 창작(한국어 지시)과 키프레임 프롬프트(영어 묘사)에 일관되게 반영한다.
export interface AiActorProfile {
  gender: string
  age: string
  vibe: string
}

export const AI_ACTOR_GENDERS = [
  { id: 'female', label: '여성', en: 'a Korean woman' },
  { id: 'male', label: '남성', en: 'a Korean man' },
] as const

export const AI_ACTOR_AGES = [
  { id: '20s', label: '20대', en: 'in their 20s' },
  { id: '30s', label: '30대', en: 'in their 30s' },
  { id: '4050', label: '40~50대', en: 'in their 40s-50s' },
  { id: 'senior', label: '시니어', en: 'in their 60s or older' },
] as const

export const AI_ACTOR_VIBES = [
  { id: 'friendly', label: '밝고 친근한', en: 'bright friendly approachable look' },
  { id: 'professional', label: '전문가 느낌', en: 'professional trustworthy appearance, neat business attire' },
  { id: 'luxury', label: '세련·고급', en: 'elegant sophisticated high-fashion look' },
  { id: 'casual', label: '캐주얼·일상', en: 'casual everyday natural look' },
  { id: 'sporty', label: '활동적·스포티', en: 'athletic energetic sporty look' },
] as const

/** 프로필 → 한국어 설명 (Gemini 각본 지시용) — 예: "여성, 30대, 밝고 친근한 이미지" */
export function buildAiActorKo(p: AiActorProfile): string {
  const g = AI_ACTOR_GENDERS.find(x => x.id === p.gender)?.label || ''
  const a = AI_ACTOR_AGES.find(x => x.id === p.age)?.label || ''
  const v = AI_ACTOR_VIBES.find(x => x.id === p.vibe)?.label || ''
  return [g, a, `${v} 이미지`].filter(Boolean).join(', ')
}

/** 프로필 → 영어 프롬프트 조각 (키프레임 이미지 생성용) */
export function buildAiActorEn(p: AiActorProfile): string {
  const g = AI_ACTOR_GENDERS.find(x => x.id === p.gender)?.en || 'a person'
  const a = AI_ACTOR_AGES.find(x => x.id === p.age)?.en || ''
  const v = AI_ACTOR_VIBES.find(x => x.id === p.vibe)?.en || ''
  return [`${g} ${a}`.trim(), v, 'generic model face not resembling any real celebrity'].filter(Boolean).join(', ')
}

// ── 스토리 구성별 씬 템플릿 (기승전결 6컷) ───────────────────────
// storyboardGenerator의 SceneTemplate과 구조 동일(구조적 타이핑으로 호환).
// "제품"은 자리표시자 — Gemini 키가 있으면 실제 제품 정보로 매번 새로 창작되고,
// 이 원문은 키가 없거나 실패했을 때의 폴백이다.
// subjectRefs가 빈 씬은 제품 단독 컷, ['person_1']은 모델(배우) 등장 컷.
interface AdSceneTemplate {
  descKo: string
  keyframePromptEn: string
  motionPromptEn: string
  dialogueKo: string
  subjectRefs: string[]
}

export const AD_CONCEPT_TEMPLATES: Record<string, AdSceneTemplate[]> = {
  // 💡 문제 → 해결형
  ad_problem: [
    {
      descKo: '일상 속 불편한 순간, 모델의 답답한 표정 클로즈업.',
      // "Before"는 어둡게가 아니라 생기 없게 — 밝기는 유지하고 채도·온기만 뺀다.
      // (어두우면 피드 첫 프레임에서 그냥 지나가고, AI 생성 품질도 떨어진다)
      keyframePromptEn: 'A frustrated person struggling with an everyday inconvenience at home, bright but flat overcast daylight, pale washed-out desaturated colors, cluttered surroundings, close-up on tired expression',
      motionPromptEn: 'slow push-in on the frustrated face',
      dialogueKo: '매일 이 문제, 언제까지 참아야 할까요?',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '문제 상황이 반복되는 몽타주 — 한숨이 깊어진다.',
      keyframePromptEn: 'Montage-style shot of the same everyday problem repeating, messy details emphasized, bright flat lighting with muted low-saturation colors, overhead angle',
      motionPromptEn: 'quick cuts feel, subtle handheld shake',
      dialogueKo: '반복되는 불편, 해결책이 필요했죠.',
      subjectRefs: [],
    },
    {
      descKo: '제품이 빛과 함께 등장하는 히어로 컷.',
      keyframePromptEn: 'The product appearing as a hero shot on a clean pedestal, spotlight from above, background transitioning from grey to bright, floating particles',
      motionPromptEn: 'slow orbit around the product, light rays intensifying',
      dialogueKo: '그래서 준비했습니다.',
      subjectRefs: [],
    },
    {
      descKo: '모델이 제품을 사용하며 문제가 시원하게 해결된다.',
      keyframePromptEn: 'The person happily using the product, the previous problem visibly solved, bright clean lighting, satisfied smile',
      motionPromptEn: 'smooth tracking shot following the action',
      dialogueKo: '이렇게 간단하게 해결돼요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품의 핵심 기능 디테일 클로즈업.',
      keyframePromptEn: 'Extreme close-up of the product key feature in action, macro detail, crisp focus, premium commercial lighting',
      motionPromptEn: 'macro rack focus across the product detail',
      dialogueKo: '핵심 기능이 만드는 차이를 느껴보세요.',
      subjectRefs: [],
    },
    {
      descKo: '환해진 일상 — 제품과 로고, 행동 유도 문구로 마무리.',
      keyframePromptEn: 'Bright transformed daily life scene with the product placed naturally, logo space above, clean commercial end-frame composition',
      motionPromptEn: 'slow pull-back revealing the whole brighter scene',
      dialogueKo: '지금 바로 만나보세요.',
      subjectRefs: ['person_1'],
    },
  ],

  // ✨ Before/After형
  ad_beforeafter: [
    {
      descKo: 'Before — 거울 앞, 고민스러운 표정의 모델.',
      keyframePromptEn: 'A person looking at themselves in a mirror with a concerned expression, bright white bathroom with cool flat lighting, pale desaturated skin tones, before-state emphasized',
      motionPromptEn: 'slow push-in over the shoulder into the mirror',
      dialogueKo: '거울을 볼 때마다 신경 쓰였어요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '고민의 원인을 보여주는 디테일 컷.',
      keyframePromptEn: 'Close-up detail of the concern area, bright soft clinical lighting, honest documentary feel, clearly visible',
      motionPromptEn: 'gentle rack focus on the detail',
      dialogueKo: '혼자서는 해결이 어려웠죠.',
      subjectRefs: [],
    },
    {
      descKo: '제품 등장 — 성분/원리가 그래픽처럼 펼쳐진다.',
      keyframePromptEn: 'The product hero shot with elegant ingredient visualization swirling around it, water droplets, fresh botanical elements, luminous studio lighting',
      motionPromptEn: 'slow rotation of the product, ingredients orbiting',
      dialogueKo: '핵심 성분이 다르니까요.',
      subjectRefs: [],
    },
    {
      descKo: '제품을 정성껏 사용하는 루틴 컷.',
      keyframePromptEn: 'The person applying or using the product in a calm routine, soft warm light, serene close-up of hands and product',
      motionPromptEn: 'smooth slow-motion of the application gesture',
      dialogueKo: '매일의 루틴이 달라집니다.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: 'After — 환하게 달라진 모습, 자신감 있는 미소.',
      keyframePromptEn: 'The same person now glowing with confidence, bright airy lighting, visibly improved after-state, genuine smile at the mirror',
      motionPromptEn: 'slow reveal from mirror reflection to real face',
      dialogueKo: '달라진 저를 만났어요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품 라인업과 로고 — 변화를 약속하는 엔드 프레임.',
      keyframePromptEn: 'Product lineup on a clean bright pedestal, soft gradient background, logo space, premium commercial end-frame',
      motionPromptEn: 'slow pull-back with light sweep across products',
      dialogueKo: '당신의 변화, 지금 시작하세요.',
      subjectRefs: [],
    },
  ],

  // 🔬 시연/데모형
  ad_demo: [
    {
      // 오프닝은 암전 티저 대신 "밝은 임팩트"로 — 첫 프레임이 곧 피드 썸네일이라
      // 어두우면 스크롤에서 그냥 지나간다 (암전 티저는 이미 유명한 브랜드의 문법)
      descKo: '제품이 밝은 스튜디오에 단독으로 놓인 임팩트 오프닝.',
      keyframePromptEn: 'The product presented alone on a clean bright white studio backdrop, crisp even lighting, sharp detail, bold minimal composition with generous negative space',
      motionPromptEn: 'slow push-in on the product',
      dialogueKo: '무엇이 다른지, 직접 보여드릴게요.',
      subjectRefs: [],
    },
    {
      descKo: '제품 전원이 켜지고 작동을 시작하는 순간.',
      keyframePromptEn: 'The product powering on, indicator lights glowing, sleek surfaces reflecting cool studio light, high-tech atmosphere',
      motionPromptEn: 'macro push-in as the device activates',
      dialogueKo: '작동을 시작합니다.',
      subjectRefs: [],
    },
    {
      descKo: '실제 시연 — 성능이 눈앞에서 증명된다.',
      keyframePromptEn: 'The product performing its core function in a real test scenario, split-second action frozen crisply, professional lab-like setting',
      motionPromptEn: 'high-speed camera feel, dramatic slow motion of the action',
      dialogueKo: '보이시나요? 이게 실제 성능입니다.',
      subjectRefs: [],
    },
    {
      descKo: '수치·그래프가 떠오르는 성능 비교 컷.',
      // 데이터 시각화는 배경이 깊을 때 잘 읽히지만, 제품 자체는 반드시 밝게 조명해
      // "어두운 화면"이 아니라 "대비가 강한 화면"이 되게 한다
      keyframePromptEn: 'Clean infographic-style shot of the product brightly lit as the focal point against a deep minimal backdrop, glowing performance metrics and comparison bars floating around it, crisp high-contrast lighting',
      motionPromptEn: 'camera glides sideways as metrics animate up',
      dialogueKo: '숫자가 증명합니다.',
      subjectRefs: [],
    },
    {
      descKo: '전문가(모델)가 만족스럽게 결과를 확인한다.',
      keyframePromptEn: 'A professional examining the product result with an approving nod, modern workspace, confident expert atmosphere',
      motionPromptEn: 'steady dolly-in on the approving expression',
      dialogueKo: '전문가도 인정한 결과예요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품 히어로 컷과 로고 — 스펙 요약 엔드 프레임.',
      keyframePromptEn: 'Final hero shot of the product on a reflective black surface, key specs space around it, logo area, premium tech commercial ending',
      motionPromptEn: 'slow orbit ending in a centered hero framing',
      dialogueKo: '성능으로 답하겠습니다.',
      subjectRefs: [],
    },
  ],

  // 🌾 산지/과정형
  ad_origin: [
    {
      descKo: '이른 아침 산지의 풍경 — 안개 낀 밭과 떠오르는 해.',
      keyframePromptEn: 'Misty farmland at dawn, golden sunrise over fresh green fields, dew on leaves, pristine natural landscape',
      motionPromptEn: 'slow aerial glide over the misty fields',
      dialogueKo: '이야기는 이곳에서 시작됩니다.',
      subjectRefs: [],
    },
    {
      descKo: '정성스럽게 원재료를 수확하는 손길 클로즈업.',
      keyframePromptEn: 'Close-up of careful hands harvesting fresh raw ingredients, morning light through fingers, authentic texture and soil detail',
      motionPromptEn: 'gentle handheld follow of the harvesting hands',
      dialogueKo: '가장 좋은 것만 골라 담습니다.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '신선한 원재료의 디테일 — 물방울과 자연광.',
      keyframePromptEn: 'Macro shot of fresh raw ingredients with water droplets, vivid natural colors, sunlight backlighting the freshness',
      motionPromptEn: 'macro rack focus with water droplet falling in slow motion',
      dialogueKo: '자연 그대로의 신선함이에요.',
      subjectRefs: [],
    },
    {
      descKo: '깨끗한 시설에서 정성껏 만들어지는 과정.',
      keyframePromptEn: 'Clean production process, careful craftsmanship steps, warm workshop lighting, honest documentary style',
      motionPromptEn: 'smooth tracking along the making process',
      dialogueKo: '보이지 않는 과정까지 정직하게.',
      subjectRefs: [],
    },
    {
      descKo: '완성된 제품 — 자연광 아래 놓인 히어로 컷.',
      keyframePromptEn: 'The finished product beautifully placed on natural wood with soft daylight, fresh ingredients arranged around it, organic commercial styling',
      motionPromptEn: 'slow top-down reveal settling on the product',
      dialogueKo: '그렇게 완성됐습니다.',
      subjectRefs: [],
    },
    {
      descKo: '식탁 위 제품과 만족스러운 모델 — 산지의 약속 엔드 프레임.',
      keyframePromptEn: 'Warm table scene with the product and a smiling person enjoying it, family kitchen atmosphere, golden hour light, logo space',
      motionPromptEn: 'slow pull-back from the table into the warm scene',
      dialogueKo: '산지의 정직함을 식탁까지, 지금 만나보세요.',
      subjectRefs: ['person_1'],
    },
  ],

  // 🌅 라이프스타일형
  ad_lifestyle: [
    {
      descKo: '햇살 좋은 아침, 여유로운 일상의 시작.',
      keyframePromptEn: 'Sunlit serene morning interior, sheer curtains glowing, calm aesthetic lifestyle scene, soft warm tones',
      motionPromptEn: 'slow drift through the sunlit room',
      dialogueKo: '어느 좋은 아침이에요.',
      subjectRefs: [],
    },
    {
      descKo: '모델의 일상 루틴 속 감성적인 순간들.',
      keyframePromptEn: 'A person enjoying a calm daily routine, aesthetic lifestyle framing, natural window light, candid relaxed mood',
      motionPromptEn: 'gentle handheld following the routine',
      dialogueKo: '나를 위한 시간이죠.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품이 일상에 자연스럽게 스며든 컷.',
      keyframePromptEn: 'The product naturally placed within the lifestyle scene, being casually reached for, effortless product integration, aesthetic flat-lay elements',
      motionPromptEn: 'smooth rack focus from scene to the product',
      dialogueKo: '이 순간을 더 특별하게 해주는 것.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품 사용의 기분 좋은 디테일 클로즈업.',
      keyframePromptEn: 'Sensory close-up of the product in use, satisfying texture detail, soft glowing light, ASMR-like visual quality',
      motionPromptEn: 'slow-motion macro of the satisfying moment',
      dialogueKo: '작은 디테일이 하루를 바꿔요.',
      subjectRefs: [],
    },
    {
      descKo: '창밖을 보며 미소 짓는 모델 — 여운의 무드 컷.',
      keyframePromptEn: 'The person smiling softly by the window at golden hour, dreamy backlight, contemplative satisfied mood, cinematic bokeh',
      motionPromptEn: 'slow orbit with lens flare through the window light',
      dialogueKo: '이런 게 좋은 하루 아닐까요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '노을빛 속 제품과 로고 — 감성 엔드 프레임.',
      keyframePromptEn: 'The product bathed in golden sunset light on a minimal surface, long soft shadows, elegant logo space, emotional end-frame',
      motionPromptEn: 'slow push-in as sunset light sweeps across',
      dialogueKo: '당신의 일상에 초대합니다.',
      subjectRefs: [],
    },
  ],

  // 💬 증언/후기형
  ad_testimonial: [
    {
      descKo: '인터뷰 세팅 — 고민을 털어놓는 모델.',
      keyframePromptEn: 'Documentary interview setup, a person sharing their honest concern facing slightly off-camera, soft key light, authentic atmosphere',
      motionPromptEn: 'static interview framing with subtle push-in',
      dialogueKo: '솔직히 처음엔 반신반의했어요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '과거의 고민 상황 회상 컷.',
      keyframePromptEn: 'Flashback-style scene of the previous struggle, slightly desaturated tones, honest everyday setting',
      motionPromptEn: 'soft dreamy transition, gentle handheld',
      dialogueKo: '늘 같은 고민이 반복됐거든요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '제품을 처음 만난 순간.',
      keyframePromptEn: 'The person discovering the product, picking it up with curiosity, bright hopeful lighting shift, close-up on hands and product',
      motionPromptEn: 'rack focus from face to the product in hand',
      dialogueKo: '그러다 이 제품을 만났죠.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '일상에서 제품을 사용하는 실제 모습.',
      keyframePromptEn: 'Candid real-life usage of the product in daily routine, natural lighting, unposed documentary style',
      motionPromptEn: 'observational handheld following the usage',
      dialogueKo: '한 달을 써보니 확실히 다르더라고요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '환한 미소로 만족을 이야기하는 인터뷰 컷.',
      keyframePromptEn: 'Back to the interview, the person now smiling brightly and speaking with conviction, warmer light than before, genuine satisfaction',
      motionPromptEn: 'slow push-in on the confident smile',
      dialogueKo: '이제는 주변에 다 추천해요.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '별점·후기 그래픽과 제품, 로고 엔드 프레임.',
      keyframePromptEn: 'The product with floating five-star ratings and review card graphics, clean bright background, trustworthy commercial end-frame with logo space',
      motionPromptEn: 'stars animating in as camera settles on the product',
      dialogueKo: '수많은 후기가 증명합니다. 직접 확인해보세요.',
      subjectRefs: [],
    },
  ],

  // 📖 브랜드 서사형
  ad_brandstory: [
    {
      descKo: '오래된 사진과 기록 — 시작의 순간을 비추는 인트로.',
      keyframePromptEn: 'Vintage photographs and old documents spread on a wooden desk, bright warm morning daylight from a window, dust motes floating in the sunbeam, nostalgic storytelling mood, details clearly visible',
      motionPromptEn: 'slow pan across the old photographs',
      dialogueKo: '모든 시작에는 이야기가 있습니다.',
      subjectRefs: [],
    },
    {
      descKo: '작은 작업실에서 몰두하던 초창기의 모습.',
      keyframePromptEn: 'A dedicated founder working intently in a small humble workshop, warm daylight filling the room, face clearly lit and visible, early-days atmosphere',
      motionPromptEn: 'slow dolly through the workshop doorway',
      dialogueKo: '작은 믿음 하나로 시작했습니다.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '실패와 도전이 교차하는 성장의 몽타주.',
      keyframePromptEn: 'Montage of trials and growth, sketches pinned on walls, prototypes evolving, day-to-night time passage feel',
      motionPromptEn: 'rhythmic cross-dissolve montage motion',
      dialogueKo: '수없이 넘어지고, 다시 일어났습니다.',
      subjectRefs: [],
    },
    {
      descKo: '오늘의 모습 — 함께 일하는 사람들과 활기찬 현장.',
      keyframePromptEn: 'Modern vibrant workplace with a team collaborating, bright daylight through large windows, energetic yet warm company atmosphere',
      motionPromptEn: 'smooth gliding shot through the lively workspace',
      dialogueKo: '이제는 함께 걷는 길이 됐습니다.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '고객과 만나는 순간 — 진심이 전해지는 장면.',
      keyframePromptEn: 'Heartfelt moment of the brand meeting its customers, genuine smiles exchanged, warm golden light, human connection',
      motionPromptEn: 'slow orbit around the warm exchange',
      dialogueKo: '우리의 약속은 변하지 않습니다.',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '브랜드 로고가 떠오르는 신뢰의 엔드 프레임.',
      keyframePromptEn: 'Elegant brand logo reveal space over a horizon at sunrise, hopeful expansive landscape, inspiring corporate end-frame',
      motionPromptEn: 'slow rise over the horizon as light expands',
      dialogueKo: '내일도, 당신 곁에서.',
      subjectRefs: [],
    },
  ],

  // ⏰ 카운트다운형
  ad_countdown: [
    {
      // 티저도 밝게 — 기대감은 어둠이 아니라 "덮인 실루엣 + 환한 무대"로 만든다
      descKo: '티저 — 밝은 무대 위 덮인 제품, "곧 공개" 무드.',
      keyframePromptEn: 'The product hidden under a sleek satin cloth on a pedestal, bright festive stage lighting, clean light-toned backdrop, confetti anticipation mood',
      motionPromptEn: 'slow orbit around the covered product, light sparkling',
      dialogueKo: '드디어, 공개합니다.',
      subjectRefs: [],
    },
    {
      descKo: '베일이 벗겨지며 제품이 드러나는 순간.',
      keyframePromptEn: 'The cloth sweeping off in slow motion revealing the product, burst of light, particles scattering, dramatic reveal',
      motionPromptEn: 'slow-motion cloth reveal with light burst',
      dialogueKo: '기다림이 끝났습니다.',
      subjectRefs: [],
    },
    {
      descKo: '제품 핵심 매력 포인트 3연속 하이라이트.',
      keyframePromptEn: 'Rapid highlight shots of the product best features, punchy commercial lighting, bold dynamic angles',
      motionPromptEn: 'snappy whip-pans between feature highlights',
      dialogueKo: '이번엔 혜택까지 특별해요.',
      subjectRefs: [],
    },
    {
      descKo: '혜택 공개 — 할인·사은 그래픽이 팡팡 터진다.',
      keyframePromptEn: 'Festive promotion scene with discount badges and gift boxes bursting around the product, confetti, vibrant celebratory colors',
      motionPromptEn: 'energetic zoom bursts as badges pop in',
      dialogueKo: '오직 지금만, 이 가격에.',
      subjectRefs: [],
    },
    {
      descKo: '설레는 표정으로 제품을 담는 모델 — 서두르는 무드.',
      keyframePromptEn: 'An excited person happily grabbing the product, joyful urgency, bright retail-like setting, energetic expression',
      motionPromptEn: 'quick tracking shot following the excited grab',
      dialogueKo: '망설이면 늦어요!',
      subjectRefs: ['person_1'],
    },
    {
      descKo: '마감 임박 카운트다운과 로고 — 강력한 CTA 엔드 프레임.',
      keyframePromptEn: 'Bold end-frame with countdown timer space, the product center stage, urgent vivid colors, strong call-to-action layout with logo space',
      motionPromptEn: 'punch-in to the product as timer space pulses',
      dialogueKo: '지금 바로 클릭하세요!',
      subjectRefs: [],
    },
  ],
}
