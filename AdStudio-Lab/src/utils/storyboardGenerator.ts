import type { Project, Scene, StyleId, BackgroundConcept, NaturalPhenomenon, Relation, Person, BodyConcept, OutfitConcept } from '../types'
import { KeyVault } from '../stores/keysStore'
import { GeminiAdapter, type GeneratedStoryboardScene } from '../services/aiAdapters'
import { AD_CONCEPT_TEMPLATES, AD_TONES, AD_STRUCTURES, AD_EMPHASIS_LABELS, AD_CLARITY_BASE, AD_VISUAL_STYLES, buildAiActorKo, buildAiActorEn } from './adConcepts'
import { useAdStore } from '../stores/adStore'
import { translateSceneTextDetailed, detectTextLocale } from '../services/localizationService'
import { resampleHomageScenes } from './homageResampler'
import type { HomageStructure, HomageScene } from '../types/homage'

const RELATION_KO: Record<Relation, string> = {
  solo: '혼자',
  couple: '커플',
  married: '부부',
  family: '가족',
  siblings: '형제자매',
  friends: '친구',
}

/** ms 안에 promise가 끝나지 않으면 타임아웃시킨다 — Gemini 호출이 걸려도 스토리보드 생성이 무한정 멈추지 않게 한다 */
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`요청이 ${ms}ms 안에 끝나지 않았어요`)), ms)
    promise.then(v => { clearTimeout(timer); resolve(v) }, e => { clearTimeout(timer); reject(e) })
  })
}

// 스타일별 영문 프롬프트 데코레이터
export function getStylePromptModifier(styleId: StyleId): string {
  switch (styleId) {
    case 'bw':
      return 'grainy black and white film style, noir cinema aesthetic, deep shadows, high contrast, dramatic lighting, shot on 35mm'
    case 'cyberpunk':
      return 'neon cyberpunk style, neon violet and cyan lights, rain slicked streets, futuristic city background, cinematic portrait, high-tech contrast'
    case 'retro_vhs':
      return '1990s retro VHS tape quality, scanlines, analog warmth, vintage color grading, soft focus, nostalgic aesthetic, magnetic tape distortion'
    case 'anime_jp':
      return 'japanese anime style, Makoto Shinkai style, masterfully hand-drawn, gorgeous sunset sky, soft beautiful anime lighting, detailed background'
    case 'toon_3d':
      return 'modern 3D animation style, Pixar style, cute character design, soft clay render, vibrant color palette, beautiful warm studio lighting'
    case 'watercolor':
      return 'soft watercolor painting, bleeding colors, textured watercolor paper, artistic hand-painted illustration, gentle pastel wash, clean edges'
    case 'film_grain':
      return 'vintage analog film style, Kodak Portra 400 grain, warm organic colors, cinematic lens flare, nostalgic mood, realistic details, shot on Leica'
    case 'hifashion':
      return 'high fashion editorial photo, luxury commercial photography, studio lighting, sharp focus, high-end magazine cover aesthetic, minimalist background'
    case 'documentary':
      return 'national geographic documentary photo, raw realistic photo, photojournalism, natural ambient lighting, candid shot, highly detailed skin texture'
    case 'cinematic':
    default:
      return 'epic cinematic film frame, 8k resolution, teal and orange color grading, dramatic side lighting, photorealistic, cinematic volumetric dust, shot on Arri Alexa'
  }
}

// 인물별 바디 컨셉 영문 프롬프트 데코레이터 — 지정 시 사진 속 실제 체형 대신 이 문구로 그려진다
export function getBodyConceptModifier(body?: BodyConcept): string {
  switch (body) {
    case 'slim':
      return 'slim build, lean physique, slender narrow-waisted frame'
    case 'athletic':
      return 'athletic build, toned physique, well-defined muscle tone'
    case 'medium':
      return 'medium build, balanced proportions, even physique'
    case 'curvy':
      return 'full-figured build, soft rounded contours, fuller proportions'
    case 'sturdy':
      return 'sturdy build, solid frame, robust muscular physique'
    case 'petite':
      return 'compact build, small frame, shorter stature'
    case 'tall':
      return 'tall build, long-limbed frame, model-like proportions'
    case 'none':
    default:
      return ''
  }
}

// 인물별 의상 컨셉 영문 프롬프트 데코레이터 — 지정 시 사진 속 실제 옷차림 대신 이 문구로 그려진다
export function getOutfitConceptModifier(outfit?: OutfitConcept): string {
  switch (outfit) {
    case 'noir':
      return 'dark noir-style tailored suit, black trench coat, fedora, dramatic low-key lighting'
    case 'hanbok':
      return 'traditional Korean hanbok, jeogori and chima/baji, vivid silk'
    case 'enlightenment_vintage':
      return 'early 20th-century Korean transitional fashion, hanbok-Western hybrid attire'
    case 'fantasy_dress':
      return 'ethereal fantasy gown, flowing chiffon layers'
    case 'youth_casual':
      return 'youthful casual streetwear, denim and sneakers'
    case 'office':
      return 'modern business suit, tailored office attire'
    case 'street_performance':
      return 'urban street dance outfit, hip-hop stage fashion'
    case 'high_fashion':
      return 'high-end luxury fashion, designer evening wear'
    case 'victorian':
      return '19th-century European tailoring, Victorian tailcoat for men or corseted gown for women, period costume'
    case 'artdeco_jazz':
      return '1920s Art Deco fashion, pinstripe suit for men or fringed flapper dress for women, jazz-age glamour'
    case 'none':
    default:
      return ''
  }
}

// 배경 컨셉별 영문 프롬프트 데코레이터 — 씬이 펼쳐지는 공간/장소를 지정한다
export function getBackgroundPromptModifier(backgroundId?: BackgroundConcept): string {
  switch (backgroundId) {
    case 'hightech_city':
      return 'set in a sleek high-tech future city, gleaming skyscrapers, holographic displays, advanced clean architecture, futuristic ambient lighting'
    case 'dystopian_cyberpunk':
      return 'set in a dystopian cyberpunk metropolis, decaying megastructures, neon signage through smog, rain-slicked streets, oppressive futuristic atmosphere'
    case 'majestic_mountains':
      return 'set against majestic towering mountains, dramatic natural grandeur, crisp alpine air, sweeping vistas'
    case 'vast_plains':
      return 'set on a vast open plain stretching to the horizon, endless grassland, expansive open sky'
    case 'ocean_resort':
      return 'set by a vast tranquil ocean at a peaceful resort, turquoise water, white sand, serene tropical paradise'
    case 'wellness_sanctuary':
      return 'set in a calming medical and wellness sanctuary, clean minimalist interior, soft natural light, serene therapeutic atmosphere'
    case 'corporate_interview':
      return 'set against a professional corporate interview backdrop, clean modern office, soft studio lighting, polished business atmosphere'
    case 'luxury_office':
      return 'set in a luxury residential-commercial tower and premium office space, sleek modern architecture, floor-to-ceiling glass, upscale minimalist design'
    case 'none':
    default:
      return ''
  }
}

// 자연현상 컨셉별 영문 프롬프트 데코레이터 — 씬에 곁들일 날씨·천체 연출을 더한다
export function getNaturalPhenomenonModifier(phenomenonId?: NaturalPhenomenon): string {
  switch (phenomenonId) {
    case 'aurora':
      return 'vivid aurora borealis dancing across the night sky, ethereal green and violet light waves'
    case 'milky_way':
      return 'the Milky Way galaxy stretching across a star-filled night sky, breathtaking cosmic detail'
    case 'solar_eclipse':
      return 'a dramatic solar eclipse darkening the sky, glowing corona ring around the sun'
    case 'meteor_shower':
      return 'a spectacular meteor shower streaking across the night sky, trails of light'
    case 'dense_mist':
      return 'thick atmospheric mist and fog rolling through the scene, soft diffused visibility'
    case 'downpour':
      return 'heavy torrential rain pouring down, dramatic wet atmosphere, water splashing'
    case 'serene_snowfall':
      return 'gentle serene snow falling quietly, soft white blanket, peaceful winter hush'
    case 'light_shafts':
      return 'dramatic volumetric sunbeams breaking through clouds or trees, glowing light shafts'
    case 'bioluminescence':
      return 'magical bioluminescent glow illuminating the scene, otherworldly natural light'
    case 'golden_hour':
      return 'warm golden hour sunset light bathing the scene, long soft shadows, glowing amber tones'
    case 'lightning':
      return 'a sudden lightning bolt striking across a clear dark sky, dramatic flash of light'
    case 'volcanic_eruption':
      return 'a volcanic eruption in the distance, glowing lava and drifting ash, dramatic fiery atmosphere'
    case 'severe_storm':
      return 'a massive storm with churning dark clouds and powerful wind, dramatic turbulent sky'
    case 'blossom_blizzard':
      return 'cherry blossom petals swirling through the air like a blizzard, soft pink drifting petals'
    case 'fiery_autumn':
      return 'vivid fiery autumn foliage in brilliant red and orange, crisp fall atmosphere'
    case 'desert_sand_wind':
      return 'wind sweeping rippling patterns across desert sand dunes, golden sand particles drifting'
    case 'none':
    default:
      return ''
  }
}

interface SceneTemplate {
  descKo: string
  keyframePromptEn: string
  motionPromptEn: string
  dialogueKo: string
  subjectRefs: string[]
}

