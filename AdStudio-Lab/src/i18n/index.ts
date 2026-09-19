import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

const resources = {
  ko: {
    translation: {
      // 공통
      app_name: 'AdStudio',
      tagline: '사진이 영화가 되는 순간',
      tagline2: '내 사진 속 주인공을\n영화·드라마·뮤직비디오로',
      free: '무료',
      pro: 'Pro',
      start: '시작하기',
      next: '다음',
      back: '이전',
      cancel: '취소',
      confirm: '확인',
      save: '저장',
      delete: '삭제',
      loading: '로딩 중...',
      retry: '다시 시도',
      done: '완료',
      error: '오류가 발생했어요',
      share: '공유',
      download: '다운로드',
      upgrade: '업그레이드',

      // 내비게이션
      nav_home: '홈',
      nav_projects: '내 작업',
      nav_create: '만들기',
      nav_keys: 'API 키',
      nav_profile: '프로필',

      // S1 홈
      home_hero_title: '내 사진을\n{{style}}처럼',
      home_hero_subtitle: '업로드한 사진의 인물이 주인공인\n5~30초 오마주 영상을 자동 생성해드려요.',
      home_start_cta: '지금 만들기',
      home_byok_banner: '내 API 키로, 내 비용으로, 무제한 생성',
      home_byok_sub: 'BYOK — 키는 내 브라우저에만 저장',
      home_my_projects: '내 작업',
      home_no_projects: '아직 만든 영상이 없어요\n첫 번째 오마주를 만들어볼까요?',
      home_plan_free: '무료 플랜',
      home_plan_pro: 'Pro 플랜',
      home_plan_free_desc: '무빙포토 · 알리바바 무료 쿼터',
      home_plan_pro_desc: '고퀄 레인 · 배치 생성',
      home_plan_price: '$9.99/월 또는 $59 평생',

      // S2 업로드
      upload_title: '사진 업로드',
      upload_subtitle: '주인공이 잘 보이는 사진을 올려주세요',
      upload_hint: '사진을 탭하거나 여기로 끌어다 놓으세요\nJPG · PNG · HEIC / 최대 4장',
      upload_face_title: '얼굴 감지',
      upload_face_hint: '인물을 감지하고 있어요...',
      upload_relation_title: '관계를 선택해주세요',
      relation_solo: '나 혼자',
      relation_couple: '연인',
      relation_married: '부부',
      relation_family: '가족',
      relation_siblings: '남매·자매',
      relation_friends: '친구',
      consent_title: '이용 동의',
      consent_1: '업로드한 사진 속 모든 인물의 동의를 받았거나, 본인입니다.',
      consent_2: '유명인·미성년 단독·성적 콘텐츠 제작에 사용하지 않겠습니다.',
      consent_biometric: '얼굴 특징은 품질 검사에만 일시 사용되며, 저장하지 않습니다.',

      // S3 컨셉
      concept_title: '컨셉 선택',
      concept_subtitle: '어떤 분위기로 만들까요?',
      genre_film: '영화',
      genre_drama: '드라마',
      genre_mv: '뮤직비디오',
      genre_animation: '애니메이션',
      genre_ad: '광고·화보',
      style_title: '스타일',
      duration_title: '길이',
      duration_sec: '{{n}}초',
      dialogue_title: '대사 방식',
      dialogue_auto: '자동 생성',
      dialogue_manual: '직접 입력',
      dialogue_none: '대사 없음',
      concept_create: '스토리보드 만들기',

      // S4 스토리보드
      storyboard_title: '스토리보드',
      storyboard_subtitle: '씬을 편집하고 제작 방식을 선택하세요',
      scene_n: '{{n}}번 씬',
      scene_duration: '{{n}}초',
      scene_regen: '키프레임 재생성',
      lane_title: '제작 방식',
      lane_moving: '무빙포토',
      lane_moving_desc: '무료 · 즉시 · 사진이 살아 움직여요',
      lane_ai: 'AI 영상',
      lane_ai_desc: '무료 · 대기열 · 진짜 AI 영상',
      lane_premium: '고퀄 영상',
      lane_premium_desc: '유료 키 · 즉시 · 1080p',
      render_start: '제작 시작',
      cost_estimate: '예상 비용: ~${{cost}}',
      gate_pass: '통과',
      gate_warn: '경고',
      gate_fail: '수정 필요',
      gate_blocked: '차단됨',

      // S5 진행
      progress_title: '제작 중이에요',
      progress_queue: '대기열 {{n}}번째',
      progress_eta: '예상 완료: {{time}}',
      progress_notify: '완료되면 알려드려요',
      scene_pending: '대기 중',
      scene_generating: '생성 중',
      scene_done: '완료',
      scene_failed: '실패',

      // S6 결과
      result_title: '완성됐어요! 🎬',
      result_subtitle: '오마주 영상이 완성됐어요',
      result_ai_notice: 'AI가 생성한 영상입니다',
      result_download: '다운로드',
      result_share_link: '링크 공유',
      result_reedit: '다시 편집',
      result_upgrade_ai: 'AI 영상으로 업그레이드',
      result_upgrade_hq: '고퀄 영상으로 업그레이드',

      // BYOK 키 설정
      keys_title: 'API 키 설정',
      keys_subtitle: '키는 내 브라우저에만 저장돼요 — 서버로 전송되지 않아요',
      keys_security_note: '🔒 이 브라우저에만 저장, 서버 전송 없음',
      keys_alibaba: '알리바바 (무료 쿼터)',
      keys_alibaba_desc: '무료 AI 영상 레인 · 1,650초 무료 쿼터',
      keys_seedance: 'Seedance 2.0',
      // fast 리소스팩 단가 $3.30/M 토큰 기준, 앱이 실제로 호출하는 사양(720p·5초·오디오 없음)
      // = 약 103K 토큰 → $0.34/씬 (6초는 $0.41, 480p로 낮추면 $0.16).
      // 이전 표기 '$0.11/씬'은 실제와 3배 차이라 정정했다.
      keys_seedance_desc: '일반 씬 · 720p · ~$0.34/씬',
      keys_hailuo: 'Hailuo 2.3',
      // 앱이 호출하는 사양(표준 MiniMax-Hailuo-2.3 · 768P·6초) 공식 단가 = $0.28/영상
      keys_hailuo_desc: '동작·애니 씬 · ~$0.28/씬',
      keys_kling: 'Kling 3.0',
      // 공식 단가 기준 실제 호출 사양(std 720p·5초) = $0.42/씬 (1 Unit=$0.14 × 0.6 Unit/초 × 5초)
      keys_kling_desc: '인물 클로즈업 씬 · 720p · ~$0.42/씬',
      keys_veo: 'Veo 3.1',
      // 공식 단가 기준 실제 호출 사양(Veo 3.1 Fast · 720p·6초) = $0.10/초 × 6 = $0.60/씬.
      // 무료 등급에는 Veo 쿼터가 없어 결제 계정 연결이 필수다.
      keys_veo_desc: '대사·오디오 씬 · 720p · ~$0.60/씬 (결제 계정 필수)',
      keys_validate: '키 확인',
      keys_valid: '유효',
      keys_invalid: '유효하지 않음',
      keys_guide: '발급 가이드',
      quota_remaining: '잔여 약 {{n}}초',
      quota_expiry: '만료 D-{{n}}',
      quota_tooltip: '추정치입니다. 정확한 값은 제공자 콘솔에서 확인하세요',

      // 공통 오류
      err_no_face: '얼굴을 찾을 수 없어요. 인물이 잘 보이는 사진을 사용해주세요.',
      err_too_many: '사진은 최대 4장까지 업로드할 수 있어요',
      err_file_type: 'JPG, PNG, HEIC 파일만 지원해요',
      err_key_missing: '{{provider}} API 키가 필요해요',
      err_key_invalid: '키가 유효하지 않아요. 다시 확인해주세요.',
      err_quota_exceeded: '무료 쿼터가 모두 사용됐어요',
    }
  },
  en: {
    translation: {
      // common
      app_name: 'AdStudio',
      tagline: 'When photos become movies',
      tagline2: 'Turn your photo into a\nmovie, drama, or music video',
      free: 'Free',
      pro: 'Pro',
      start: 'Get Started',
      next: 'Next',
      back: 'Back',
      cancel: 'Cancel',
      confirm: 'Confirm',
      save: 'Save',
      delete: 'Delete',
      loading: 'Loading...',
      retry: 'Retry',
      done: 'Done',
      error: 'Something went wrong',
      share: 'Share',
      download: 'Download',
      upgrade: 'Upgrade',

      // navigation
      nav_home: 'Home',
      nav_projects: 'Projects',
      nav_create: 'Create',
      nav_keys: 'API Keys',
      nav_profile: 'Profile',

      // S1 Home
      home_hero_title: 'Your photo,\nas {{style}}',
      home_hero_subtitle: 'Auto-generate a 5~30s hommage video\nwith your photo\'s subject as the star.',
      home_start_cta: 'Create Now',
      home_byok_banner: 'Unlimited creation with your own API key',
      home_byok_sub: 'BYOK — keys stored in your browser only',
      home_my_projects: 'My Projects',
      home_no_projects: 'No videos yet\nCreate your first hommage!',
      home_plan_free: 'Free',
      home_plan_pro: 'Pro',
      home_plan_free_desc: 'Moving Photo · Alibaba free quota',
      home_plan_pro_desc: 'HQ lanes · Batch',
      home_plan_price: '$9.99/mo or $59 lifetime',

      // S2 Upload
      upload_title: 'Upload Photos',
      upload_subtitle: 'Use clear photos showing the subject\'s face',
      upload_hint: 'Tap or drag photos here\nJPG · PNG · HEIC / up to 4 photos',
      upload_face_title: 'Face Detection',
      upload_face_hint: 'Detecting faces...',
      upload_relation_title: 'Select relationship',
      relation_solo: 'Solo',
      relation_couple: 'Couple',
      relation_married: 'Married',
      relation_family: 'Family',
      relation_siblings: 'Siblings',
      relation_friends: 'Friends',
      consent_title: 'Consent',
      consent_1: 'I confirm all people in the photos have consented, or this is me.',
      consent_2: 'I will not use this for celebrities, minors, or inappropriate content.',
      consent_biometric: 'Face features are used temporarily for quality checks only and are never stored.',

      // S3 Concept
      concept_title: 'Choose Concept',
      concept_subtitle: 'What vibe are you going for?',
      genre_film: 'Film',
      genre_drama: 'Drama',
      genre_mv: 'Music Video',
      genre_animation: 'Animation',
      genre_ad: 'Ad / Editorial',
      style_title: 'Style',
      duration_title: 'Duration',
      duration_sec: '{{n}}s',
      dialogue_title: 'Dialogue',
      dialogue_auto: 'Auto-generate',
      dialogue_manual: 'Write my own',
      dialogue_none: 'No dialogue',
      concept_create: 'Build Storyboard',

      // S4 Storyboard
      storyboard_title: 'Storyboard',
      storyboard_subtitle: 'Edit scenes and choose your production lane',
      scene_n: 'Scene {{n}}',
      scene_duration: '{{n}}s',
      scene_regen: 'Regenerate',
      lane_title: 'Production Lane',
      lane_moving: 'Moving Photo',
      lane_moving_desc: 'Free · Instant · Parallax motion',
      lane_ai: 'AI Video',
      lane_ai_desc: 'Free · Queue · Real AI video',
      lane_premium: 'HQ Video',
      lane_premium_desc: 'Paid key · Instant · 1080p',
      render_start: 'Start Production',
      cost_estimate: 'Est. cost: ~${{cost}}',
      gate_pass: 'Pass',
      gate_warn: 'Warning',
      gate_fail: 'Fix needed',
      gate_blocked: 'Blocked',

      // S5 Progress
      progress_title: 'Creating your video...',
      progress_queue: 'Queue position: #{{n}}',
      progress_eta: 'Est. completion: {{time}}',
      progress_notify: "We'll notify you when done",
      scene_pending: 'Pending',
      scene_generating: 'Generating',
      scene_done: 'Done',
      scene_failed: 'Failed',

      // S6 Result
      result_title: 'It\'s ready! 🎬',
      result_subtitle: 'Your hommage video is complete',
      result_ai_notice: 'AI-generated content',
      result_download: 'Download',
      result_share_link: 'Share Link',
      result_reedit: 'Edit Again',
      result_upgrade_ai: 'Upgrade to AI Video',
      result_upgrade_hq: 'Upgrade to HQ Video',

      // BYOK Key Settings
      keys_title: 'API Key Settings',
      keys_subtitle: 'Keys are stored in your browser only — never sent to servers',
      keys_security_note: '🔒 Stored locally, never transmitted',
      keys_alibaba: 'Alibaba (Free quota)',
      keys_alibaba_desc: 'Free AI video lane · 1,650s free quota',
      keys_seedance: 'Seedance 2.0',
      keys_seedance_desc: 'General scenes · 720p · ~$0.34/scene',
      keys_hailuo: 'Hailuo 2.3',
      keys_hailuo_desc: 'Motion/animation scenes · ~$0.28/scene',
      keys_kling: 'Kling 3.0',
      keys_kling_desc: 'Close-up/portrait scenes · 720p · ~$0.42/scene',
      keys_veo: 'Veo 3.1',
      keys_veo_desc: 'Dialogue/audio scenes · 720p · ~$0.60/scene (billing account required)',
      keys_validate: 'Validate Key',
      keys_valid: 'Valid',
      keys_invalid: 'Invalid',
      keys_guide: 'Setup Guide',
      quota_remaining: '~{{n}}s remaining',
      quota_expiry: 'Expires in {{n}} days',
      quota_tooltip: 'Estimated. Check your provider console for exact usage.',

      // errors
      err_no_face: 'No face detected. Please use a clear photo with a visible face.',
      err_too_many: 'You can upload up to 4 photos',
      err_file_type: 'Only JPG, PNG, HEIC files are supported',
      err_key_missing: '{{provider}} API key required',
      err_key_invalid: 'Invalid key. Please check and try again.',
      err_quota_exceeded: 'Free quota exhausted',
    }
  }
}

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: navigator.language.startsWith('ko') ? 'ko' : 'en',
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
  })

export default i18n
