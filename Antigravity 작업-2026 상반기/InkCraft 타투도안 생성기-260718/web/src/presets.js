// InkCraft AI — 타투 스타일 프리셋 (UI 표시용)
// id는 서버(server/, functions/)의 STYLE_PROMPTS 키와 일치해야 함.
export const STYLES = [
  {
    id: 'oldschool',
    emoji: '⚓',
    label: 'Old School',
    tag: 'American Traditional',
    desc: 'Bold outlines, vintage sailor flash',
  },
  {
    id: 'fineline',
    emoji: '🪶',
    label: 'Fine Line',
    tag: 'Single Needle',
    desc: 'Delicate thin lines, subtle shading',
  },
  {
    id: 'minimal',
    emoji: '◦',
    label: 'Minimal',
    tag: 'Simple & Iconic',
    desc: 'Clean lines, negative space',
  },
  {
    id: 'geometric',
    emoji: '◇',
    label: 'Geometric',
    tag: 'Sacred Geometry',
    desc: 'Symmetric shapes, dotwork mandala',
  },
  {
    id: 'tribal',
    emoji: '🌀',
    label: 'Tribal',
    tag: 'Blackwork',
    desc: 'Solid black polynesian patterns',
  },
  {
    id: 'irezumi',
    emoji: '🐉',
    label: 'Irezumi',
    tag: 'Japanese',
    desc: 'Waves, clouds, black & grey',
  },
  {
    id: 'realism',
    emoji: '🖤',
    label: 'Realism',
    tag: 'Photorealistic',
    desc: 'Lifelike soft shading',
  },
  {
    id: 'neotrad',
    emoji: '🌹',
    label: 'Neo-Trad',
    tag: 'Neo-Traditional',
    desc: 'Bold lines, ornate details',
  },
  {
    id: 'watercolor',
    emoji: '💧',
    label: 'Watercolor',
    tag: 'Paint Splash',
    desc: 'Flowing washes, no outlines',
  },
  {
    id: 'anime',
    emoji: '⛩️',
    label: 'Anime',
    tag: 'Manga / Cel',
    desc: 'Clean cel-shaded linework',
  },
  {
    id: 'trashpolka',
    emoji: '🔴',
    label: 'Trash Polka',
    tag: 'Black & Red',
    desc: 'Realism × abstract chaos',
  },
  {
    id: 'sketch',
    emoji: '✏️',
    label: 'Sketch',
    tag: 'Pencil Art',
    desc: 'Loose expressive strokes',
  },
  {
    id: 'dotwork',
    emoji: '🔘',
    label: 'Dotwork',
    tag: 'Stippling',
    desc: 'Dot-density shading',
  },
  {
    id: 'celtic',
    emoji: '🪢',
    label: 'Celtic',
    tag: 'Nordic Knots',
    desc: 'Interwoven knotwork',
  },
];

// 잉크 대구분 — id는 서버/functions의 color 파라미터 값과 일치해야 함.
export const COLOR_MODES = [
  { id: 'bw',    emoji: '⬛', label: 'Black & Grey', desc: '흑백 잉크' },
  { id: 'color', emoji: '🎨', label: 'Color',        desc: '컬러 잉크' },
];

// 시착 스튜디오 부위 프리셋 — id는 서버/functions의 BODY_PART_HINTS 키와 일치해야 함.
export const BODY_PARTS = [
  { id: 'arm',   emoji: '💪', label: 'Arm',        ko: '팔' },
  { id: 'leg',   emoji: '🦵', label: 'Leg',        ko: '다리' },
  { id: 'upper', emoji: '🫸', label: 'Upper body', ko: '상체' },
  { id: 'full',  emoji: '🧍', label: 'Full body',  ko: '온몸' },
];

// AI 가상 모델 — 각도(id는 서버 MODEL_ANGLE_HINTS 키), 부위(id는 MODEL_PART_LABELS 키)
export const MODEL_ANGLES = [
  { id: 0, label: 'Front' },
  { id: 1, label: 'Front-R' },
  { id: 2, label: 'Right' },
  { id: 3, label: 'Back-R' },
  { id: 4, label: 'Back' },
  { id: 5, label: 'Back-L' },
  { id: 6, label: 'Left' },
  { id: 7, label: 'Front-L' },
];
export const MODEL_PARTS = [
  { id: 'leftarm',  emoji: '💪', label: 'Left arm',  ko: '왼팔' },
  { id: 'rightarm', emoji: '💪', label: 'Right arm', ko: '오른팔' },
  { id: 'chest',    emoji: '🫀', label: 'Chest',     ko: '가슴' },
  { id: 'back',     emoji: '🔙', label: 'Back',      ko: '등' },
  { id: 'leftleg',  emoji: '🦵', label: 'Left leg',  ko: '왼다리' },
  { id: 'rightleg', emoji: '🦵', label: 'Right leg', ko: '오른다리' },
];
export const MODEL_GENDERS = [
  { id: 'female', emoji: '👩', label: 'Female model' },
  { id: 'male',   emoji: '👨', label: 'Male model' },
];

// 소재 입력이 비어있을 때 보여줄 영감 예시
export const SUBJECT_SEEDS = [
  'a snake coiled around a dagger',
  'a phoenix rising from flames',
  'a wolf howling at a crescent moon',
  'a rose with falling petals',
  'a koi fish swimming upstream',
  'an anchor with a compass rose',
  'a skull with butterfly wings',
  'a tiger face front view',
  'a lotus flower above rippling water',
  'an hourglass with wings',
];