// 정적 컨셉 씬 템플릿 뱅크 — 각 컨셉은 기승전결이 있는 6컷 구성이다.
// (씬 개수는 durationSec에 맞춰 앞에서부터 잘라 쓰고, 풀이 짧은 컨셉은 뒤로 갈수록
// 개별 씬 길이를 늘려 총 길이를 맞춘다 — buildSceneDurations 참고)
const CONCEPT_TEMPLATES: Record<string, SceneTemplate[]> = {
  // 느와르 스릴러
  c1: [
    {
      descKo: '어두운 사무실 창가에서 도시 야경을 내려다보며 상념에 잠긴 주인공.',
      keyframePromptEn: 'A lone protagonist standing by a rain-streaked office window at night, city lights blurred below, moody blue backlight, contemplative silhouette',
      motionPromptEn: 'slow push-in toward the window, city lights flickering',
      dialogueKo: '이제 물러설 곳은 없어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '어두운 골목길 가로등 아래, 주인공이 비장한 눈빛으로 서 있다.',
      keyframePromptEn: 'A lone protagonist standing under a flickering streetlamp in a dark rainy alleyway, holding a dark umbrella, dramatic shadows',
      motionPromptEn: 'slow camera zoom in, rain drops falling in slow motion',
      dialogueKo: '이제 끝을 낼 때가 왔어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '마주 선 두 사람 사이로 차가운 바람이 불며 서로를 노려본다.',
      keyframePromptEn: 'Two people facing each other in a tense standoff, intense eye contact, cold misty air, distant city headlights blurred in background',
      motionPromptEn: 'dolly shot circling the characters, wind blowing coat tails',
      dialogueKo: '우린 다른 길을 가야 해.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '좁은 골목을 전력질주로 빠져나가는 주인공의 다급한 뒷모습.',
      keyframePromptEn: 'Protagonist sprinting through a narrow neon-lit alley at night, motion blur, rain splashing underfoot, dramatic side lighting',
      motionPromptEn: 'fast tracking shot from behind, camera shake, rain streaks',
      dialogueKo: '잡히면 끝이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '옥상 위, 도시를 등지고 결단을 내리는 주인공의 클로즈업.',
      keyframePromptEn: 'Close-up of protagonist standing on a rooftop at night, city skyline glowing behind, wind blowing coat, intense resolute expression',
      motionPromptEn: 'slow orbit around the character, wind effect',
      dialogueKo: '더 이상 도망치지 않아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '빗길 위로 멀어지는 실루엣과 바닥에 흩뿌려진 빛무리가 교차한다.',
      keyframePromptEn: 'A lonely silhouette walking away into the deep dark misty street, wet asphalt reflecting red and blue lights, cinematic backlight',
      motionPromptEn: 'slow tilt up camera following the silhouette',
      dialogueKo: '돌아보지 마.',
      subjectRefs: ['person_1']
    }
  ],
  // 로맨틱 멜로
  c2: [
    {
      descKo: '우연히 마주친 두 사람이 서로에게 시선이 머무는 첫 순간.',
      keyframePromptEn: 'Two people locking eyes for the first time across a sunlit café, soft golden light, subtle smiles, cinematic depth of field',
      motionPromptEn: 'slow rack focus from background to their eyes',
      dialogueKo: '우리 어디서 본 적 있나요?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노을이 붉게 물드는 바닷가, 두 사람이 손을 잡고 수평선을 바라본다.',
      keyframePromptEn: 'Romantic couple holding hands standing on the beach at sunset, warm golden sunlight rimming their silhouettes, soft waves crashing',
      motionPromptEn: 'slow tracking shot following them from behind',
      dialogueKo: '이 순간이 멈췄으면 좋겠어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '주인공이 상대방의 얼굴을 부드럽게 바라보며 따뜻하게 미소 짓는다.',
      keyframePromptEn: 'Close up of a character looking affectionately at the partner, warm sunlight filtering through leaves, soft background focus',
      motionPromptEn: 'extremely slow push in to the eyes, camera focus pulling',
      dialogueKo: '너와 함께라서 행복해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '살짝 토라진 듯 돌아서는 순간, 애틋한 감정이 스친다.',
      keyframePromptEn: 'Close-up of a character turning away with a soft hurt expression, then glancing back longingly, warm indoor lighting, bokeh background',
      motionPromptEn: 'slow whip pan following the turn, soft focus pull',
      dialogueKo: '나한테 화난 거 아니지?',
      subjectRefs: ['person_1']
    },
    {
      descKo: '서로를 따뜻하게 껴안은 채 흔들리는 나뭇잎 사이로 햇살이 쏟아진다.',
      keyframePromptEn: 'Couple embracing warmly in a sun-drenched park, golden hour light leaks, romantic and nostalgic atmosphere',
      motionPromptEn: 'gentle camera panning, lens flare dancing',
      dialogueKo: '언제나 곁에 있을게.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노을 진 하늘 아래 이마를 맞대고 웃는 두 사람의 실루엣.',
      keyframePromptEn: 'Silhouette of a couple with foreheads touching, laughing softly under a vivid sunset sky, warm rim light, romantic atmosphere',
      motionPromptEn: 'slow crane shot rising and pulling back',
      dialogueKo: '오래오래 함께하자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 청춘 성장기
  c3: [
    {
      descKo: '푸른 들판 위에서 하늘을 올려다보며 큰 숨을 들이쉬는 주인공.',
      keyframePromptEn: 'Young protagonist standing in a wide green grass field, looking up at the clear blue sky with fluffy clouds, wind blowing hair',
      motionPromptEn: 'camera crane shot rising up, wind blowing the grass',
      dialogueKo: '더 넓은 세상으로 갈 거야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '자전거를 타고 언덕 위를 시원하게 달리는 주인공의 뒷모습.',
      keyframePromptEn: 'Protagonist riding a bicycle up a scenic coastal hill road, refreshing morning breeze, sparkling ocean in the distance',
      motionPromptEn: 'tracking shot following the bicycle, energetic camera movement',
      dialogueKo: '포기하지 않아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '도서관 창가에 앉아 책을 읽다 문득 먼 곳을 바라보는 주인공.',
      keyframePromptEn: 'Protagonist sitting by a library window, sunlight streaming across an open book, pausing to gaze thoughtfully into the distance',
      motionPromptEn: 'slow push-in, dust particles floating in the light',
      dialogueKo: '나는 뭘 하고 싶은 걸까.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '빗속에서 흠뻑 젖은 채 하늘을 향해 팔을 뻗으며 웃는 주인공.',
      keyframePromptEn: 'Protagonist standing in the rain with arms outstretched, laughing joyfully, wet hair, dramatic backlighting, water splashing',
      motionPromptEn: 'slow motion rain, camera slowly circling',
      dialogueKo: '이대로도 괜찮아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '언덕 끝에서 석양을 바라보며 결연한 다짐을 하는 주인공의 얼굴.',
      keyframePromptEn: 'Close up profile of a young character facing the golden sunset, wind in hair, determined and hope-filled gaze',
      motionPromptEn: 'slow dolly-in, sunset glow intensification',
      dialogueKo: '나만의 길을 찾겠어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '새벽 기차역 플랫폼에서 새로운 여정을 시작하는 주인공의 뒷모습.',
      keyframePromptEn: 'Protagonist walking away down a train platform at dawn, soft morning mist, suitcase in hand, hopeful atmosphere',
      motionPromptEn: 'slow tracking shot following from behind, mist drifting',
      dialogueKo: '이제 진짜 시작이야.',
      subjectRefs: ['person_1']
    }
  ],
  // 레트로 애니 감성 (애니메이션)
  c12: [
    {
      descKo: '초록빛 가득한 비밀 정원에 앉아 신비로운 생명체를 지켜보는 주인공.',
      keyframePromptEn: 'Nostalgic anime character sitting in a lush green mossy garden, ancient trees, sparkling fireflies, soft magical light filtering',
      motionPromptEn: 'slow camera tilt down, fireflies floating gently',
      dialogueKo: '여긴 꼭 비밀의 방 같아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '바람이 불어오는 풀밭 언덕 위에서 함께 구름을 바라보는 두 사람.',
      keyframePromptEn: 'Two friends sitting on a high grassy hill under massive beautiful white summer clouds, wind sweeping through the meadows',
      motionPromptEn: 'slow panning shot, clouds moving slowly in background',
      dialogueKo: '저 구름 너머엔 뭐가 있을까?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '오래된 마을 골목을 뛰어다니며 신기한 것들을 구경하는 주인공.',
      keyframePromptEn: 'Nostalgic anime character running through an old cobblestone village alley, colorful lanterns, whimsical hand-painted buildings, soft afternoon light',
      motionPromptEn: 'dynamic tracking shot following the character, lanterns swaying',
      dialogueKo: '여기 정말 신기한 곳이야!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '커다란 나무 아래 그늘에서 낮잠을 자다 살며시 눈을 뜨는 주인공.',
      keyframePromptEn: 'Character napping under a giant ancient tree, dappled sunlight through leaves, gently waking up, peaceful anime atmosphere',
      motionPromptEn: 'slow zoom in, leaves rustling in the wind',
      dialogueKo: '얼마나 잔 걸까...',
      subjectRefs: ['person_1']
    },
    {
      descKo: '따뜻한 등불이 켜진 아늑한 방 안에서 평온하게 책을 읽고 있는 주인공.',
      keyframePromptEn: 'Character reading a book in a cozy attic room filled with wooden shelves, a glowing desk lamp, soft warm atmosphere',
      motionPromptEn: 'slow zoom out showing the details of the room, steam rising from tea cup',
      dialogueKo: '따뜻한 바람이 불어와.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노을 지는 언덕 위에서 두 사람이 손을 흔들며 인사하는 정겨운 순간.',
      keyframePromptEn: 'Two anime characters waving goodbye on a sunset hill, warm nostalgic colors, wind swept grass, heartwarming retro anime atmosphere',
      motionPromptEn: 'slow pull-back crane shot, wind blowing through the grass',
      dialogueKo: '또 만나자, 꼭!',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 가족 드라마
  c4: [
    {
      descKo: '아침 햇살이 드는 부엌에서 함께 아침을 준비하며 웃는 가족.',
      keyframePromptEn: 'A family preparing breakfast together in a sunlit kitchen, warm morning light, laughter and gentle chaos, cozy domestic atmosphere',
      motionPromptEn: 'gentle handheld camera movement, steam rising from the stove',
      dialogueKo: '오늘도 맛있게 먹자.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '거실 소파에 나란히 앉아 오래된 사진첩을 넘기며 추억에 잠긴 가족.',
      keyframePromptEn: 'Family sitting together on a living room sofa, flipping through an old photo album, warm lamp light, nostalgic tender expressions',
      motionPromptEn: 'slow push-in on the photo album, soft focus pull to their faces',
      dialogueKo: '이때 진짜 어렸었네.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '마당에서 아이처럼 뛰어노는 모습을 지켜보며 흐뭇하게 웃는 주인공.',
      keyframePromptEn: 'Protagonist watching over the family in a sunny backyard garden, warm affectionate smile, soft bokeh background, golden afternoon light',
      motionPromptEn: 'slow dolly-in, warm lens flare',
      dialogueKo: '이 순간이 제일 소중해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '식탁에 둘러앉아 촛불을 밝히고 서로에게 감사를 전하는 저녁.',
      keyframePromptEn: 'Family gathered around a dinner table with candlelight, warm golden glow, heartfelt smiles, cozy home interior',
      motionPromptEn: 'slow circular pan around the table, candle flames flickering',
      dialogueKo: '우리 가족이라서 다행이야.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '창가에 기대어 저무는 노을을 함께 바라보는 다정한 뒷모습.',
      keyframePromptEn: 'Family standing by a large window watching the sunset together, silhouettes against warm orange sky, tender quiet moment',
      motionPromptEn: 'slow zoom out revealing the whole room',
      dialogueKo: '내일도 함께하자.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '현관에서 포옹하며 서로를 꼭 안아주는 따뜻한 작별 인사.',
      keyframePromptEn: 'Family embracing warmly at the front door, soft evening light, heartfelt hug, cozy warm color palette',
      motionPromptEn: 'slow push-in on the embrace, gentle warm light flare',
      dialogueKo: '사랑해, 우리 가족.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 로맨스 판타지
  c5: [
    {
      descKo: '별빛이 쏟아지는 신비로운 숲속에서 처음 마주친 두 사람.',
      keyframePromptEn: 'Two people meeting for the first time in a magical starlit forest, glowing fireflies, ethereal mist, fated encounter atmosphere',
      motionPromptEn: 'slow orbit shot, fireflies drifting through the frame',
      dialogueKo: '마치 예전부터 알던 사람 같아요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '빛나는 꽃잎이 흩날리는 정원에서 손끝이 스치는 순간.',
      keyframePromptEn: 'Glowing petals swirling around a couple in an enchanted garden, soft magical light, delicate hands almost touching, dreamlike atmosphere',
      motionPromptEn: 'slow motion petals falling, gentle camera drift',
      dialogueKo: '이 순간이 꿈은 아니겠죠?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '달빛 호수 위 물안개 속에서 서로를 바라보는 주인공의 옆모습.',
      keyframePromptEn: 'Close-up profile of a character gazing at their partner beside a moonlit misty lake, soft blue glow, romantic fantasy mood',
      motionPromptEn: 'extremely slow push-in, mist swirling gently',
      dialogueKo: '당신 곁이라면 어디든 좋아요.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '빛의 입자가 흩어지는 공중에서 함께 떠오르듯 춤을 추는 두 사람.',
      keyframePromptEn: 'A couple dancing amidst floating light particles in a surreal glowing forest clearing, magical sparkles, ethereal fantasy romance',
      motionPromptEn: 'slow crane shot circling upward, particles swirling',
      dialogueKo: '시간이 멈췄으면 좋겠어요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '고대 나무 아래 빛나는 문 앞에서 서로의 손을 꼭 붙잡는 순간.',
      keyframePromptEn: 'Couple holding hands tightly before a glowing ancient portal beneath a massive tree, magical golden light, fated destiny atmosphere',
      motionPromptEn: 'slow dolly-in toward their joined hands',
      dialogueKo: '무슨 일이 있어도 놓지 않을게요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '새벽빛이 번지는 하늘 아래 서로를 끌어안은 실루엣.',
      keyframePromptEn: 'Silhouette of a couple embracing under a magical dawn sky, soft pastel light gradient, ethereal romantic conclusion',
      motionPromptEn: 'slow pull-back crane shot, light rays spreading',
      dialogueKo: '우리, 운명이었나 봐요.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 직장인 로맨스
  c6: [
    {
      descKo: '붐비는 엘리베이터 안, 우연히 시선이 마주치는 두 사람.',
      keyframePromptEn: 'Two office workers accidentally locking eyes inside a crowded elevator, soft fluorescent light, subtle nervous smiles, modern office aesthetic',
      motionPromptEn: 'slow zoom on their eye contact, elevator doors closing',
      dialogueKo: '몇 층 가세요?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '야근 후 텅 빈 사무실, 창밖 야경을 함께 바라보는 순간.',
      keyframePromptEn: 'Two colleagues standing by a floor-to-ceiling window in an empty office at night, city lights sparkling below, quiet intimate atmosphere',
      motionPromptEn: 'slow tracking shot, city lights bokeh in foreground',
      dialogueKo: '오늘 고생 많았어요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '옥상 자판기 커피를 마시며 편안하게 웃는 주인공의 모습.',
      keyframePromptEn: 'Protagonist leaning on a rooftop railing holding a coffee cup, relaxed smile, warm afternoon city light, casual office attire',
      motionPromptEn: 'gentle handheld push-in, wind blowing hair',
      dialogueKo: '여기 오면 마음이 편해져요.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '회의실 유리벽 너머로 눈이 마주치며 슬며시 미소짓는 두 사람.',
      keyframePromptEn: 'Two coworkers exchanging a subtle smile through a glass meeting room wall, modern office interior, soft natural daylight',
      motionPromptEn: 'slow rack focus between them through the glass',
      dialogueKo: '나중에 커피 한잔 할래요?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '퇴근길 노을 진 거리를 나란히 걸으며 대화를 나누는 두 사람.',
      keyframePromptEn: 'Two people walking side by side down a sunset city street after work, warm golden light, easy comfortable conversation, urban backdrop',
      motionPromptEn: 'slow tracking shot from the side, warm lens flare',
      dialogueKo: '집 방향 같으니까 같이 가요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '사무실 파티션 사이로 몰래 건넨 작은 쪽지에 미소 짓는 순간.',
      keyframePromptEn: "Close-up of a character smiling softly at a small handwritten note passed across an office desk, warm afternoon light, tender office romance moment",
      motionPromptEn: 'slow push-in on the smile, soft depth of field',
      dialogueKo: '오늘 저녁에 시간 있어요?',
      subjectRefs: ['person_1']
    }
  ],
  // 시대극 멜로
  c7: [
    {
      descKo: '고즈넉한 한옥 마당, 처음 마주친 두 사람의 조심스러운 눈빛.',
      keyframePromptEn: 'Two people in traditional hanbok meeting for the first time in a serene hanok courtyard, soft diffused light, reserved graceful expressions, period drama aesthetic',
      motionPromptEn: 'slow dolly-in, cherry blossom petals drifting',
      dialogueKo: '뉘시온지 여쭤봐도 되겠습니까.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '달빛 가득한 궁궐 정원에서 은밀히 재회하는 두 사람.',
      keyframePromptEn: 'A couple in elegant hanbok reuniting secretly in a moonlit palace garden, soft lantern light, traditional Korean architecture, romantic period drama mood',
      motionPromptEn: 'slow crane shot descending, lanterns swaying gently',
      dialogueKo: '이리 다시 뵐 줄은 몰랐습니다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '서예를 하다 문득 멈추고 창밖을 바라보는 주인공의 그리움 어린 옆모습.',
      keyframePromptEn: 'Close-up profile of a character in hanbok pausing while writing calligraphy, gazing wistfully out a traditional wooden window, soft natural light',
      motionPromptEn: 'slow push-in, ink brush lowering slowly',
      dialogueKo: '언제쯤 다시 만날 수 있을까.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '비 내리는 처마 밑에서 우산도 없이 서로를 기다리는 애틋한 순간.',
      keyframePromptEn: 'Couple in hanbok standing under a traditional eave in the rain, soft grey light, longing expressions, period romance atmosphere',
      motionPromptEn: 'slow static shot with rain falling, subtle camera drift',
      dialogueKo: '비가 그칠 때까지 함께 있어 주시겠습니까.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '연등이 가득한 밤거리를 손잡고 걷는 두 사람의 뒷모습.',
      keyframePromptEn: 'A couple in hanbok walking hand in hand through a night street filled with glowing traditional lanterns, warm festive atmosphere, period drama romance',
      motionPromptEn: 'slow tracking shot from behind, lanterns glowing softly',
      dialogueKo: '이 길이 끝나지 않았으면 좋겠습니다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노을 진 언덕 위 정자에서 두 사람이 서로를 마주보며 미소 짓는다.',
      keyframePromptEn: 'Couple in hanbok sitting together in a traditional pavilion on a sunset hill, warm golden light, tender smiles, timeless period romance',
      motionPromptEn: 'slow pull-back revealing the landscape',
      dialogueKo: '평생 곁에 있어 주시겠습니까.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 청춘 우정
  c8: [
    {
      descKo: '교실 창가에 나란히 앉아 장난스럽게 웃는 친구들.',
      keyframePromptEn: 'Friends sitting side by side by a classroom window, playful laughter, warm afternoon sunlight, youthful carefree atmosphere',
      motionPromptEn: 'gentle handheld camera, light flickering through window',
      dialogueKo: '우리 진짜 웃긴다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '학교 옥상에서 하늘을 향해 팔을 뻗으며 소리치는 친구들의 뒷모습.',
      keyframePromptEn: 'Friends standing on a school rooftop, arms raised toward the sky, wind blowing hair, energetic youthful freedom, wide open sky',
      motionPromptEn: 'slow crane shot rising, wind effect',
      dialogueKo: '우리 꼭 꿈 이루자!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '매점 앞 계단에 앉아 아이스크림을 나눠 먹으며 웃는 주인공.',
      keyframePromptEn: 'Protagonist sitting on school steps sharing ice cream with a friend, bright cheerful smile, casual school uniform, sunny afternoon',
      motionPromptEn: 'slow push-in, natural candid movement',
      dialogueKo: '이거 진짜 맛있다, 너도 먹어봐.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '시험 끝난 뒤 운동장을 가로질러 함께 달려가는 친구들.',
      keyframePromptEn: 'Friends running joyfully across a school field after exams, golden afternoon light, dynamic energetic movement, youthful liberation',
      motionPromptEn: 'fast tracking shot following the run, dust kicking up',
      dialogueKo: '드디어 끝났다!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '늦은 밤 편의점 앞 파라솔 아래 앉아 진지하게 이야기 나누는 친구들.',
      keyframePromptEn: 'Friends sitting under a convenience store parasol at night, soft neon glow, heartfelt quiet conversation, nostalgic youth atmosphere',
      motionPromptEn: 'slow static shot, gentle ambient light flicker',
      dialogueKo: '너 없었으면 진짜 힘들었을 거야.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '졸업식 날 교문 앞에서 서로를 부둥켜안고 우는 친구들.',
      keyframePromptEn: 'Friends embracing tearfully in front of the school gate on graduation day, warm spring light, cherry blossoms falling, bittersweet farewell',
      motionPromptEn: 'slow push-in on the embrace, petals drifting',
      dialogueKo: '우리 우정 변하지 말자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 감성 발라드 (뮤직비디오)
  c9: [
    {
      descKo: '비 내리는 창가에 기대어 먼 곳을 바라보는 주인공의 옆모습.',
      keyframePromptEn: 'Close-up profile of a character leaning against a rain-streaked window, gazing into the distance, melancholic blue-grey light, emotional ballad mood',
      motionPromptEn: 'extremely slow push-in, raindrops trailing down the glass',
      dialogueKo: '아직도 네 생각이 나.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '텅 빈 밤거리를 홀로 천천히 걸어가는 주인공의 뒷모습.',
      keyframePromptEn: 'Protagonist walking slowly alone down an empty night street, streetlights glowing, soft mist, quiet emotional atmosphere',
      motionPromptEn: 'slow tracking shot from behind, streetlights passing',
      dialogueKo: '혼자인 게 익숙해졌어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '낡은 사진 한 장을 손에 쥐고 눈을 감는 주인공의 클로즈업.',
      keyframePromptEn: 'Close-up of a character holding an old photograph, eyes closing softly, warm nostalgic lamp light, bittersweet emotional moment',
      motionPromptEn: 'extremely slow zoom in, dust particles floating in the light',
      dialogueKo: '그때로 돌아갈 수 있다면.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '바닷가에 홀로 앉아 파도를 바라보며 눈물을 참는 주인공.',
      keyframePromptEn: 'Protagonist sitting alone on a beach at dusk, gazing at the waves, holding back tears, moody grey-blue color grading, emotional ballad atmosphere',
      motionPromptEn: 'slow dolly-in, waves crashing softly',
      dialogueKo: '이제는 놓아줘야 할까.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '텅 빈 공연장 무대 위에서 홀로 노래하듯 서 있는 주인공.',
      keyframePromptEn: 'Protagonist standing alone on an empty stage under a single spotlight, dust particles in the light beam, emotional and vulnerable atmosphere',
      motionPromptEn: 'slow crane shot pulling back, spotlight flickering',
      dialogueKo: '이 노래가 너에게 닿기를.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '새벽빛이 번지는 창가에서 눈을 뜨며 옅은 미소를 짓는 주인공.',
      keyframePromptEn: 'Protagonist waking up by a window at dawn, soft warm light spreading, faint hopeful smile, gentle emotional resolution',
      motionPromptEn: 'slow push-in, light gradually brightening',
      dialogueKo: '그래도, 살아가야지.',
      subjectRefs: ['person_1']
    }
  ],
  // 힙합 비트 (뮤직비디오)
  c10: [
    {
      descKo: '그래피티 벽 앞에서 자신감 넘치는 표정으로 서 있는 주인공.',
      keyframePromptEn: 'Protagonist standing confidently in front of a vibrant graffiti wall, urban streetwear, bold dramatic lighting, hip hop music video aesthetic',
      motionPromptEn: 'slow dolly-in with subtle camera shake, urban energy',
      dialogueKo: '내 스타일대로 간다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '지하철 플랫폼에서 비트에 맞춰 걸어가는 주인공의 역동적인 모습.',
      keyframePromptEn: 'Protagonist walking through a gritty subway platform with swagger, dramatic neon signage, urban night atmosphere, dynamic hip hop energy',
      motionPromptEn: 'fast tracking shot following the walk, neon lights streaking',
      dialogueKo: '멈추지 않고 계속 간다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '옥상에서 도시 야경을 배경으로 친구들과 함께 포즈를 취하는 모습.',
      keyframePromptEn: 'A group of friends posing confidently on an urban rooftop at night, city skyline glowing behind, bold hip hop fashion, dramatic side lighting',
      motionPromptEn: 'slow low-angle dolly, city lights flaring',
      dialogueKo: '우리가 이 거리의 주인공이야.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '비 내리는 도심 거리에서 강렬한 눈빛으로 카메라를 응시하는 주인공.',
      keyframePromptEn: 'Close-up of protagonist standing in the rain on a city street, intense confident gaze directly at camera, neon reflections, dramatic hip hop mood',
      motionPromptEn: 'slow push-in, rain streaking through neon light',
      dialogueKo: '흔들리지 않아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '낙서 가득한 골목을 배경으로 리듬을 타듯 움직이는 주인공의 실루엣.',
      keyframePromptEn: 'Silhouette of protagonist moving rhythmically against a graffiti-covered alley backdrop, dramatic backlighting, urban hip hop energy',
      motionPromptEn: 'dynamic handheld tracking, strobing light effect',
      dialogueKo: '이 비트가 내 심장이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '새벽 도심 위 옥상에서 해 뜨는 스카이라인을 등지고 서 있는 주인공.',
      keyframePromptEn: 'Protagonist standing on a rooftop at dawn, city skyline glowing behind with sunrise colors, confident triumphant pose, epic hip hop finale',
      motionPromptEn: 'slow crane shot pulling back and rising',
      dialogueKo: '여기까지 왔다.',
      subjectRefs: ['person_1']
    }
  ],
  // 팝 댄스 (뮤직비디오)
  c11: [
    {
      descKo: '화려한 조명이 켜진 댄스 스튜디오에서 준비 자세를 취하는 주인공.',
      keyframePromptEn: 'Protagonist in a dance studio with vibrant colorful stage lighting, dynamic ready pose, energetic pop music video aesthetic',
      motionPromptEn: 'slow dolly-in with light flares pulsing',
      dialogueKo: '지금부터 시작이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '네온 조명 아래 역동적으로 춤을 추는 주인공의 강렬한 순간.',
      keyframePromptEn: 'Protagonist dancing dynamically under neon stage lights, motion blur, vibrant magenta and cyan lighting, high energy pop performance',
      motionPromptEn: 'fast dynamic camera movement synced to the beat, light trails',
      dialogueKo: '몸이 먼저 반응해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '친구들과 함께 대형을 맞춰 춤추는 활기찬 그룹 신.',
      keyframePromptEn: 'A group of friends dancing in synchronized formation on a colorful lit stage, vibrant pop concert atmosphere, dynamic choreography',
      motionPromptEn: 'wide dynamic crane shot capturing the formation',
      dialogueKo: '다 같이 맞춰보자!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '스포트라이트 아래 홀로 서서 감정을 담아 춤추는 클로즈업.',
      keyframePromptEn: 'Close-up of protagonist dancing solo under a bright spotlight, emotional expressive movement, dramatic colorful stage haze',
      motionPromptEn: 'slow orbit shot with light rays cutting through haze',
      dialogueKo: '이 순간만큼은 내가 주인공이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '거울로 가득한 연습실에서 반복 연습하다 서로 마주보며 웃는 순간.',
      keyframePromptEn: "Friends practicing dance in a mirror-filled studio, catching each other's eyes and laughing mid-move, warm energetic atmosphere",
      motionPromptEn: 'dynamic handheld movement, mirror reflections multiplying',
      dialogueKo: '우리 진짜 많이 늘었다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '화려한 무대 위 마지막 포즈에서 환호하는 관객을 향해 미소 짓는 주인공.',
      keyframePromptEn: 'Protagonist striking a final triumphant pose on a dazzling concert stage, confetti falling, vibrant lighting, joyful pop finale',
      motionPromptEn: 'slow crane pull-back revealing the full stage, confetti falling',
      dialogueKo: '고마워요, 다음에 또 만나요!',
      subjectRefs: ['person_1']
    }
  ],
  // 수묵 동양화
  c13: [
    {
      descKo: '안개 낀 산수화 풍경 속 대나무숲을 홀로 걷는 주인공.',
      keyframePromptEn: 'Traditional ink wash painting style scene of a figure walking alone through a misty bamboo forest, monochrome brushstroke aesthetic, serene atmosphere',
      motionPromptEn: 'slow tracking shot through the mist, bamboo swaying',
      dialogueKo: '마음을 비우니 길이 보이는구나.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '먹빛 산과 강이 어우러진 풍경 앞에서 정자에 앉아 사색하는 주인공.',
      keyframePromptEn: 'Ink wash painting style scene of a figure sitting in a traditional pavilion overlooking mountains and a river, monochrome with subtle color wash, contemplative mood',
      motionPromptEn: 'slow zoom out revealing the vast landscape',
      dialogueKo: '자연 앞에서는 모두가 작아지는구나.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '달빛 어린 호수 위 조각배에 나란히 앉은 두 사람의 고요한 순간.',
      keyframePromptEn: 'Ink wash painting style scene of two figures sitting together in a small boat on a moonlit lake, delicate brushstroke ripples, tranquil monochrome mood',
      motionPromptEn: 'extremely slow drifting camera movement, ripples spreading',
      dialogueKo: '이 고요함이 참 좋습니다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '매화나무 아래 눈이 흩날리는 풍경 속에 서 있는 주인공의 옆모습.',
      keyframePromptEn: 'Ink wash painting style scene of a figure standing beneath a plum blossom tree in falling snow, elegant monochrome brushwork with soft pink accents',
      motionPromptEn: 'slow push-in, snow and petals drifting together',
      dialogueKo: '겨울에도 피어나는 것이 있구나.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '폭포 앞에서 붓을 들어 그림을 그리는 주인공의 진중한 모습.',
      keyframePromptEn: 'Ink wash painting style scene of a figure painting with a brush before a majestic waterfall, monochrome mist and spray, meditative artistic mood',
      motionPromptEn: 'slow dolly-in on the brush strokes, waterfall mist drifting',
      dialogueKo: '붓끝에 마음을 담는다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노을 진 산등성이를 배경으로 두 사람이 함께 걸어가는 뒷모습.',
      keyframePromptEn: 'Ink wash painting style scene of two figures walking together along a mountain ridge at sunset, monochrome with warm ochre wash, timeless harmony',
      motionPromptEn: 'slow tracking shot from behind, mountains layering into the distance',
      dialogueKo: '함께라면 어디든 갈 수 있지요.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 럭셔리 광고
  c14: [
    {
      descKo: '대리석 인테리어 속에서 우아하게 포즈를 취하는 주인공.',
      keyframePromptEn: 'Protagonist posing elegantly in a marble luxury interior, high-end fashion editorial lighting, minimalist sophisticated composition',
      motionPromptEn: 'slow dolly-in, soft studio light shifting',
      dialogueKo: '디테일이 전부를 말해줍니다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '황금빛 노을이 지는 루프탑에서 도시를 내려다보는 세련된 실루엣.',
      keyframePromptEn: 'Silhouette of protagonist standing on a golden-lit rooftop overlooking the city skyline, luxury fashion campaign aesthetic, dramatic warm light',
      motionPromptEn: 'slow crane shot rising, warm lens flare',
      dialogueKo: '정상에서 보는 풍경은 다르죠.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '고급 자동차 옆에 기대어 카메라를 응시하는 당당한 포즈.',
      keyframePromptEn: 'Protagonist leaning against a luxury car, confident direct gaze at camera, studio-quality lighting, high fashion commercial photography',
      motionPromptEn: 'slow orbit shot, subtle rim light sweep',
      dialogueKo: '클래식은 영원합니다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '샹들리에 아래 화려한 홀에서 우아하게 걸어 나오는 두 사람.',
      keyframePromptEn: 'Two people walking elegantly through a grand hall beneath a crystal chandelier, luxury editorial fashion, cinematic golden lighting',
      motionPromptEn: 'slow tracking shot alongside them, chandelier light sparkling',
      dialogueKo: '오늘 밤의 주인공은 우리예요.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '통유리창 너머 야경을 배경으로 와인잔을 든 세련된 실루엣.',
      keyframePromptEn: 'Protagonist silhouetted against floor-to-ceiling windows with city night lights, holding a wine glass, refined luxury lifestyle mood',
      motionPromptEn: 'slow push-in, city lights twinkling',
      dialogueKo: '이런 순간을 위해 살아요.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '프라이빗 요트 위에서 바람에 머리카락이 흩날리는 자유로운 모습.',
      keyframePromptEn: 'Protagonist standing on a private yacht deck, hair flowing in the wind, brilliant ocean sunlight, luxurious freedom and elegance',
      motionPromptEn: 'slow tracking shot, ocean spray glistening',
      dialogueKo: '자유로움이 곧 럭셔리죠.',
      subjectRefs: ['person_1']
    }
  ],
  // 인생 화보
  c15: [
    {
      descKo: '아침 햇살 속 창가에서 커피 한 잔과 함께 하루를 시작하는 담백한 순간.',
      keyframePromptEn: 'Protagonist enjoying a quiet cup of coffee by a sunlit window in the morning, natural documentary photography style, soft candid warmth',
      motionPromptEn: 'gentle handheld push-in, steam rising from the cup',
      dialogueKo: '오늘 하루도 잘 살아보자.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '도심 거리를 담백하게 걸어가는 주인공의 자연스러운 뒷모습.',
      keyframePromptEn: 'Protagonist walking naturally through a city street, candid documentary photography, soft natural daylight, authentic everyday moment',
      motionPromptEn: 'slow tracking shot from behind, city life passing by',
      dialogueKo: '이 길을 걷는 게 좋아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '공원 벤치에 앉아 소중한 사람과 편안하게 웃으며 대화하는 순간.',
      keyframePromptEn: 'Two people sitting on a park bench, laughing comfortably in conversation, candid documentary style, warm natural light',
      motionPromptEn: 'slow static shot with subtle handheld sway',
      dialogueKo: '너랑 있으면 시간 가는 줄 몰라.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '빗속에서 우산 없이 웃으며 뛰어가는 즉흥적이고 생생한 순간.',
      keyframePromptEn: 'Protagonist running joyfully in the rain without an umbrella, candid documentary photography, genuine laughter, vivid raw emotion',
      motionPromptEn: 'dynamic handheld tracking shot, rain splashing',
      dialogueKo: '가끔은 이렇게 사는 것도 좋아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노을 지는 강가에 앉아 조용히 생각에 잠긴 담담한 옆모습.',
      keyframePromptEn: 'Protagonist sitting quietly by a riverside at sunset, contemplative candid documentary mood, warm natural light, genuine reflection',
      motionPromptEn: 'slow zoom in, water reflecting the sunset',
      dialogueKo: '지나온 시간들이 다 소중했어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '소중한 사람과 어깨를 나란히 하고 걸어가는 인생의 한 장면.',
      keyframePromptEn: 'Two people walking side by side down a quiet street at golden hour, candid documentary life photography, warm intimate authentic mood',
      motionPromptEn: 'slow tracking shot from the side, golden light streaming',
      dialogueKo: '앞으로도 이렇게 함께 걷자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 고딕 공포극
  c16: [
    {
      descKo: '안개 자욱한 밤, 저택의 육중한 철문 앞에 홀로 선 주인공의 불안한 그림자.',
      keyframePromptEn: 'A lone protagonist standing before towering wrought-iron gates, fog-shrouded gothic mansion looming behind, flickering candlelight in distant tower windows, crumbling stone gargoyles overhead, bare twisted trees under pale moonlight, deep velvet-black shadows pooling across the courtyard, ornate Victorian stonework cracked with decay, cold blue moonlight mixed with warm amber candle glow',
      motionPromptEn: 'slow push-in through drifting fog toward the gates',
      dialogueKo: '여기서부터는... 돌아갈 수 없겠지.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불이 흔들리는 긴 복도를 지나며 벽에 걸린 초상화들의 시선을 느끼는 순간.',
      keyframePromptEn: 'Protagonist walking alone down a narrow candlelit corridor, rows of dust-covered oil portraits with unsettling painted eyes lining the walls, wavering candelabra casting elongated shadows, peeling blood-dark velvet wallpaper, cobweb-draped chandelier overhead, warped creaking floorboards, dim gold candlelight swallowed by surrounding darkness',
      motionPromptEn: 'slow tracking shot forward, candle flames trembling',
      dialogueKo: '저 그림들... 전부 나를 보고 있어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불 아래 함께 낡은 서재에서 오래된 일기장을 발견하고 불안하게 마주보는 순간.',
      keyframePromptEn: 'Two people huddled close together in a decaying candlelit library, an old leather-bound diary open on a dust-covered desk between them, towering bookshelves draped in cobwebs, guttering candle stubs, rain-streaked gothic arched windows, heavy crimson velvet curtains, tense flickering firelight across worried faces',
      motionPromptEn: 'slow handheld push-in, candlelight flickering across their faces',
      dialogueKo: '이 집에서... 대체 무슨 일이 있었던 거야?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '지하 묘실로 홀로 내려가던 중, 등 뒤에서 스스로 열리는 관 뚜껑을 목격하는 순간.',
      keyframePromptEn: 'Protagonist descending narrow worn stone stairs into a crypt alone, trembling candle held aloft, an ancient carved stone sarcophagus lid creaking open in the shadows behind, pale ghostly mist seeping through cracked stonework, dripping damp walls, guttering torchlight, oppressive darkness, ornate skull carvings lining the crypt walls',
      motionPromptEn: 'slow rotating reveal of the opening sarcophagus behind',
      dialogueKo: '안 돼... 이럴 순 없어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '무너지는 대저택의 계단을 필사적으로 뛰어 내려가며 뒤쫓는 어둠으로부터 도망치는 순간.',
      keyframePromptEn: 'Protagonist sprinting alone down a grand crumbling staircase, torn velvet coat flowing behind, shattering candelabra scattering sparks, swirling black mist pursuing from above, cracked marble floor underfoot, dying candlelight flickering out one by one, gothic stained-glass windows casting fractured blood-red light',
      motionPromptEn: 'fast tracking shot from below, camera shaking, mist swirling',
      dialogueKo: '제발, 누구든... 나를 좀 도와줘!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '동틀 무렵 안개를 뚫고 저택을 벗어나 서로를 부축하며 뒤돌아보는 두 사람의 마지막 모습.',
      keyframePromptEn: 'Two people stumbling together through the iron gates at first light, pale dawn mist clinging low to the ground, gothic mansion silhouette fading into fog behind them, torn and disheveled clothing, exhausted relieved expressions, cold blue dawn breaking through parting storm clouds, one last candle glow flickering out in a distant window',
      motionPromptEn: 'slow pull-back tracking shot, fog swirling around their feet',
      dialogueKo: '이제 다시는... 돌아오지 말자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 사막 서부극
  c17: [
    {
      descKo: '이글거리는 정오의 사막 고속도로 위, 먼지 뒤덮인 픽업트럭에서 내려 먼 지평선을 응시하는 방랑자의 모습.',
      keyframePromptEn: 'Lone traveler stepping down from a dust-caked pickup truck on a cracked desert highway, heat haze shimmering above the sunbaked asphalt, wide-brim weathered hat, sun-faded duster coat, endless amber horizon, harsh high-noon sun, dry scrub brush scattered along the roadside',
      motionPromptEn: 'slow low-angle push-in, heat haze rippling across the horizon',
      dialogueKo: '이 길 끝에 뭐가 있을지, 봐야겠어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '버려진 주유소 앞, 흩날리는 모래바람 속에서 낡은 가죽 장갑을 조여매며 걸어가는 모습.',
      keyframePromptEn: 'Traveler walking past a rusted abandoned gas pump, boots crunching on sunbaked dirt, worn leather gloves being tightened, sun-bleached wooden signboard creaking in the wind, swirling dust under a dusty amber sky, long harsh shadow trailing behind',
      motionPromptEn: 'steady tracking shot from the side, dust drifting across the frame',
      dialogueKo: '이 정도 모래바람쯤이야, 아무것도 아니지.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '낡은 사막 주막 그늘 아래, 오랜만에 마주한 얼굴을 보며 양철 잔을 부딪치는 순간.',
      keyframePromptEn: 'Two dust-covered travelers seated at a weathered wooden table under a torn canvas awning, tin cups raised together in a toast, cracked leather vests and sun-worn boots, desert light slicing through wooden slats, warm amber dust motes drifting in the air',
      motionPromptEn: 'slow handheld dolly-in, dust motes floating through the sunbeams',
      dialogueKo: '오랜만이야, 안 죽고 잘 버텼군.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '길게 늘어진 그림자 사이로 홀로 서서 다가오는 위협을 응시하는 결연한 눈빛.',
      keyframePromptEn: 'Lone figure standing at the center of a sunbaked desert highway in late afternoon, long stretched shadow reaching across cracked asphalt, weathered hand resting near a worn leather holster, faint dust cloud rising on the distant horizon, golden dusty light',
      motionPromptEn: 'slow zoom in on the resolute gaze, distant dust cloud approaching',
      dialogueKo: '이번엔 물러서지 않아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '정오의 태양 아래 등을 맞대고 선 두 사람이 다가오는 모래폭풍을 향해 맞서는 순간.',
      keyframePromptEn: 'Two figures standing back to back at a desolate desert crossroads under the high-noon sun, dust storm looming on the horizon, duster coats whipping in the wind, hands hovering near holsters, sharp short shadows on cracked earth, swirling amber sand',
      motionPromptEn: 'slow orbiting crane shot around the pair, sandstorm swirling closer',
      dialogueKo: '여기서부턴, 같이 간다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '모래바람이 잦아든 사막 고속도로 위로 노을을 향해 유유히 멀어지는 뒷모습.',
      keyframePromptEn: 'Lone silhouette walking away down an empty desert highway at sunset, long dramatic shadow stretching across the asphalt, settling dust catching the light, deep amber and burnt-orange sky, distant mesas fading into the haze',
      motionPromptEn: 'slow wide pull-back, dust settling in the golden light',
      dialogueKo: '다음 길은 또, 어디로 이어질까.',
      subjectRefs: ['person_1']
    }
  ],
  // 카지노 강탈극
  c18: [
    {
      descKo: '자정의 화려한 카지노 입구로 침착하게 들어서는 주인공의 결의에 찬 뒷모습.',
      keyframePromptEn: 'A lone protagonist in a sharp black tailored suit stepping through a grand casino entrance at midnight, crystal chandeliers glowing overhead, emerald green marble floor, gold trim architectural details, city skyline glimpsed through tall glass doors, composed confident expression, warm champagne-toned light',
      motionPromptEn: 'slow dolly forward following the entrance',
      dialogueKo: '오늘 밤, 판이 뒤집힌다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '룰렛 테이블 앞에서 태연히 판을 돌리며 경비의 동선을 살피는 주인공의 날카로운 눈빛.',
      keyframePromptEn: 'Protagonist standing at a roulette table, spinning wheel blurred mid-motion, stacks of gold chips on emerald green felt, cufflink glinting under chandelier light, sidelong glance toward blurred security guards in the background, tense composed poise, rich gold and emerald color palette',
      motionPromptEn: 'slow rack focus from the chips to the guards',
      dialogueKo: '3분 후, 저 문이 열려.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '샴페인 잔을 부딪히며 은밀한 신호를 주고받는 두 사람의 팽팽한 순간.',
      keyframePromptEn: 'Two people clinking champagne flutes at a casino bar, one in a sharp emerald tailored suit and one in a glittering gold gown, secretive knowing eye contact, golden bokeh chandelier lights, card tables blurred in the background, poised smiles concealing tension',
      motionPromptEn: 'slow orbit around the clinking glasses',
      dialogueKo: '신호 오면, 망설이지 마.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '황금빛 금고실 복도, 경보등이 번쩍이는 사이로 조용히 잠입하는 주인공의 긴장된 손끝.',
      keyframePromptEn: 'Dim gold-toned vault corridor, heavy vault door ajar, red alarm light flickering across the walls, gloved hands reaching toward the lock, narrowed focused eyes, faint green laser security grid crossing the hallway, tense deep shadows',
      motionPromptEn: 'fast low-angle tracking shot, sparks of red alarm light',
      dialogueKo: '여기서부턴, 소리 없이.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '경보음이 울려 퍼지자 화려한 게임장을 가로질러 질주하는 주인공의 다급한 뒷모습.',
      keyframePromptEn: 'Casino gaming floor in chaos, gold chips scattering through the air, panicked crowd blurred in motion, red alarm lights flashing across emerald green walls, suit jacket flaring open mid-run, dramatic side lighting, streaks of motion blur',
      motionPromptEn: 'fast tracking shot from the side, camera shake, lights strobing',
      dialogueKo: '이제 뛰어야 해!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '멀어지는 카지노의 불빛을 등지고 여유로운 미소를 나누는 두 사람의 만족스러운 얼굴.',
      keyframePromptEn: 'Two figures in tailored suits standing on a rooftop terrace at night, glittering casino skyline glowing behind them, gold chips glinting between fingers, champagne-toned city lights reflected in their eyes, relaxed triumphant smiles, deep emerald night sky above',
      motionPromptEn: 'slow pull back revealing the skyline',
      dialogueKo: '다음 판은, 더 크게 가자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 재난 생존 드라마
  c19: [
    {
      descKo: '잿빛 하늘 아래 해안 마을 앞에 모여 다가오는 폭풍을 불안하게 올려다보는 가족.',
      keyframePromptEn: 'storm-ravaged coastal village, churning gray-teal storm clouds looming over the horizon, small huddled group standing on a wooden porch, worried upward gazes, wind bending nearby palm trees, loose shutters rattling, dim greenish pre-storm light, distant whitecapped waves',
      motionPromptEn: 'slow push-in toward the group, clouds churning overhead',
      dialogueKo: '심상치 않은 날씨야, 서둘러야 해.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '몰아치는 비바람 속에서 창문을 판자로 급히 막아내는 주인공의 다급한 손길.',
      keyframePromptEn: 'protagonist hammering wooden boards over a rattling window, driving horizontal rain, wind-whipped soaked hair and clothing, loose shingles flying past, coastal house exterior, storm-teal sky darkening to near black, single swinging porch light casting flickering shadows',
      motionPromptEn: 'handheld shaky push-in, rain streaking across frame',
      dialogueKo: '시간이 없어, 완전히 잠가야 해!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '거센 해일이 마을을 집어삼키며 불어난 물살 속을 필사적으로 헤쳐나가는 주인공.',
      keyframePromptEn: 'flooded coastal street submerged in chest-deep churning gray-teal water, protagonist wading forward against the current, floating debris and overturned furniture, torrential rain pounding the surface, storm-dark sky, distant collapsing power line sparking',
      motionPromptEn: 'fast tracking shot alongside the wading figure, waves surging into frame',
      dialogueKo: '조금만 더, 버텨야 해!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '무너진 잔해 더미 사이에서 흩어진 가족을 애타게 부르며 찾아 헤매는 주인공.',
      keyframePromptEn: 'collapsed timber and shattered roofing scattered across a storm-wrecked yard, protagonist scrambling over debris, torn soaked clothing, rain-streaked desperate face, storm-teal gray light filtering through low clouds, splintered wood and downed branches everywhere',
      motionPromptEn: 'whip-pan search across the wreckage, rain streaking through frame',
      dialogueKo: '어디 있어! 대답 좀 해봐!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '무너진 지붕 아래에서 마침내 서로를 찾아낸 두 사람이 부둥켜안으며 안도하는 순간.',
      keyframePromptEn: 'two soaked survivors embracing tightly beneath a partially collapsed roof overhang, rain dripping from splintered beams, exhausted relieved expressions, storm clouds beginning to thin overhead, faint pale light breaking through the gray-teal haze, scattered wreckage in the background',
      motionPromptEn: 'slow circular dolly around the embrace, rain easing to a drizzle',
      dialogueKo: '괜찮아... 이제 괜찮아.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '폭풍이 지나간 새벽, 고요해진 해안가 잔해 속에서 떠오르는 여명을 바라보는 주인공.',
      keyframePromptEn: 'calm storm-battered coastline at first light, scattered driftwood and debris along the wet sand, torn gray-teal storm clouds breaking apart to reveal soft warm dawn light, protagonist standing still facing the horizon, gentle waves now lapping quietly, distant birds returning to the sky',
      motionPromptEn: 'slow tilt up from the wreckage toward the brightening sky',
      dialogueKo: '우리, 결국 살아남았어.',
      subjectRefs: ['person_1']
    }
  ],
  // 법정 드라마
  c20: [
    {
      descKo: '법원 복도를 서류 가방을 들고 무거운 걸음으로 걸어가는 주인공의 모습.',
      keyframePromptEn: 'Lone figure walking through a vast marble courthouse corridor, cold fluorescent light overhead, dark wood doors lining the hall, worn leather briefcase in hand, tense rigid posture, long steel-blue shadows stretching across polished stone floor',
      motionPromptEn: 'slow tracking shot following from behind, footsteps echoing down the hall',
      dialogueKo: '오늘, 진실을 말해야 해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '빈 법정 안, 흩어진 서류를 살피며 마지막 준비를 하는 주인공의 진지한 얼굴.',
      keyframePromptEn: 'Protagonist seated alone at a dark wood table inside an empty courtroom, case files and legal documents scattered across the surface, cold steel-blue morning light filtering through tall narrow windows, furrowed brow, focused unwavering gaze',
      motionPromptEn: 'slow push-in toward the face, papers rustling as a hand turns a page',
      dialogueKo: '이 증거 하나가 전부를 바꿀 수도 있어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '방청석에 앉은 가족과 눈이 마주치며 용기를 얻는 짧은 순간.',
      keyframePromptEn: 'Protagonist standing near the witness stand glancing back toward a familiar figure seated on a dark wood bench in the courtroom gallery, harsh fluorescent light overhead, tall marble columns framing the room, quiet reassuring eye contact across the hushed space',
      motionPromptEn: 'slow rack focus shifting between the two figures, faint light flicker overhead',
      dialogueKo: '네가 있어서 버틸 수 있어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '증인석에 선 주인공이 떨리는 목소리로 진실을 증언하는 결정적 순간.',
      keyframePromptEn: 'Close-up of protagonist standing at a worn dark wood witness stand, one hand gripping the polished edge, harsh cold fluorescent light casting sharp shadows across the face, faint sheen of tension on the brow, steel-blue haze filling the blurred courtroom behind, scattered case files out of focus in the foreground',
      motionPromptEn: 'slow zoom in on the face, overhead light subtly flickering',
      dialogueKo: '저는 그날 있었던 일을, 그대로 말하겠습니다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '판결을 기다리며 정적에 잠긴 법정 안, 숨죽인 순간.',
      keyframePromptEn: "Protagonist standing motionless at the center of a hushed marble courtroom, cold overhead light falling straight down in a narrow beam, distant judge's bench softly blurred beyond, loose papers resting still on the dark wood floor, shallow breath held in silence",
      motionPromptEn: 'static shot slowly dimming, dust particles drifting through the light beam',
      dialogueKo: '이제, 결과를 받아들일 시간이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '법원 계단을 나란히 내려오며 서로를 다독이는 안도의 순간.',
      keyframePromptEn: 'Two figures walking together down the wide marble steps outside a grand courthouse, overcast steel-blue sky above, long cool shadows stretching across the stone, quiet relieved expressions, distant hazy city skyline beyond the columns',
      motionPromptEn: 'slow tracking shot from the side, coat hems drifting in a light breeze',
      dialogueKo: '이제 다 끝났어. 같이 가자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 이민자 가족 서사
  c21: [
    {
      descKo: '새벽 안개 낀 기차역에서 낡은 가방을 쥐고 고향을 뒤돌아보는 순간.',
      keyframePromptEn: 'Lone traveler standing alone on a foggy train platform at dawn, weathered leather suitcase gripped in hand, sepia-toned muted color palette, steam rising from an idling train behind, faded family photograph tucked into a coat pocket, wistful backward glance toward the platform, warm amber station lights glowing through the mist',
      motionPromptEn: 'slow pull-back revealing the empty platform, steam drifting past the frame',
      dialogueKo: '다시 돌아올 수 있을까.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '낯선 항구 도시에 첫발을 내딛으며 유리빌딩 사이로 시선을 옮기는 순간.',
      keyframePromptEn: "Lone immigrant stepping off a ship's gangway into a hazy unfamiliar harbor city, worn suitcase and battered cardboard trunk in hand, towering skyline of steel and glass rising through morning haze, sepia warmth of the old world fading into cooler daylight tones, uncertain yet determined expression, gulls circling distant cranes",
      motionPromptEn: 'slow tilt up from the suitcase to the towering skyline',
      dialogueKo: '이제부터 진짜 시작이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '네온 불빛 아래 식당 주방에서 밤새 일하며 버텨내는 순간.',
      keyframePromptEn: 'Lone worker laboring through a late night shift in a cramped diner kitchen, steam rising off a sink full of dishes, neon signage glowing red and blue through a rain-streaked window, exhausted calloused hands, a small faded photograph taped above the sink, quiet unbroken resolve on a tired face',
      motionPromptEn: 'slow handheld push-in across the kitchen, neon light flickering on wet glass',
      dialogueKo: '힘들어도 여기서 버텨야 해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '공항 입국장에서 가족과 재회하며 빛바랜 사진이 흘러내리는 순간.',
      keyframePromptEn: 'Two family members embracing tearfully at an airport arrivals gate, a worn suitcase dropped beside them, a faded sepia photograph slipping loose from an overcoat pocket onto the polished floor, modern glass terminal glowing with cool evening light, warm golden emotion breaking through the sterile coldness, blurred travelers passing behind',
      motionPromptEn: 'slow orbit around the embrace, crowd blurring past in the background',
      dialogueKo: '이렇게 다시 만날 줄 몰랐어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '고층 창가에서 오래된 사진을 도시 야경에 비춰보며 지난 세월을 되새기는 순간.',
      keyframePromptEn: 'Protagonist standing alone at a high-rise apartment window at dusk, holding a faded sepia photograph up against the glowing glass-and-neon skyline outside, warm amber photograph tones bleeding into the cool blue city light, weathered contemplative expression, decades of memory layered in the reflected glass',
      motionPromptEn: 'slow dolly in toward the window, city lights shimmering below',
      dialogueKo: '그때 그 사람들이 있어 지금의 내가 있어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '옥상 테라스에서 가족과 함께 낡은 사진들을 나누며 웃음 짓는 순간.',
      keyframePromptEn: "Two family members standing together on a rooftop terrace at night, warm string lights glowing overhead, an old sepia suitcase and a stack of faded photographs resting on a small table nearby, glittering modern glass skyline behind them, warm golden light merging with the city's cool neon glow, content hopeful smiles shared between them",
      motionPromptEn: 'slow crane shot rising over the rooftop gathering, city lights sparkling beyond',
      dialogueKo: '우리 가족의 이야기는 계속될 거야.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 아이돌 그룹 무대
  c22: [
    {
      descKo: '무대 뒤 어두운 대기실에서 조명이 켜지기를 기다리며 숨을 고르는 순간.',
      keyframePromptEn: 'Solo idol performer standing backstage in a dim waiting area, stage lights glowing faintly through a gap in the curtain, magenta and cyan light spilling along the edges, sequined stage outfit, focused breathing, anticipation in the eyes, faint stage smoke drifting in',
      motionPromptEn: 'slow push-in on the face, light flickering through the curtain gap',
      dialogueKo: '드디어 우리 차례야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '무대 위로 첫 발을 내딛으며 쏟아지는 스포트라이트를 마주하는 순간.',
      keyframePromptEn: 'Solo idol stepping onto a grand concert stage, blinding magenta spotlight sweeping across the floor, cyan laser beams slicing through rising stage smoke, sequined costume catching the light, confident stride, crowd silhouettes blurred in the dark distance',
      motionPromptEn: 'low-angle tracking shot rising with the step, spotlight sweeping past',
      dialogueKo: '이 순간을 기다려왔어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '두 사람이 정확히 맞춘 동작으로 마주 보며 무대 중앙을 채우는 순간.',
      keyframePromptEn: 'Two performers in perfectly synchronized choreography facing each other center stage, magenta and cyan spotlights crossing between them, sharp matching hand gestures, stage smoke swirling at their feet, glittering costumes, dynamic dance formation',
      motionPromptEn: 'fast circular dolly around both dancers, lights strobing',
      dialogueKo: '완벽하게 맞았어!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '강렬한 비트에 맞춰 홀로 클라이맥스 동작을 터뜨리는 순간.',
      keyframePromptEn: 'Solo idol performer mid-air during an explosive dance break, magenta backlight silhouetting the sharp body line, cyan spotlight beam cutting through thick stage smoke, sweat glistening under hot stage lights, intense focused expression, confetti particles beginning to drift',
      motionPromptEn: 'rapid low-angle whip pan following the jump, strobe flashes',
      dialogueKo: '지금 이 순간, 다 쏟아낼게.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노래의 절정에서 서로의 손을 맞잡고 눈빛을 교환하는 순간.',
      keyframePromptEn: 'Two performers reaching out and clasping hands at the peak of the chorus, magenta and cyan spotlights blending into a soft purple haze around them, stage smoke drifting low, emotional locked eye contact, glittering costumes catching cross light, arena lights sparkling in the background',
      motionPromptEn: 'slow orbit closing in on the clasped hands and faces',
      dialogueKo: '우리가 함께라서 여기까지 왔어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '폭죽과 색종이가 쏟아지는 가운데 마지막 포즈로 무대를 완성하는 순간.',
      keyframePromptEn: 'Solo idol striking a final triumphant pose center stage, confetti and metallic streamers raining down, magenta and cyan spotlights converging into a bright halo, stage smoke glowing under the lights, glittering costume sparkling, arms raised toward the cheering crowd silhouettes',
      motionPromptEn: 'slow crane shot pulling back and up, confetti falling in slow motion',
      dialogueKo: '우리의 무대, 잊지 마!',
      subjectRefs: ['person_1']
    }
  ],
  // 록 밴드 라이브
  c23: [
    {
      descKo: '무대 뒤 좁은 대기실에서 홀로 기타 줄을 조율하며 숨을 고르는 주인공.',
      keyframePromptEn: 'Lone musician in a cramped backstage room lit by a single bare bulb, tuning an electric guitar, worn leather jacket damp with sweat, tangled amp cables coiled at bare feet, graffiti-scrawled concrete wall, faint amber stage glow bleeding through a cracked door',
      motionPromptEn: 'slow push-in on hands tightening the guitar strings',
      dialogueKo: '오늘 밤, 다 쏟아붓는 거야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '관객의 함성 속으로 첫 발을 내딛으며 무대에 오르는 주인공.',
      keyframePromptEn: 'Musician stepping onto a small underground stage, amber spotlight cutting through drifting smoke, stacked amplifiers and a battered drum kit behind, raised silhouetted hands of the crowd in the foreground, sweat glistening under hot stage lights, guitar strap slung low',
      motionPromptEn: 'low-angle tracking shot rising with the step onto stage',
      dialogueKo: '다들, 준비됐어?',
      subjectRefs: ['person_1']
    },
    {
      descKo: '드럼 비트가 시작되기 직전, 서로 눈빛을 주고받는 두 사람.',
      keyframePromptEn: 'Two musicians standing back to back on a smoke-filled stage, guitar and bass slung low, amber and red light streaks crossing sweat-soaked skin, sharp knowing glance exchanged between them, cymbals glinting behind, cables snaking across the floor',
      motionPromptEn: 'quick handheld whip pan between the two musicians',
      dialogueKo: '지금이야, 가자!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '전력을 다해 기타를 내리치며 폭발적인 솔로를 쏟아내는 순간.',
      keyframePromptEn: 'Musician mid-jump on stage, electric guitar raised overhead, strings blurred with violent motion, sweat flying off tangled hair, thick smoke swirling under amber and violet stage lights, distorted amp stacks rattling behind, crowd hands reaching up in silhouette below',
      motionPromptEn: 'fast low-angle shot with handheld shake, strobing light flashes',
      dialogueKo: '이 순간을 위해 살아왔어!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '하나의 마이크에 얼굴을 맞대고 마지막 후렴을 함께 외치는 두 사람.',
      keyframePromptEn: 'Two musicians pressed shoulder to shoulder sharing a single microphone, mouths open mid-shout, sweat-drenched hair stuck to their foreheads, amber stage lights flaring behind them, smoke curling around silhouetted drum cymbals, blurred glow of the crowd at the edges of frame',
      motionPromptEn: 'slow circular dolly around the pair, light flares streaking',
      dialogueKo: '이 소리, 잊지 마!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '함성이 잦아든 무대 위에 걸터앉아 여운에 잠긴 주인공의 뒷모습.',
      keyframePromptEn: 'Musician sitting alone on the edge of the empty stage, guitar resting against one leg, dim amber house lights fading, smoke settling low across the floor, scattered cables and empty cans near silent amp stacks, exhausted content expression',
      motionPromptEn: 'slow pull-back revealing the empty smoky stage',
      dialogueKo: '오늘 밤, 진짜 살아있었어.',
      subjectRefs: ['person_1']
    }
  ],
  // 시티팝 레트로
  c24: [
    {
      descKo: '노을 지는 옥상에서 네온 스카이라인을 바라보며 카세트 플레이어로 음악을 듣는 순간.',
      keyframePromptEn: 'Solo figure leaning against a rooftop railing at dusk, retro cassette Walkman in hand, neon 1980s skyline glowing behind a pastel pink and purple gradient sky, faint synthwave grid horizon shimmering in the distance, vintage windbreaker jacket, wistful contemplative expression',
      motionPromptEn: 'slow push-in toward the glowing skyline, neon lights shimmering',
      dialogueKo: '이 노래만 들으면 그때가 생각나.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '네온 간판이 반짝이는 거리를 따라 걸으며 도시의 리듬 속으로 들어서는 순간.',
      keyframePromptEn: 'Solo figure walking down a glowing neon-lit street at night, reflections of pink and cyan signage rippling on wet pavement, retro 1980s storefronts, palm tree silhouettes, synthwave grid horizon glowing faintly in the distance, high-waisted jeans and retro sunglasses',
      motionPromptEn: 'smooth tracking shot from the side, neon signs flickering past',
      dialogueKo: '오늘 밤은 왠지 특별할 것 같아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '루프탑 바에서 반가운 얼굴과 마주치며 미소 짓는 설레는 순간.',
      keyframePromptEn: 'Two people meeting on a neon-lit rooftop terrace bar, glowing pastel signage overhead, soft disco ball reflections scattering across faces, city skyline grid horizon glowing pink and teal behind them, vintage 1980s fashion, warm delighted smiles',
      motionPromptEn: 'slow dolly circling both figures, neon lights sparkling',
      dialogueKo: '여기서 만날 줄은 몰랐네.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '해안 도로를 홀로 드라이브하며 지나간 밤을 떠올리는 아련한 순간.',
      keyframePromptEn: 'Solo figure driving a vintage convertible along a coastal highway at night, hair blowing in the wind, neon horizon glowing pink and purple over the dark ocean, faint synthwave grid lines shimmering across the water, dashboard lit with warm amber dials',
      motionPromptEn: 'fast tracking shot alongside the car, wind streaking, lights blurring past',
      dialogueKo: '이 밤이 끝나지 않았으면 좋겠어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '친구와 함께 네온 불빛 아래서 마음껏 웃고 춤추는 벅찬 순간.',
      keyframePromptEn: 'Two people dancing together on a glowing rooftop under a giant pastel neon sign, synthwave gradient sky streaked pink and violet behind them, distant city grid horizon sparkling, retro fashion, shimmering light flares drifting through the air, joyful laughter',
      motionPromptEn: 'dynamic handheld orbit around the dancing figures, lights flaring',
      dialogueKo: '오늘 이 순간을 절대 잊지 못할 거야.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '새벽빛이 번지는 네온 지평선을 향해 차를 몰고 떠나가는 잔잔한 순간.',
      keyframePromptEn: 'Solo figure driving away down an empty neon-lit highway toward a glowing pastel dawn horizon, synthwave grid fading softly into rising sunrise colors, city skyline silhouette shrinking in the rearview mirror, calm serene afterglow mood',
      motionPromptEn: 'slow pull-back aerial shot following the car into the horizon',
      dialogueKo: '다시 또 이런 밤이 오겠지.',
      subjectRefs: ['person_1']
    }
  ],
  // 어쿠스틱 버스킹
  c25: [
    {
      descKo: '노을이 내려앉는 거리 모퉁이에서 기타 케이스를 펼치고 조명을 밝히며 버스킹을 준비하는 순간.',
      keyframePromptEn: 'A lone street musician kneeling beside an open guitar case on a cobblestone corner, velvet-lined case scattered with a few coins, warm string of fairy lights draped overhead just flickering on, golden hour sunset glow washing the brick walls, soft amber haze in the air',
      motionPromptEn: 'slow push-in toward the guitar case, fairy lights flickering on one by one',
      dialogueKo: '오늘 밤엔 이 노래를 들려주고 싶어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '첫 코드를 튕기며 노래를 시작하자 지나가던 사람들이 하나둘 발걸음을 멈추는 순간.',
      keyframePromptEn: 'A lone musician strumming an acoustic guitar under warm fairy lights, eyes gently closed in concentration, faint silhouettes of passersby pausing at the edge of golden lamplight, distant cafe windows glowing amber, soft bokeh lights scattered in the background',
      motionPromptEn: 'slow handheld arc around the performer, fairy lights swaying gently',
      dialogueKo: '떨리지만... 시작해볼게요.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노래에 이끌려 다가온 소중한 사람이 가까이 서서 조용히 귀 기울이는 순간.',
      keyframePromptEn: 'Two people at a busking corner, one playing guitar under strings of warm fairy lights, the other standing close with a soft attentive smile, golden bokeh lights blurred behind them, warm intimate amber street glow, worn guitar case resting nearby',
      motionPromptEn: 'slow lateral tracking shot drawing the two figures closer',
      dialogueKo: '이 노래, 꼭 너한테 들려주고 싶었어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노래가 절정에 다다르며 온몸으로 감정을 쏟아내는 클라이맥스의 순간.',
      keyframePromptEn: 'Close-up of a musician mid-performance, head tilted slightly back with passionate expression, fingers blurred across guitar strings, warm fairy lights glowing directly overhead, small crowd silhouettes holding up glowing phone lights, golden amber tones saturating the whole street',
      motionPromptEn: 'slow close-up orbit, fairy light bokeh drifting past frame',
      dialogueKo: '이 순간을 위해 여기까지 왔어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '소중한 사람이 곁으로 다가와 함께 노래를 흥얼거리며 하모니를 이루는 순간.',
      keyframePromptEn: 'Two people singing together at a busking corner, guitar held between them, cheeks close and voices blending, warm fairy lights glowing softly above, gentle golden backlight, joyful harmonious expressions, small crowd smiling warmly around them',
      motionPromptEn: 'slow circular dolly around the duo, string lights twinkling',
      dialogueKo: '네 목소리랑 이렇게 잘 어울릴 줄이야.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '마지막 화음이 울려 퍼지고 따뜻한 박수와 함께 버스킹이 마무리되는 순간.',
      keyframePromptEn: 'A lone musician taking a gentle bow beside an open guitar case now filled with coins, glowing fairy lights strung overhead, soft silhouettes of the crowd clapping in warm golden dusk, string lights reflecting off damp cobblestones, tender satisfied smile',
      motionPromptEn: 'slow pull-back wide shot, fairy lights glowing brighter as dusk deepens',
      dialogueKo: '오늘 노래, 다들 즐거우셨나요.',
      subjectRefs: ['person_1']
    }
  ],
  // 사이버펑크 도시
  c26: [
    {
      descKo: '비 내리는 네온 골목, 홀로그램 간판 불빛 아래 홀로 서서 도시를 마주하는 순간.',
      keyframePromptEn: 'cel-shaded animation style, lone protagonist standing in a rain-slicked neon alley, towering holographic billboards flickering overhead, chrome-plated walls reflecting violet and cyan light, wet asphalt mirroring neon signage, drifting electric blue-violet haze, sleek futuristic megacity skyline in the distance',
      motionPromptEn: 'slow push-in through drifting neon haze, holographic signs flickering',
      dialogueKo: '이 도시는 늘 날 지켜보고 있어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '고가도로 아래 글리치하는 홀로그램 광고 사이를 헤치며 걸어가는 주인공의 순간.',
      keyframePromptEn: 'cel-shaded animation style, protagonist walking beneath towering elevated highways, holographic advertisements glitching along glass building facades, chrome-finished umbrella reflecting neon glow, rain streaking through violet-blue haze, glowing signage rippling across puddled streets',
      motionPromptEn: 'tracking shot following from behind, neon reflections rippling in puddles',
      dialogueKo: '답을 찾으려면 더 깊이 들어가야 해.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '옥상 야시장에서 오랜 친구와 마주쳐 정보를 주고받는 순간.',
      keyframePromptEn: 'cel-shaded animation style, two figures meeting at a crowded rooftop night market, strings of holographic lanterns glowing violet and cyan, chrome vending stalls steaming under neon light, drizzling rain haze drifting between stalls, distant megacity skyline glittering below',
      motionPromptEn: 'slow lateral dolly across the market stalls, holographic lanterns swaying',
      dialogueKo: '정보는 구했어, 근데 대가가 있어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '좁은 네온 골목을 감시 드론에 쫓기며 전력 질주하는 순간.',
      keyframePromptEn: 'cel-shaded animation style, protagonist sprinting through a narrow neon-drenched alley, motion-blurred holographic signage overhead, chrome surveillance drones hovering with scanning light beams, rain splattering off wet pavement, deep electric blue-violet haze glowing behind',
      motionPromptEn: 'fast tracking shot from the side, camera shake, neon streaks blurring',
      dialogueKo: '들켰어, 뛰어야 해!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '폭우 속 초고층 옥상 끝에 홀로 서서 결단을 내리는 순간.',
      keyframePromptEn: 'cel-shaded animation style, protagonist standing alone at the edge of a rain-lashed skyscraper rooftop, towering holographic advertisements looming overhead, chrome cityscape sprawling below drenched in electric blue-violet haze, wind-whipped coat and hair, silhouette lit by glowing signage',
      motionPromptEn: 'slow orbit around the character, wind blowing rain sideways',
      dialogueKo: '여기서 멈추지 않아, 끝까지 간다.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '새벽빛과 네온이 뒤섞인 거리를 나란히 걸어가는 두 사람의 순간.',
      keyframePromptEn: 'cel-shaded animation style, two silhouettes walking side by side down a rain-glossed neon boulevard, holographic signage dimming into soft dawn light, chrome skyscrapers fading into violet-blue haze, reflections rippling across wet pavement, glowing megacity stretching toward the horizon',
      motionPromptEn: 'slow tracking shot from behind, neon lights gradually fading into dawn glow',
      dialogueKo: '이 도시에서, 우리만의 길을 찾았어.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 이세계 판타지
  c27: [
    {
      descKo: '낡은 다락방 한켠에서 갑자기 빛나는 포털이 열리며 신비로운 빛이 쏟아지는 순간.',
      keyframePromptEn: "A lone protagonist standing in a dusty attic, a shimmering swirling portal of golden light tearing open in the wooden wall, dust motes floating in radiant beams, painterly saturated fantasy glow spilling into the room, astonished expression, warm amber interior light contrasting the portal's glow",
      motionPromptEn: 'slow push-in toward the glowing portal, light particles drifting',
      dialogueKo: '이게 대체 뭐지?',
      subjectRefs: ['person_1']
    },
    {
      descKo: '포털을 통과해 두둥실 떠 있는 섬들 사이로 발을 내딛는 순간.',
      keyframePromptEn: 'Protagonist stepping through a dissolving veil of light onto a floating island, ancient stone archway covered in glowing moss, distant islands drifting in a saturated pastel sky, waterfalls pouring into clouds below, painterly fantasy illustration style, vivid teal and violet atmosphere',
      motionPromptEn: 'slow reveal crane shot rising to show the floating islands',
      dialogueKo: '여긴... 완전히 다른 세계야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '이끼 낀 고대 유적의 벽화 앞에서 소중한 사람과 함께 놀라움을 나누는 순간.',
      keyframePromptEn: 'Two people standing before towering ancient ruins covered in glowing runes and vines, crumbling stone pillars with fragments of rock suspended in midair, shafts of golden light piercing through drifting mist, vivid saturated fantasy colors, awe-struck expressions, intricate carved fantasy architecture',
      motionPromptEn: 'slow tracking shot circling the ruins, light shafts shifting',
      dialogueKo: '이 문양들, 뭔가 의미가 있는 것 같아.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '고대 유적 깊은 곳에서 거대한 수호석상의 눈이 붉게 빛나며 깨어나는 순간.',
      keyframePromptEn: 'A colossal ancient stone guardian statue overgrown with luminous vines cracking open, glowing crimson eyes igniting in the dim ruin chamber, floating rock shards trembling around it, dramatic shafts of light cutting through swirling dust, protagonist stepping back in alarm, painterly fantasy tension, deep shadowed stone chamber',
      motionPromptEn: "quick handheld zoom out as the statue's eyes ignite, dust shaking loose",
      dialogueKo: '다들 조심해, 뭔가 깨어났어!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '무너지는 유적 사이에서 서로의 손을 맞잡고 빛의 결계를 펼치는 순간.',
      keyframePromptEn: 'Two figures standing back to back amid crumbling floating ruins, a radiant swirling barrier of golden and violet light erupting around them, shards of stone suspended mid-collapse, brilliant saturated magical glow illuminating their determined faces, dynamic fantasy energy, sparks and light motes scattering outward',
      motionPromptEn: 'fast orbiting shot around the pair as the light barrier expands',
      dialogueKo: '내가 지켜줄게, 걱정 마.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '위기를 넘긴 뒤 떠 있는 섬 끝자락에 앉아 노을 지는 신비로운 세계를 바라보는 순간.',
      keyframePromptEn: 'Protagonist sitting quietly at the edge of a floating island, legs dangling over drifting clouds, ancient ruins glowing softly behind, distant islands and waterfalls bathed in warm saturated sunset light, serene painterly fantasy landscape stretching to the horizon, glowing fireflies drifting in the air',
      motionPromptEn: 'slow pull-back crane shot revealing the vast floating world',
      dialogueKo: '이 세계에서, 새로운 이야기가 시작되겠지.',
      subjectRefs: ['person_1']
    }
  ],
  // 점토 애니메이션
  c28: [
    {
      descKo: '아침 햇살 아래, 삐뚤빼뚤한 점토 집 창문을 열고 마을을 내다보는 주인공.',
      keyframePromptEn: 'claymation protagonist figure with visible fingerprint textures and stop-motion tool marks, standing at a lopsided clay house window, felt curtain fluttering softly, miniature clay village rooftops with cotton-wisp chimney smoke, morning sunlight in golden putty tones, charmingly imperfect handcrafted diorama world, tiny clay flowerpots on the windowsill',
      motionPromptEn: 'slow push-in through the window frame, dust motes drifting in the light',
      dialogueKo: '오늘은 뭔가 특별한 일이 생길 것 같아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '펠트 질감의 언덕길을 따라 삐걱대는 점토 다리를 조심스레 건너는 주인공.',
      keyframePromptEn: 'claymation protagonist figure walking along a felt-textured green hill path, tiny wobbly clay bridge crossing a blue cellophane river, fingerprint-dappled putty rooftops in the distance, miniature pebble stones lining the trail, charmingly uneven stop-motion craftsmanship, soft matte daylight',
      motionPromptEn: 'handheld tracking alongside the path, gentle frame-by-frame jitter',
      dialogueKo: '발밑을 조심해야겠어, 다리가 좀 흔들리네.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '마을 광장 점토 좌판 앞에서 오랜 친구와 반갑게 인사를 나누는 장면.',
      keyframePromptEn: 'two claymation figures with fingerprint-textured faces greeting each other warmly at a tiny clay market stall, felt bunting flags strung overhead, miniature clay fruit and jars arranged on wooden crate tables, putty-toned cobblestone square, whimsical imperfect stop-motion charm',
      motionPromptEn: 'gentle pan across the market square, bunting flags swaying',
      dialogueKo: '이게 누구야, 여기서 다 만나네!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '갑자기 몰려온 솜뭉치 먹구름 아래, 넘어질 뻔한 점토 수레를 황급히 붙잡는 주인공.',
      keyframePromptEn: 'claymation protagonist figure lunging to catch a tipping clay cart loaded with felt sacks, cotton-ball storm clouds gathering overhead, wind-blown paper leaves scattered across the ground, fingerprint textures visible on strained clay hands, dramatic stop-motion tension, muted grey putty tones',
      motionPromptEn: 'quick whip pan toward the tipping cart, urgent frame skips',
      dialogueKo: '안돼, 조금만 더 버텨줘!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '온 가족이 함께 힘을 모아 무너진 점토 지붕을 다시 쌓아 올리는 훈훈한 순간.',
      keyframePromptEn: 'claymation family figures with charming fingerprint-dappled faces working together stacking clay bricks to rebuild a small rooftop, felt-textured hill backdrop, miniature wooden ladder props leaning against the wall, warm afternoon putty-orange light, joyful cooperative stop-motion scene',
      motionPromptEn: 'slow crane shot rising over the rebuilding scene',
      dialogueKo: '다 같이 하니까 금방 되네!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노을 지는 언덕 위에서 나란히 앉아 완성된 마을을 바라보며 미소짓는 장면.',
      keyframePromptEn: 'two claymation figures sitting side by side atop a felt-textured hill, tiny clay village glowing warm putty-orange under a cotton-wool sunset sky, fingerprint textures catching the golden light, charmingly imperfect handcrafted diorama warmth, miniature string-light lanterns flickering below',
      motionPromptEn: 'slow pull-back revealing the whole glowing village',
      dialogueKo: '역시, 우리 마을이 최고야.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 스팀펑크 모험
  c29: [
    {
      descKo: '고풍스러운 공방 안, 브라스 톱니바퀴와 설계도에 둘러싸여 비행선을 완성하는 주인공의 진지한 모습.',
      keyframePromptEn: 'Lone inventor wearing brass-rimmed steampunk goggles and a worn leather vest, standing in a cluttered Victorian workshop, copper gears and springs scattered across a wooden workbench, airship blueprints pinned to the wall, warm lantern glow, sepia-bronze color palette, brass instruments hanging from hooks',
      motionPromptEn: 'slow push-in across the workshop, gear shadows rotating on the wall',
      dialogueKo: '드디어… 날아오를 시간이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '브라스와 구리로 뒤덮인 비행선이 빅토리아풍 지붕들 위로 힘차게 떠오르는 순간, 바람을 맞는 주인공의 벅찬 얼굴.',
      keyframePromptEn: 'Protagonist standing at the helm of a brass-plated airship, gripping a large copper steering wheel, steam vents releasing white plumes along the hull, rows of Victorian rooftops and chimney spires below bathed in golden sepia light, goggles reflecting the glowing sky, wind tousling hair and coat',
      motionPromptEn: 'sweeping aerial push forward, steam trailing softly behind the ship',
      dialogueKo: '세상이 이렇게 넓었구나!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '갑판 위에서 동료와 함께 낡은 톱니 장치를 고치며 활짝 웃는 활기찬 순간.',
      keyframePromptEn: 'Two adventurers on a weathered wooden airship deck, one gripping a brass wrench against an oversized gear, the other holding a glowing steam-pressure gauge, tangled copper pipework and rope rigging around them, warm bronze sunset light, scattered brass tools and coiled chains',
      motionPromptEn: 'handheld side tracking shot, steam puffing rhythmically',
      dialogueKo: '이 톱니만 맞추면 완벽해!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '먹구름이 몰려오는 폭풍 속 하늘 위, 흔들리는 조종간을 필사적으로 붙잡는 주인공의 긴박한 모습.',
      keyframePromptEn: 'Protagonist gripping a large brass control wheel amid swirling storm clouds, lightning glinting off copper hull plating, loose gears sparking near a cracked pressure valve, wind-torn Victorian rooftops far below, dramatic steel-blue and bronze color contrast, goggles fogged with rain',
      motionPromptEn: "shaky handheld shot, camera tilting with the ship's sway",
      dialogueKo: '버텨야 해, 조금만 더!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '가족과 힘을 합쳐 과열된 증기 엔진을 진정시키며 위기를 넘기는 짜릿한 순간.',
      keyframePromptEn: 'Two figures bracing against a hissing brass engine core, one turning a large valve wheel with both hands, the other pulling down a long copper lever, bursts of steam and sparks flying off glowing coils, storm light fading into a warm amber glow, gauge needle resting in the safe zone',
      motionPromptEn: 'dynamic low-angle shot, steam bursting toward the camera',
      dialogueKo: '됐어, 엔진이 다시 돌아가!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '노을 진 하늘 아래 무사히 항해를 마친 비행선 갑판에서 도시를 내려다보며 홀로 미소 짓는 평온한 순간.',
      keyframePromptEn: "Protagonist leaning on a brass deck railing at sunset, calm steam drifting gently from copper vents, Victorian city rooftops and clock towers glowing bronze below, warm golden light gleaming across weathered goggles and coat, faint silhouette of the airship's balloon overhead",
      motionPromptEn: 'slow wide pull-back revealing the airship gliding over the golden city',
      dialogueKo: '우리, 정말 해냈어.',
      subjectRefs: ['person_1']
    }
  ],
  // 레트로 게임 감성
  c30: [
    {
      descKo: '8비트 픽셀 세계에 첫 발을 내딛으며 모험을 시작하는 주인공.',
      keyframePromptEn: 'Chunky 8-bit pixel hero character standing at a glowing level-start marker, blocky pixelated mountains in the background, bold primary color palette of red blue and yellow, pixelated clouds drifting in a flat sky, glowing arcade-cabinet frame vignette, retro CRT scanline texture, floating coin block sprite nearby',
      motionPromptEn: 'slow push-in on the pixel hero, background parallax scrolling',
      dialogueKo: '자, 게임 시작이다!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '떠 있는 블록 사이를 점프하며 반짝이는 포인트를 모으는 짜릿한 순간.',
      keyframePromptEn: 'Pixel hero character mid-jump between floating chunky platform blocks, bright coin sprites spinning and sparkling in an arc, bold primary color sky, pixelated cloud shapes, retro platformer level layout, chiptune-style particle sparkle effects',
      motionPromptEn: 'dynamic side-scrolling tracking shot following the jump arc',
      dialogueKo: '하나, 둘, 셋... 점프!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '체크포인트 깃발 앞에서 든든한 친구와 하이파이브를 나누며 힘을 합치는 순간.',
      keyframePromptEn: 'Two chunky 8-bit pixel characters giving a high-five beside a glowing checkpoint flag, pixel spark burst effect at the point of contact, blocky mountain backdrop, bold primary colors, warm arcade-cabinet glow lighting, pixelated confetti particles drifting',
      motionPromptEn: 'quick zoom in on the high-five with a bright flash',
      dialogueKo: '이제부터 같이 가자!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '거대한 픽셀 보스의 그림자가 드리우며 위기감이 감도는 순간.',
      keyframePromptEn: 'Lone pixel hero standing before a massive looming blocky boss silhouette, dramatic red and purple glitch lighting, jagged pixel outline on the boss, cracked pixel ground tiles underfoot, ominous arcade-cabinet vignette framing, bold contrasting primary colors',
      motionPromptEn: "slow dramatic zoom out revealing the boss's full towering scale",
      dialogueKo: '여기서 물러설 순 없어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '충전된 필살기를 발동해 보스에게 강렬한 빛의 일격을 날리는 주인공.',
      keyframePromptEn: 'Pixel hero unleashing a glowing special-attack beam from outstretched arms, explosive pixel particle burst, radiant primary color energy blast, shattering pixel blocks flying outward, intense arcade flash lighting, bright retro screen glow',
      motionPromptEn: 'fast dynamic shake with a bright flash at impact',
      dialogueKo: '필살기, 발동!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '픽셀 산 정상에서 친구와 함께 승리를 자축하며 축포가 터지는 순간.',
      keyframePromptEn: 'Two chunky pixel characters standing triumphantly atop a blocky pixel mountain summit, glowing victory fireworks bursting in bold primary colors, pixelated confetti falling, warm sunset gradient sky, retro arcade-cabinet glow frame, chiptune-style celebration sparkle effects',
      motionPromptEn: 'slow orbit around the victorious duo as fireworks burst',
      dialogueKo: '우리가 해냈어, 클리어!',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 결혼기념일 광고
  c31: [
    {
      descKo: '결혼반지를 만지작거리며 오래된 웨딩 사진을 바라보는 조용한 아침의 순간.',
      keyframePromptEn: 'Protagonist sitting alone at a sunlit vanity table, softly touching a wedding ring between fingers, an old wedding photograph in a blush toned frame nearby, ivory lace curtains, warm morning light, delicate rose petals scattered across the table, gentle nostalgic atmosphere',
      motionPromptEn: 'slow push-in on the hands and ring, dust motes drifting through sunlight',
      dialogueKo: '벌써 이렇게 많은 시간이 흘렀네.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불과 블러쉬빛 장미로 기념일 테이블을 정성스레 꾸미는 손길.',
      keyframePromptEn: 'Protagonist arranging an anniversary celebration table, blush pink and ivory roses in low centerpieces, rows of tapered candles freshly lit, soft golden bokeh string lights blurred in the background, fine china and champagne flutes on ivory linen, warm intimate glow',
      motionPromptEn: 'slow tracking shot along the table as candles flicker to life',
      dialogueKo: '오늘 저녁은 특별하게 준비하고 싶었어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불 켜진 현관에서 마주한 두 사람이 서로의 모습에 놀라며 설레는 미소를 짓는 순간.',
      keyframePromptEn: 'Two people meeting at a candlelit doorway, one dressed elegantly in blush and ivory attire, soft warm backlight, delicate rose petals scattered softly around them, tender surprised smiles, cinematic shallow depth of field with golden bokeh',
      motionPromptEn: "slow dolly in as they reach for each other's hands",
      dialogueKo: '오늘 이렇게 예쁘게 하고 나올 줄 몰랐어.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '촛불 켜진 테이블에서 와인잔을 부딪히며 지난 시간을 추억하는 순간.',
      keyframePromptEn: 'Two people toasting with champagne flutes at a candlelit table, blush rose petals scattered across ivory linen, warm amber bokeh lights softly blurred behind, joyful tender expressions, soft romantic glow',
      motionPromptEn: 'slow orbit around the toasting glasses, candle flames flickering',
      dialogueKo: '우리가 함께한 모든 순간에 건배.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '가족이 둘러앉아 기념일 케이크의 촛불을 함께 불며 웃음 가득한 축하를 나누는 순간.',
      keyframePromptEn: 'A couple surrounded by warm candlelight blowing out candles together on an ivory anniversary cake decorated with blush sugar flowers, joyful embracing family gathered close around the table, soft golden bokeh, blush rose petals scattered near the cake stand',
      motionPromptEn: 'slow crane shot rising above the cake as candlelight flickers',
      dialogueKo: '우리 가족 모두 함께라서 더 행복해.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '은은한 촛불 아래 서로를 안고 천천히 춤추며 마무리하는 다정한 순간.',
      keyframePromptEn: 'Two people slow dancing in a softly candlelit room, blush and ivory floral arrangements blurred in the background, warm cinematic bokeh, foreheads gently touching, tender intimate embrace, soft golden light enveloping them',
      motionPromptEn: 'slow circular dolly around the embracing couple, candlelight glowing warmly',
      dialogueKo: '앞으로도 계속, 오늘처럼 사랑하자.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 스타트업 브랜드 광고
  c32: [
    {
      descKo: '새벽 사무실, 홀로 화이트보드 앞에 서서 새로운 아이디어를 그려나가는 주인공.',
      keyframePromptEn: 'Solo founder standing before a large glass whiteboard covered in blue marker sketches and diagrams, sleek minimalist office at dawn, cool blue-white ambient light, laptop glowing faintly on a nearby desk, quiet focused expression',
      motionPromptEn: 'slow push-in toward the whiteboard, marker lines catching the light',
      dialogueKo: '이 아이디어라면 될 것 같아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '밤늦도록 노트북 화면 앞에서 몰입해 있는 주인공의 옆모습.',
      keyframePromptEn: 'Solo founder deeply focused at a laptop in a minimalist glass-walled office at night, cool blue screen glow illuminating face, scattered notes and coffee cup on desk, city lights faintly visible through window',
      motionPromptEn: 'slow handheld drift closer, screen light flickering across face',
      dialogueKo: '될 때까지 해보는 거야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '회의실 유리 테이블에 모여 아이디어를 나누며 화이트보드를 채워가는 친구들.',
      keyframePromptEn: 'Two founders leaning over a glass meeting table covered in sticky notes and sketches, minimalist office with cool blue-white lighting, laptop screens glowing between them, whiteboard filled with diagrams in the background, energetic collaborative mood',
      motionPromptEn: 'slow tracking shot around the table, papers shuffling',
      dialogueKo: '이거 진짜 되겠는데?',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '쌓여가는 커피잔과 흩어진 서류들 속에서도 흔들리지 않는 주인공의 눈빛.',
      keyframePromptEn: 'Solo founder surrounded by empty coffee cups and scattered printouts at a glass desk late at night, laptop glow reflecting on tired but determined face, minimalist office bathed in cool blue light, whiteboard sketches faintly visible behind',
      motionPromptEn: 'slow static shot with subtle handheld sway, steam rising from coffee',
      dialogueKo: '여기서 포기할 순 없어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '모니터에 뜨는 첫 신호에 두 사람이 동시에 화면으로 몸을 기울이는 순간.',
      keyframePromptEn: 'Two founders leaning toward a laptop screen displaying a glowing dashboard with a rising graph line, stunned excited expressions, minimalist glass office at night, cool blue-white light reflecting off the screen and glass walls',
      motionPromptEn: 'quick push-in toward the screen, light flaring across their faces',
      dialogueKo: '이거 봐, 진짜 올라가고 있어!',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '동틀 무렵, 통유리창 너머 도시를 바라보며 다음 걸음을 그려보는 주인공의 담담한 얼굴.',
      keyframePromptEn: 'Solo founder standing before a floor-to-ceiling glass window at dawn, city skyline glowing in cool blue and soft gold light, minimalist office interior faintly reflected in the glass, calm resolute expression',
      motionPromptEn: "slow tilt up from the skyline to the founder's face",
      dialogueKo: '이제 시작이야.',
      subjectRefs: ['person_1']
    }
  ],
  // 여행 브이로그 광고
  c33: [
    {
      descKo: '이른 아침 해안도로를 달리며 여행의 설렘을 만끽하는 순간.',
      keyframePromptEn: 'Protagonist driving a convertible along a winding coastal highway at sunrise, wind blowing through hair, turquoise ocean glimpsed between rocky cliffs, golden morning light, sunglasses reflecting the horizon, road trip atmosphere, open road stretching ahead',
      motionPromptEn: 'smooth tracking shot alongside the moving car, wind rushing past',
      dialogueKo: '드디어 떠난다, 이 순간을 기다렸어.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '하얀 절벽 위에서 눈부신 터키석빛 바다를 처음 마주하는 순간.',
      keyframePromptEn: 'Protagonist standing atop a whitewashed cliff, arms outstretched toward the horizon, vivid turquoise sea stretching endlessly below, scattered white sailboats, bright midday sun, vibrant blue sky with wisps of cloud, light linen clothing fluttering in the breeze',
      motionPromptEn: 'slow pull-back revealing the full coastline',
      dialogueKo: '이 바다 색깔 좀 봐, 진짜 상상 이상이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '골목 시장을 거닐며 낯선 여행지의 활기를 즐기는 자유로운 발걸음.',
      keyframePromptEn: 'Protagonist wandering through a sun-bleached seaside village alley, bougainvillea draped over whitewashed walls, colorful market stalls with fruit and woven baskets, dappled afternoon light, straw hat and casual linen clothing, warm ochre stone underfoot',
      motionPromptEn: 'handheld walking shot following from behind',
      dialogueKo: '여긴 골목마다 사진 찍을 곳 천지네.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '소중한 사람들과 함께 보트 위에서 웃음 가득한 오후 피크닉을 즐기는 순간.',
      keyframePromptEn: 'Two people sitting on the sun-warmed deck of a small wooden boat, sharing a fruit platter and chilled drinks, turquoise water sparkling all around, distant limestone cliffs against a vivid blue sky, relaxed candid laughter, sun hats and light linen shirts',
      motionPromptEn: "gentle handheld sway with the boat's rocking motion",
      dialogueKo: '이 순간 그대로 시간이 멈췄으면 좋겠다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '절벽 끝에서 망설임 없이 바다로 뛰어드는 짜릿한 도약의 순간.',
      keyframePromptEn: 'Protagonist leaping off a sun-warmed cliff edge into vivid turquoise water below, mid-air silhouette against a bright open sky, white foam splashing on impact, dramatic sunlight, wind-swept hair, pure exhilaration and freedom',
      motionPromptEn: 'fast whip-pan following the fall, camera dropping with the jump',
      dialogueKo: '지금 아니면 언제 해보겠어!',
      subjectRefs: ['person_1']
    },
    {
      descKo: '노을 진 해변에서 함께 손을 맞잡고 여행의 마지막 순간을 만끽하는 장면.',
      keyframePromptEn: 'Two people standing together on a golden sand beach at sunset, silhouetted against a vivid orange and pink sky, gentle waves glowing at their feet, hair and light clothing swaying in the sea breeze, warm cinematic glow, footprints trailing in the sand',
      motionPromptEn: 'slow wide pull-back revealing the full sunset horizon',
      dialogueKo: '다음 여행은 또 어디로 떠나볼까.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 피트니스 광고
  c34: [
    {
      descKo: '이른 아침, 햇살 가득한 스튜디오에 요가매트를 펼치며 하루를 준비하는 순간.',
      keyframePromptEn: 'bright airy fitness studio interior, protagonist unrolling a fresh yoga mat onto the floor, tall potted monstera and fiddle leaf plants scattered around, large windows flooding warm morning sunlight, crisp white walls, fresh green accents, minimalist wellness decor, calm focused expression, athletic wear in soft neutral tones',
      motionPromptEn: 'slow gentle push-in, sunlight rays shifting across the floor',
      dialogueKo: '오늘도 나를 위한 시간을 시작해볼까.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '밝은 스튜디오에서 친구와 나란히 스트레칭하며 서로 웃음을 나누는 순간.',
      keyframePromptEn: 'two people stretching side by side on yoga mats in a sunlit studio, potted plants framing the background, crisp white flooring, fresh green foliage, playful genuine smiles, natural daylight streaming through large windows, matching athletic outfits in fresh pastel tones',
      motionPromptEn: 'slow lateral tracking shot, light flickering through leaves',
      dialogueKo: '같이 하니까 훨씬 더 즐겁다.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '경쾌한 리듬에 맞춰 점점 속도를 높이며 활기차게 움직이는 주인공의 역동적인 순간.',
      keyframePromptEn: 'protagonist mid-jump during an energetic cardio move, bright studio flooded with natural light, potted greenery lining the walls, crisp white surfaces, dynamic athletic pose, light sheen of sweat, fresh green and white color palette, sense of building momentum',
      motionPromptEn: 'fast handheld tracking shot, following the upward movement',
      dialogueKo: '심장이 뛰는 게 느껴져, 이 순간이 좋아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '힘겨운 플랭크 자세를 끝까지 버티며 이를 악무는 주인공의 클로즈업.',
      keyframePromptEn: 'close-up of protagonist holding a challenging plank pose on a yoga mat, strained determined expression, beads of sweat catching sunlight, taut muscles, bright studio background softly blurred with green potted plants, crisp white light, quiet intensity',
      motionPromptEn: 'slow crawling dolly shot along the ground, light trembling with effort',
      dialogueKo: '포기하고 싶을 때, 딱 한 번만 더.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '마침내 완벽한 자세를 완성하고 환하게 미소 짓는 벅찬 순간.',
      keyframePromptEn: 'protagonist rising into a strong triumphant standing pose, arms extended upward, radiant genuine smile, golden sunlight flooding the studio, potted plants glowing green in the light, crisp white walls, sense of achievement and release',
      motionPromptEn: 'slow upward tilt, sunlight flaring through the window',
      dialogueKo: '해냈다, 오늘도 내가 자랑스러워.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '운동을 마친 뒤 친구와 나란히 앉아 상쾌한 얼굴로 서로를 바라보며 웃는 순간.',
      keyframePromptEn: 'two people sitting cross-legged side by side on yoga mats after a workout, refreshed content smiles, water bottles and folded towels nearby, bright studio glowing with late afternoon sunlight, lush potted plants surrounding them, crisp white and fresh green tones, warm relaxed atmosphere',
      motionPromptEn: 'slow pull-back reveal, soft light glowing across the room',
      dialogueKo: '다음에도 같이 하자, 오늘 정말 좋았어.',
      subjectRefs: ['person_1', 'person_2']
    }
  ],
  // 미식 광고
  c35: [
    {
      descKo: '레스토랑에 들어서며 은은한 촛불 조명 속으로 걸어가는 주인공의 설레는 첫 걸음.',
      keyframePromptEn: 'Protagonist walking into an elegant candlelit fine-dining restaurant, deep burgundy velvet drapes, warm gold ambient lighting, soft bokeh candle flames scattered in background, polished dark wood interior, anticipation in expression',
      motionPromptEn: 'slow steady walk-in tracking shot, candlelight flickering warmly',
      dialogueKo: '오늘 같은 날엔 특별한 곳이 필요하지.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불 흔들리는 테이블 위, 와인이 잔에 채워지며 저녁의 시작을 알리는 순간.',
      keyframePromptEn: 'close-up of a crystal wine glass being filled with deep red wine at a candlelit table, burgundy tablecloth, gold cutlery gleaming, soft flame reflections rippling on glass surface, shallow depth of field',
      motionPromptEn: 'slow motion pour, gentle rack focus from glass to candle flame',
      dialogueKo: '이 한 잔으로 하루의 피로가 녹아내리는 것 같아.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '갓 나온 요리에서 피어오르는 김과 반짝이는 플레이팅을 눈앞에서 마주하는 순간.',
      keyframePromptEn: 'extreme close-up of an exquisitely plated dish, delicate steam rising, glistening sauce drizzled in artistic swirls, gold-rimmed plate, folded burgundy linen napkin beside it, warm candle glow reflecting off glossy garnish',
      motionPromptEn: 'slow overhead push-in, steam curling upward in soft light',
      dialogueKo: '이 향만으로도 벌써 행복해지네.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '마주 앉은 두 사람이 촛불 아래서 잔을 부딪히며 함께하는 저녁을 축하하는 순간.',
      keyframePromptEn: 'two people clinking wine glasses across a candlelit table, warm golden glow on faces, burgundy and gold table setting, soft focus background of flickering candles, genuine warm smiles',
      motionPromptEn: 'slow dolly in circling the toast, candle flames swaying gently',
      dialogueKo: '우리, 오늘을 위해 건배하자.',
      subjectRefs: ['person_1', 'person_2']
    },
    {
      descKo: '정성스레 플레이팅된 요리를 한 입 맛보며 눈을 감고 깊이 음미하는 순간.',
      keyframePromptEn: 'close-up of protagonist savoring the first bite, eyes gently closed in delight, candlelight casting warm amber highlights on skin, glistening plated dish softly blurred in foreground, rich burgundy tones surrounding',
      motionPromptEn: 'slow subtle zoom in on the expression of savoring',
      dialogueKo: '이런 맛은 처음이야.',
      subjectRefs: ['person_1']
    },
    {
      descKo: '촛불이 은은하게 타오르는 테이블에서 서로를 바라보며 여운을 나누는 저녁의 마무리.',
      keyframePromptEn: 'two people lingering at a candlelit table late in the evening, empty dessert plates glazed with gold light, deep burgundy ambiance, warm contented smiles, soft flame glow illuminating both faces intimately',
      motionPromptEn: 'slow pull-back wide shot, candlelight gently flickering as the scene settles',
      dialogueKo: '이 시간이 오래 기억날 것 같아.',
      subjectRefs: ['person_1', 'person_2']
    }
  ]
}

// 폴백 기본 템플릿 (어떤 컨셉도 매칭 안될 때 사용)
const DEFAULT_CONCEPT_TEMPLATE: SceneTemplate[] = [
  {
    descKo: '카메라를 부드럽게 응시하는 인물',
    keyframePromptEn: 'Cinematic portrait of a person looking at the camera, beautiful studio lighting, highly detailed face',
    motionPromptEn: 'slow dolly in, subtle eye movement',
    dialogueKo: '기억해줘, 우리의 시간.',
    subjectRefs: ['person_1']
  },
  {
    descKo: '주변 풍경을 둘러보며 천천히 걷는 모습',
    keyframePromptEn: 'A person walking slowly in a beautiful scenic park during golden hour, soft focus bokeh background',
    motionPromptEn: 'tracking camera shot following the character',
    dialogueKo: '모든 것이 변해도 괜찮아.',
    subjectRefs: ['person_1']
  },
  {
    descKo: '석양 아래서 마주 서 있는 순간',
    keyframePromptEn: 'Two people standing together looking at the sunset, warm glowing light, nostalgic mood',
    motionPromptEn: 'slow camera panning around the characters',
    dialogueKo: '우린 함께니까.',
    subjectRefs: ['person_1', 'person_2']
  }
]

// 씬 하나의 기준/최소/최대 길이(초) — 최대치는 S4 편집 슬라이더(2~4초)와 맞춘 기본 상한이고,
// HARD_MAX는 템플릿 풀이 짧아 총 길이를 못 채울 때만 예외적으로 늘리는 절대 상한이다.
const SCENE_SEC_TARGET = 3
const SCENE_SEC_MIN = 2
const SCENE_SEC_SOFT_MAX = 4
const SCENE_SEC_HARD_MAX = 6

/**
 * durationSec를 sceneCount개 씬에 나눠 담는다. 1단계에서 2~4초 범위 안으로 최대한 맞추고,
 * 그래도 남는 시간(템플릿 풀이 짧아 씬 수를 충분히 못 늘렸을 때)은 2단계에서 6초까지만 늘려 흡수한다.
 * 그래도 못 채우면(풀이 아주 짧고 요청 길이가 아주 길면) 실제 총 길이가 요청보다 짧아질 수 있다 —
 * 이 경우가 바로 해당 컨셉의 템플릿 보강이 필요하다는 신호다.
 *
 * @param weights 선택적 상대 가중치(오마주 모드에서 레퍼런스의 컷 비율을 전달). 길이가
 *                sceneCount 와 다르거나 합이 0이면 무시하고 균등 분배한다.
 *                weights 를 넘기지 않으면 아래 균등 분배 경로만 타므로 기존 호출부(가중치 없이
 *                호출하는 모든 곳)는 이 함수가 바뀌기 전과 완전히 동일한 값을 받는다.
 *
 * ⚠️ 씬 길이는 SCENE_SEC_MIN~SCENE_SEC_SOFT_MAX(2~4초)로 우선 클램프된다. 영상 생성 어댑터가
 *    짧은 클립을 안정적으로 못 만들기 때문에 생긴 기존 제약이며, 레퍼런스의 0.5초 퀵컷이나
 *    8초 롱테이크는 그대로 재현되지 않는다(가중치를 줘도 이 클램프 자체는 그대로 적용된다).
 */
export function buildSceneDurations(durationSec: number, sceneCount: number, weights?: number[]): number[] {
  const usable = weights && weights.length === sceneCount && weights.some(w => w > 0)
    ? weights.map(w => (Number.isFinite(w) && w > 0 ? w : 0))
    : null

  let durations: number[]
  if (usable) {
    const total = usable.reduce((a, b) => a + b, 0)
    durations = usable.map(w =>
      Math.max(SCENE_SEC_MIN, Math.min(SCENE_SEC_SOFT_MAX, Math.round((durationSec * w) / total))))
  } else {
    const base = Math.max(SCENE_SEC_MIN, Math.min(SCENE_SEC_SOFT_MAX, Math.floor(durationSec / sceneCount)))
    durations = new Array(sceneCount).fill(base)
  }
  let remainder = durationSec - durations.reduce((a, b) => a + b, 0)

  for (let i = 0; i < durations.length && remainder !== 0; i++) {
    while (remainder > 0 && durations[i] < SCENE_SEC_SOFT_MAX) { durations[i]++; remainder-- }
    while (remainder < 0 && durations[i] > SCENE_SEC_MIN) { durations[i]--; remainder++ }
  }
  for (let i = 0; i < durations.length && remainder > 0; i++) {
    const room = SCENE_SEC_HARD_MAX - durations[i]
    const take = Math.min(room, remainder)
    durations[i] += take
    remainder -= take
  }
  return durations
}

/**
 * 오마주 구조를 Gemini 프롬프트용 한 줄 흐름 설명으로 바꾼다.
 *
 * ⚠️ 여기에 원본 대사를 넣지 않는다 — HomageStructure 에 애초에 그런 필드가 없다.
 *    샷 문법과 감정 단계만 전달하고, 실제 대사는 제품 분석 결과에서 창작된다.
 */
function buildHomageFlowText(structure: HomageStructure, scenes: HomageScene[]): string {
  const beats = scenes
    .map((s, i) => `${i + 1}) ${s.shotType}/${s.cameraMove} · ${s.subjectRole} · ${s.emotionBeat || '-'}`)
    .join('  →  ')
  return `[${structure.pacing} 페이싱] ${structure.overallArc}\n${beats}`
}

/**
 * Gemini 창작 이전의 초기값(그리고 만에 하나 이 값이 최종 결과까지 새는 경우의 최후 방어선)을
 * 오마주 구조 자체에서 파생시킨다.
 *
 * ⚠️ DEFAULT_CONCEPT_TEMPLATE(개인 영상용 로맨틱 커플 대사, 예: "기억해줘, 우리의 시간.")를 절대
 *    재사용하지 않는다 — HOMAGE_STRUCTURE_ID는 AD_CONCEPT_TEMPLATES에 의도적으로 미등록이라 오마주
 *    모드의 씬 풀(pool)은 항상 DEFAULT_CONCEPT_TEMPLATE로 귀결된다. 그 원문 대사를 그대로 순환시키면
 *    (예: 수분크림 광고인데) 제품과 무관한 로맨틱 문구가 반복 재생되는 사고가 난다.
 * dialogueKo는 항상 빈 문자열로 둔다 — generateStoryboardScenes가 오마주 모드에서 Gemini 실패 시
 *    명시적으로 예외를 던지므로 정상 경로에서는 이 값이 최종 결과에 도달하지 않아야 하지만, 혹시
 *    새더라도 아래쪽 "대사 보증" 안전망(대사가 전부 비었을 때만 발동)이 정상 작동하게 하기 위함이다.
 */
export function buildHomageFallbackScene(scene: HomageScene, index: number): GeneratedStoryboardScene {
  return {
    descKo: `${index + 1}번째 컷 · ${scene.shotType} 샷 · ${scene.subjectRole} 중심${scene.emotionBeat ? ` · ${scene.emotionBeat}` : ''}`,
    dialogueKo: '',
    keyframePromptEn: `${scene.shotType} shot, ${scene.cameraMove} camera movement, subject: ${scene.subjectRole}`,
    motionPromptEn: `${scene.cameraMove} camera movement`,
  }
}

/**
 * 프로젝트 설정을 바탕으로 세밀하고 정교한 스토리보드 씬 배열을 생성합니다.
 * 씬 개수는 durationSec ÷ 씬당 목표 길이(3초)로 역산하고, 컨셉 템플릿 풀 크기 안에서 자른다 —
 * 즉 영상 길이를 길게 선택할수록 (풀에 여유가 있는 한) 서사 비트가 더 많은 씬으로 반영된다.
 */
export async function generateStoryboardScenes(project: Project, persons: Person[]): Promise<Scene[]> {
  const { conceptId, styleId, backgroundId, phenomenonId, relation, durationSec } = project

  // 오마주 모드면 레퍼런스에서 뽑은 구조를 씬 뼈대로 쓴다.
  // ⚠️ homage 인데 structure 가 없으면 조용히 DEFAULT_CONCEPT_TEMPLATE 으로 흘러가면 안 된다 —
  //    사용자가 명시적으로 고른 모드라 템플릿으로 바꿔치기하면 "왜 내가 고른 영상 느낌이 안 나지"가 된다.
  const adStateEarly = useAdStore.getState()
  const isHomage = adStateEarly.adConcept?.structureSource === 'homage'
  const homageStructure = adStateEarly.adConcept?.homage?.structure

  if (isHomage && !homageStructure) {
    throw new Error('오마주 구조가 없어요. 레퍼런스를 다시 선택해주세요.')
  }

  // 1. 해당 컨셉 아이디의 템플릿 풀 가져오기 — 광고 구성(ad_*)은 adConcepts의 광고 템플릿 뱅크에서
  const pool = CONCEPT_TEMPLATES[conceptId] || AD_CONCEPT_TEMPLATES[conceptId] || DEFAULT_CONCEPT_TEMPLATE

  // 2. 요청된 영상 길이에 맞춰 필요한 씬 개수를 정하고(최소 3개), 풀 크기 안으로 자른다
  const desiredCount = Math.max(3, Math.round(durationSec / SCENE_SEC_TARGET))

  let sceneCount: number
  let chosen: typeof pool
  let durations: number[]
  // isHomage && homageStructure 일 때만 채워진다. 아래 콘텐츠 폴백(4번)과 Gemini 프롬프트용
  // structureFlow 계산이 이 값을 재사용한다 — resampleHomageScenes를 다시 부르면 두 계산이
  // (지금은 순수·결정론적이라 우연히 같지만) 나중에 함수가 바뀔 때 서로 어긋날 수 있다.
  let homageScenes: HomageScene[] | undefined

  if (isHomage && homageStructure) {
    // 레퍼런스 씬 수를 목표에 맞춰 리샘플링하고, 그 상대 길이를 가중치로 넘긴다.
    // 균등 분배하면 오마주의 핵심인 완급이 사라진다.
    homageScenes = resampleHomageScenes(homageStructure.scenes, desiredCount)
    sceneCount = homageScenes.length
    // 구도(누가/무엇이 등장하는지=subjectRefs) 참고용으로만 템플릿 풀을 빌린다 — 대사/설명
    // 텍스트는 여기서 가져오지 않는다(4번에서 homageScenes 기반으로 별도 파생한다)
    chosen = Array.from({ length: sceneCount }, (_, i) => pool[i % pool.length])
    durations = buildSceneDurations(durationSec, sceneCount, homageScenes.map(s => s.durationSec))
  } else {
    sceneCount = Math.min(desiredCount, pool.length)
    chosen = pool.slice(0, sceneCount)
    durations = buildSceneDurations(durationSec, chosen.length)
  }

  // 3. 프로젝트 특성(인원 구성 등)에 맞게 가공 및 스타일/배경/자연현상 프롬프트 데코레이터 적용
  // (표정은 씬마다 스토리·대사에 이미 자연스럽게 녹아 있어 전역 덧붙임을 없앴다 — 컨셉/씬별 내용과
  // 충돌하는 걸 방지)
  const styleModifier = getStylePromptModifier(styleId)
  const backgroundModifier = getBackgroundPromptModifier(backgroundId)
  const phenomenonModifier = getNaturalPhenomenonModifier(phenomenonId)

  // 4. 대사/설명/프롬프트 텍스트 — 기본값(폴백)을 먼저 채우고, Gemini 키가 있으면 같은 인물
  // 구성·전개를 유지한 채 매번 새로 창작한 텍스트로 교체를 시도한다.
  // 템플릿 모드는 실패하면(키 없음/네트워크 오류/응답 형식 불일치) 조용히 폴백 원문으로
  // 되돌아간다 — 파이프라인은 절대 깨지지 않는다(이 앱의 다른 AI 폴백들과 동일한 원칙).
  // ⚠️ 오마주 모드는 폴백 원문의 출처부터 다르다 — pool은 항상 DEFAULT_CONCEPT_TEMPLATE(로맨틱
  // 커플 대사)로 귀결되므로 그 텍스트를 쓰지 않고 homageScenes에서 중립적으로 파생시킨다. 게다가
  // 오마주 모드는 이 폴백이 최종 결과가 되는 일이 아예 없어야 한다 — Gemini가 실패하면 아래에서
  // 조용히 넘어가지 않고 명시적으로 예외를 던진다(이 폴백은 어디까지나 이중 방어선).
  let content: GeneratedStoryboardScene[] = homageScenes
    ? homageScenes.map(buildHomageFallbackScene)
    : chosen.map(tpl => ({
        descKo: tpl.descKo,
        dialogueKo: tpl.dialogueKo,
        keyframePromptEn: tpl.keyframePromptEn,
        motionPromptEn: tpl.motionPromptEn,
      }))

  // 광고 프로젝트(ad_* 구성)면 제품 분석 결과 + 4축 컨셉을 반영한 광고 각본 창작을 시도한다
  const adState = useAdStore.getState()
  const isAdProject = conceptId.startsWith('ad_') && !!adState.analysis

  const geminiKey = await KeyVault.getKey('gemini')

  // ⚠️ 오마주 모드는 애초에 레퍼런스 분석 단계(homageAnalyzer)에서 Gemini 키를 요구해야만
  // 진입할 수 있는 흐름이다 — 여기서 키를 요구하는 건 새로운 부담이 아니라 일관성이다. 여기서
  // 키가 없다는 건 호출 사이 어딘가에서 키가 지워졌다는 뜻이므로, 조용히 4번의 중립 폴백으로
  // 넘어가지 않고 사용자에게 명시적으로 알린다(Task 9 리뷰 Critical — 로맨틱 템플릿 유출 방지의
  // 정상 경로 쪽 방어선. 4번의 중립 폴백은 그래도 새는 경우를 무해하게 만드는 두 번째 방어선).
  if (isHomage && !geminiKey) {
    throw new Error('오마주 모드는 Gemini API 키가 있어야 각본을 만들 수 있어요. 설정에서 Gemini 키를 등록한 뒤 다시 시도하거나, 템플릿 모드로 전환해주세요.')
  }

  if (geminiKey) {
    // isValid가 false인 경우(형식 불일치)를 try 블록 밖에서 처리하기 위한 플래그 — try 안에서
    // 바로 throw하면 아래 catch가 그 예외까지 삼켜서 "조용히 템플릿으로 대체" 로그를 다시
    // 찍어버린다. try/catch가 완전히 끝난 뒤에 판단해야 원인별로 정확한 메시지를 유지할 수 있다.
    let homageResultInvalid = false
    try {
      const llmScenes = await withTimeout(
        isAdProject
          ? GeminiAdapter.generateAdStoryboardScenes(
              content,
              {
                productName: adState.analysis!.productName,
                description: adState.analysis!.description,
                keyFeatures: adState.analysis!.keyFeatures,
                narration: adState.analysis!.narration,
                callToAction: adState.analysis!.callToAction,
                emphasisKo: adState.adConcept.emphasis.map(id => AD_EMPHASIS_LABELS[id] || id),
                toneKo: AD_TONES.find(t => t.id === adState.adConcept.tone)?.label || '활기찬',
                visualStyleKo: AD_VISUAL_STYLES.find(v => v.id === adState.adConcept.visualStyle)?.label || '클린 브라이트',
                visualStyleEn: AD_VISUAL_STYLES.find(v => v.id === adState.adConcept.visualStyle)?.promptEn || '',
                structureLabel: isHomage
                  ? '레퍼런스 오마주'
                  : (AD_STRUCTURES.find(s => s.id === conceptId)?.label || conceptId),
                structureFlow: isHomage && homageStructure && homageScenes
                  ? buildHomageFlowText(homageStructure, homageScenes)
                  : (AD_STRUCTURES.find(s => s.id === conceptId)?.flow || ''),
                sceneCount,
                durationSec,
                hasModel: persons.length > 0,
                virtualActorKo: persons.length === 0 ? buildAiActorKo(adState.aiActor) : undefined,
                virtualActorEn: persons.length === 0 ? buildAiActorEn(adState.aiActor) : undefined,
                dialogueMode: project.dialogueMode,
              },
              geminiKey
            )
          : GeminiAdapter.generateStoryboardScenes(
              content,
              { relationKo: RELATION_KO[relation], dialogueMode: project.dialogueMode, sceneCount },
              geminiKey
            ),
        20000
      )
      const isValid = Array.isArray(llmScenes)
        && llmScenes.length === sceneCount
        && llmScenes.every(s => s.descKo?.trim() && s.keyframePromptEn?.trim() && s.motionPromptEn?.trim())
      if (isValid) {
        content = llmScenes
      } else if (isHomage) {
        homageResultInvalid = true
        console.warn('오마주 각본 생성 결과 형식이 예상과 달라요:', llmScenes)
      } else {
        console.warn('Gemini 응답 형식이 예상과 달라 템플릿으로 대체합니다:', llmScenes)
      }
    } catch (e) {
      if (isHomage) {
        console.error('오마주 스토리보드 생성 실패:', e)
        throw new Error('오마주 각본을 만들지 못했어요. 다시 시도하거나 템플릿 모드로 전환해주세요.')
      }
      console.warn('Gemini 스토리보드 생성 실패, 템플릿으로 대체합니다:', e)
    }
    if (homageResultInvalid) {
      throw new Error('오마주 각본 생성 결과가 올바르지 않았어요. 다시 시도하거나 템플릿 모드로 전환해주세요.')
    }
  }

  // (AdStudio) 대사 보증 — 창작 결과가 대사를 전부 비워뒀으면 광고 나레이션을 문장 단위로
  // 잘라 씬 순서대로 배분한다. "대사 없는 광고"가 되는 것을 방지하는 마지막 안전망.
  if (isAdProject && project.dialogueMode !== 'none' && adState.analysis) {
    const allEmpty = content.every(s => !s.dialogueKo?.trim())
    if (allEmpty) {
      const sentences = adState.analysis.narration
        .split(/(?<=[.!?。…])\s+|\n+/)
        .map(t => t.trim())
        .filter(Boolean)
      if (sentences.length > 0) {
        const per = Math.ceil(sentences.length / content.length)
        content = content.map((s, i) => ({
          ...s,
          dialogueKo: sentences.slice(i * per, (i + 1) * per).join(' '),
        }))
      }
    }

    // (AdStudio) 나레이션 언어 확정 — 여기서 못 박는 게 핵심이다.
    // 제품 자료가 영어면 AI가 영어 대사를 만들어내는데, 이를 렌더 시점 번역에만 맡기면
    // 그때 번역이 실패(키 없음·쿼터 소진)했을 때 이미 포인트를 쓴 뒤에 영어 음성이 나와버린다.
    // 스토리보드 단계에서 미리 맞춰두면 사용자가 화면에서 언어를 눈으로 확인하고 직접 고칠 수도 있다.
    const targetLocale = adState.config.narrationLocale
    const needsFix = content.some(s => {
      const line = (s.dialogueKo ?? '').trim()
      if (!line) return false
      return targetLocale === 'ko' ? !/[가-힣]/.test(line) : detectTextLocale(line) !== targetLocale
    })
    if (needsFix) {
      console.warn(`스토리보드 대사가 "${targetLocale}"가 아니어서 생성 단계에서 번역을 시도합니다.`)
      const fixed = await Promise.all(content.map(async s => {
        const line = (s.dialogueKo ?? '').trim()
        if (!line) return s
        const r = await translateSceneTextDetailed(line, targetLocale)
        return { ...s, dialogueKo: r.text }
      }))
      content = fixed
    }

    // (AdStudio) 대사 분량 상한 — 최종 안전망.
    // Gemini가 글자 예산 지시를 무시했거나 위 문장 분배가 예산을 넘겼을 때, 씬당 한도로 잘라
    // 영상 길이 안에 반드시 끝나게 한다. (한국어 나레이션 초당 약 4.5자, 안내·CTA 여유 0.85)
    const totalCharBudget = Math.round(durationSec * 4.5 * 0.85)
    const perSceneBudget = Math.max(8, Math.floor(totalCharBudget / content.length))
    content = content.map(s => {
      const line = (s.dialogueKo ?? '').trim()
      if (line.length <= perSceneBudget) return s
      // 한도 안에서 마지막 문장부호나 공백에서 자연스럽게 끊는다 (단어 중간 절단 방지)
      const clipped = line.slice(0, perSceneBudget)
      const cut = Math.max(clipped.lastIndexOf(' '), clipped.search(/[.!?。…][^.!?。…]*$/) + 1)
      return { ...s, dialogueKo: (cut > perSceneBudget * 0.6 ? clipped.slice(0, cut) : clipped).trim() }
    })
  }

  // 광고 톤&무드 데코레이터 — 광고 프로젝트일 때만 키프레임 프롬프트에 덧붙는다
  const adToneModifier = isAdProject
    ? (AD_TONES.find(t => t.id === adState.adConcept.tone)?.promptEn || '')
    : ''
  // 비주얼 스타일(룩) — 조명·질감의 실제 방향을 정한다. 밝기를 규칙으로 강제하는 대신
  // 사용자가 고른 이 값이 룩을 결정하고, 가독성(AD_CLARITY_BASE)만 공통으로 보장한다.
  const adStyleModifier = isAdProject
    ? (AD_VISUAL_STYLES.find(v => v.id === adState.adConcept.visualStyle)?.promptEn || '')
    : ''
  // AI 가상 배우(사진 없음) 프로필 — 인물이 등장하는 씬의 프롬프트에만 덧붙는다
  // (Gemini 창작이 성공하면 이미 프롬프트에 녹아 있지만, 템플릿 폴백 시에도 프로필이 반영되도록 이중 보강)
  const adActorModifier = isAdProject && persons.length === 0
    ? buildAiActorEn(adState.aiActor)
    : ''

  return chosen.map((tpl, i) => {
    // 인물 지정 (relation이 solo인 경우 person_2가 있더라도 person_1로 교체) — 구도는 창작 영역이
    // 아니라 항상 템플릿 원본 기준을 따른다. 광고 템플릿의 제품 단독 컷(subjectRefs 빈 배열)은
    // 인물을 강제로 넣지 않는다.
    let subjects = [...tpl.subjectRefs]
    if (relation === 'solo') {
      subjects = tpl.subjectRefs.length > 0 ? ['person_1'] : []
    } else if (subjects.length > 1 && persons.length > subjects.length) {
      // 템플릿은 "여러 명이 함께" 나오는 그룹 씬으로 설계됐는데(subjectRefs.length > 1) 실제
      // 선택 인원이 템플릿 가정(2명)보다 많으면(가족 3~4명, 친구 3~6명 등) 전원을 반영한다 —
      // 안 그러면 person_3 이후로 선택한 배우는 어떤 씬에도 영원히 등장하지 못한다
      subjects = persons.map(p => p.label)
    }

    // 영문 비주얼 프롬프트를 정교하게 재조합 (배경/자연현상/광고톤은 선택 안 했으면(빈 문자열) 그냥 생략)
    // AI 가상 배우 프로필은 인물이 등장하는 씬에만 덧붙인다 (제품 단독 컷에 사람이 생기는 것 방지)
    const finalPrompt = [
      content[i].keyframePromptEn,
      styleModifier,
      backgroundModifier,
      phenomenonModifier,
      adToneModifier,
      adStyleModifier,
      subjects.length > 0 ? adActorModifier : '',
      // 광고는 피사체가 또렷이 읽혀야 목적(부각)을 달성한다 — 밝기가 아니라 "가독성"만 공통으로 건다
      isAdProject ? AD_CLARITY_BASE : '',
    ]
      .filter(Boolean)
      .join(', ')

    return {
      id: crypto.randomUUID(),
      seq: i + 1,
      duration: durations[i],
      descKo: content[i].descKo,
      keyframePromptEn: finalPrompt,
      originalKeyframePromptEn: finalPrompt,
      motionPromptEn: content[i].motionPromptEn,
      dialogueKo: project.dialogueMode === 'none' ? undefined : content[i].dialogueKo,
      subjectRefs: subjects,
      status: 'pending',
      regenCount: 0,
      gateResults: []
    }
  })
}
