'use client';

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import { FREE_GENERATIONS, MODES, ROOM_TYPES, STYLES } from '@/lib/constants';
import { useLocalStorage } from '@/lib/useLocalStorage';
import { useAuth } from '@/lib/useAuth';
import { firebaseAuth, signInWithGoogle } from '@/lib/firebase/client';
import CompareSlider from './CompareSlider';
import Reveal from './Reveal';

const LOADING_STATUSES: Record<string, string[]> = {
  default: [
    'Analyzing the room structure...',
    'Placing furniture and decor...',
    'Tuning lighting and colors...',
    'Rendering the final image...',
  ],
  declutter: [
    'Analyzing the room structure...',
    'Removing furniture and clutter...',
    'Reconstructing floors and walls...',
    'Rendering the final image...',
  ],
  twilight: [
    'Analyzing the exterior...',
    'Painting the evening sky...',
    'Lighting up the windows...',
    'Rendering the final image...',
  ],
  renovation: [
    'Analyzing the room structure...',
    'Replacing floors and finishes...',
    'Installing new fixtures...',
    'Rendering the final image...',
  ],
  curb_appeal: [
    'Analyzing the exterior...',
    'Refreshing the landscaping...',
    'Tidying up the facade...',
    'Rendering the final image...',
  ],
};

const RESULT_BADGES: Record<string, string> = {
  redesign: 'Redesign Complete',
  staging: 'Staging Complete',
  declutter: 'Room Emptied',
  twilight: 'Twilight Ready',
  renovation: 'Renovation Ready',
  curb_appeal: 'Curb Appeal Boosted',
};

const GENERATE_LABELS: Record<string, string> = {
  redesign: 'Generate my design',
  staging: 'Stage this room',
  declutter: 'Empty this room',
  twilight: 'Create twilight shot',
  renovation: 'Preview the renovation',
  curb_appeal: 'Boost curb appeal',
};

const UPLOAD_LABELS: Record<string, string> = {
  redesign: 'Upload your room photo',
  staging: 'Upload the empty room',
  declutter: 'Upload the occupied room',
  twilight: 'Upload the daytime exterior',
  renovation: 'Upload the room to renovate',
  curb_appeal: 'Upload the exterior photo',
};

/** Tips panel shown when a mode needs neither room type nor style. */
const MODE_TIPS: Record<string, { title: string; items: string[] }> = {
  twilight: {
    title: 'Tips for a great twilight shot',
    items: [
      'Shoot from the street or driveway with the whole facade in frame',
      'Daytime photos with a visible sky convert best',
      'Windows in the shot will glow with warm interior light',
      'No style or room selection needed — just upload and generate',
    ],
  },
  curb_appeal: {
    title: 'Tips for a great curb appeal shot',
    items: [
      'Capture the whole front of the property, lawn included',
      'The lawn gets mowed, hedges trimmed and flower beds refreshed',
      'Stains, clutter and gray skies are cleaned up automatically',
      'No style or room selection needed — just upload and generate',
    ],
  },
};

export default function Studio() {
  // Input state
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState(MODES[0].id);
  const [selectedRoom, setSelectedRoom] = useState(ROOM_TYPES[0].id);
  const [selectedStyle, setSelectedStyle] = useState(STYLES[0].id);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Anonymous free trial counter (synced with localStorage)
  const [freeCountRaw, setFreeCountRaw] = useLocalStorage(
    'reroom_free_generations',
    String(FREE_GENERATIONS)
  );
  const freeCount = Number(freeCountRaw);

  // Account state (no-op when Firebase env vars are absent)
  const { enabled: authEnabled, user, credits, refreshCredits } = useAuth();

  // Generation state
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [generationTime, setGenerationTime] = useState<number | null>(null);
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Share state
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [isSharing, setIsSharing] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);

  useEffect(() => {
    // Style pre-selected from a gallery card
    const onPickStyle = (e: Event) => {
      const styleId = (e as CustomEvent<string>).detail;
      if (STYLES.some((s) => s.id === styleId)) {
        setSelectedStyle(styleId);
        setResultImage(null);
      }
    };
    window.addEventListener('reroom:style', onPickStyle);
    return () => window.removeEventListener('reroom:style', onPickStyle);
  }, []);

  // Upload preprocessing — downscale longest side to 1024px via canvas
  const handleImageFile = (file: File) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setErrorMsg('Please upload an image file (JPG, PNG or WebP).');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setErrorMsg('Files must be under 10MB.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new window.Image();
      img.onload = () => {
        const maxDim = 1024;
        let { width, height } = img;
        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.drawImage(img, 0, 0, width, height);
          setUploadedImage(canvas.toDataURL('image/jpeg', 0.85));
          setResultImage(null);
          setShareUrl(null);
          setErrorMsg(null);
        }
      };
      img.src = e.target?.result as string;
    };
    reader.readAsDataURL(file);
  };

  const handleGenerate = async () => {
    if (!uploadedImage) {
      setErrorMsg('Please upload a photo of your room first.');
      return;
    }

    const signedIn = Boolean(user);
    if (!signedIn && freeCount <= 0) {
      setErrorMsg(
        authEnabled
          ? `You've used all ${FREE_GENERATIONS} free tries. Sign in with Google to get free credits, or grab a credit pack below.`
          : `You've used all ${FREE_GENERATIONS} free tries. Check the pricing section for credit packs.`
      );
      return;
    }
    if (signedIn && credits !== null && credits < 1) {
      setErrorMsg("You're out of credits — credit packs start at $9 in the pricing section below.");
      return;
    }

    setIsLoading(true);
    setErrorMsg(null);
    setResultImage(null);
    setShareUrl(null);
    setLoadingStep(0);

    const statusCount = (LOADING_STATUSES[selectedMode] ?? LOADING_STATUSES.default).length;
    const interval = setInterval(() => {
      setLoadingStep((prev) => (prev + 1) % statusCount);
    }, 2500);
    const startTime = Date.now();

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const currentUser = firebaseAuth()?.currentUser;
      if (currentUser) {
        headers.Authorization = `Bearer ${await currentUser.getIdToken()}`;
      }

      const res = await fetch('/api/generate', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          image: uploadedImage,
          modeId: selectedMode,
          roomTypeId: selectedRoom,
          styleId: selectedStyle,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Generation failed.');
      }

      setResultImage(`data:image/png;base64,${data.image}`);
      setGenerationTime(Number(((Date.now() - startTime) / 1000).toFixed(1)));

      if (currentUser) {
        void refreshCredits();
      } else {
        setFreeCountRaw(String(Math.max(0, freeCount - 1)));
      }
    } catch (err) {
      console.error(err);
      setErrorMsg(
        err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      );
    } finally {
      clearInterval(interval);
      setIsLoading(false);
    }
  };

  const handleDownload = () => {
    if (!resultImage) return;
    const link = document.createElement('a');
    link.href = resultImage;
    link.download = `reroom_${selectedMode}_${selectedRoom}_${selectedStyle}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleShare = async () => {
    if (!resultImage || !uploadedImage) return;

    const currentUser = firebaseAuth()?.currentUser;
    if (!currentUser) {
      await signInWithGoogle();
      return;
    }

    // Copy an existing link instead of re-uploading
    if (shareUrl) {
      await navigator.clipboard.writeText(`${window.location.origin}${shareUrl}`);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
      return;
    }

    setIsSharing(true);
    try {
      const token = await currentUser.getIdToken();
      const res = await fetch('/api/share', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          before: uploadedImage,
          after: resultImage,
          modeId: selectedMode,
          roomTypeId: selectedRoom,
          styleId: selectedStyle,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not create a share link.');

      setShareUrl(data.url);
      await navigator.clipboard.writeText(`${window.location.origin}${data.url}`);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Could not create a share link.');
    } finally {
      setIsSharing(false);
    }
  };

  const resetResult = () => {
    setResultImage(null);
    setGenerationTime(null);
    setShareUrl(null);
  };

  const resetAll = () => {
    setUploadedImage(null);
    setResultImage(null);
    setGenerationTime(null);
    setShareUrl(null);
    setErrorMsg(null);
  };

  const mode = MODES.find((m) => m.id === selectedMode) ?? MODES[0];
  const loadingStatuses = LOADING_STATUSES[mode.id] ?? LOADING_STATUSES.default;
  // Step numbers shift when a mode hides the room/style pickers
  const roomStepNo = '03';
  const styleStepNo = mode.needsRoomType ? '04' : '03';
  const usageBadge = user
    ? credits !== null
      ? `${credits} credit${credits === 1 ? '' : 's'} left`
      : 'Signed in'
    : `${freeCount} of ${FREE_GENERATIONS} free tries left`;

  return (
    <section id="studio" className="w-full scroll-mt-16 border-t border-line">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-clay">
                Studio
              </p>
              <h2 className="font-display mt-3 text-3xl font-bold tracking-tight text-ink md:text-4xl">
                Your design studio
              </h2>
            </div>
            <span className="rounded-full border border-line bg-paper-raised px-4 py-2 text-xs font-semibold text-ink-soft">
              {usageBadge}
            </span>
          </div>
        </Reveal>

        <Reveal delay={100} className="mt-10">
          <div className="rounded-3xl border border-line bg-paper-raised p-6 shadow-lift md:p-10">
            {resultImage && uploadedImage ? (
              /* ── Result ── */
              <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-8 animate-fade-in">
                <div className="text-center">
                  <span className="rounded-full bg-clay px-4 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] text-paper">
                    {RESULT_BADGES[mode.id] ?? 'Complete'}
                  </span>
                  <h3 className="font-display mt-4 text-2xl font-bold text-ink">
                    Your new space is ready
                  </h3>
                  <p className="mt-1.5 text-xs text-ink-faint">
                    {mode.needsStyle
                      ? `${STYLES.find((s) => s.id === selectedStyle)?.label} style`
                      : mode.label}{' '}
                    · generated in {generationTime}s
                  </p>
                </div>

                <CompareSlider
                  beforeSrc={uploadedImage}
                  afterSrc={resultImage}
                  beforeAlt="Original room"
                  afterAlt="Redesigned room"
                />

                <div className="flex w-full flex-wrap justify-center gap-3">
                  <button
                    onClick={handleDownload}
                    className="cursor-pointer rounded-full bg-ink px-8 py-3.5 text-sm font-semibold text-paper shadow-lift transition-all duration-200 hover:bg-clay active:scale-95"
                  >
                    Download PNG
                  </button>
                  {authEnabled && (
                    <button
                      onClick={() => void handleShare()}
                      disabled={isSharing}
                      className="cursor-pointer rounded-full border border-clay bg-clay-soft px-8 py-3.5 text-sm font-semibold text-clay-deep transition-all duration-200 hover:border-ink active:scale-95 disabled:cursor-wait disabled:opacity-60"
                    >
                      {isSharing
                        ? 'Creating link...'
                        : shareCopied
                          ? 'Link copied!'
                          : user
                            ? 'Copy share link'
                            : 'Sign in to share'}
                    </button>
                  )}
                  <button
                    onClick={resetResult}
                    className="cursor-pointer rounded-full border border-line-strong bg-paper-raised px-8 py-3.5 text-sm font-semibold text-ink transition-all duration-200 hover:border-ink active:scale-95"
                  >
                    Try another style
                  </button>
                  <button
                    onClick={resetAll}
                    className="cursor-pointer rounded-full px-6 py-3.5 text-sm font-semibold text-ink-soft transition-colors hover:text-ink"
                  >
                    Upload a new photo
                  </button>
                </div>
              </div>
            ) : (
              /* ── Input ── */
              <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:gap-12">
                {/* 00. Mode */}
                <div className="flex flex-col gap-3 lg:col-span-2">
                  <label className="flex items-baseline gap-2 text-base font-bold text-ink">
                    <span className="font-display text-sm text-clay">01</span>
                    What are we doing today?
                  </label>
                  <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                    {MODES.map((mode) => (
                      <button
                        key={mode.id}
                        onClick={() => {
                          setSelectedMode(mode.id);
                          setErrorMsg(null);
                        }}
                        className={`flex cursor-pointer flex-col items-start gap-1 rounded-xl border p-4 text-left transition-all duration-200 ${
                          selectedMode === mode.id
                            ? 'border-clay bg-clay-soft shadow-lift'
                            : 'border-line bg-paper hover:border-line-strong'
                        }`}
                      >
                        <span className="flex items-center gap-2 text-sm font-bold text-ink">
                          {mode.label}
                          {mode.badge && (
                            <span className="rounded-full bg-clay px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-paper">
                              {mode.badge}
                            </span>
                          )}
                        </span>
                        <span className="text-xs text-ink-soft">{mode.desc}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 02. Upload */}
                <div className="flex flex-col gap-3">
                  <label className="flex items-baseline gap-2 text-base font-bold text-ink">
                    <span className="font-display text-sm text-clay">02</span>
                    {UPLOAD_LABELS[mode.id] ?? 'Upload your photo'}
                  </label>

                  {!uploadedImage ? (
                    <div
                      role="button"
                      tabIndex={0}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setIsDragOver(true);
                      }}
                      onDragLeave={() => setIsDragOver(false)}
                      onDrop={(e) => {
                        e.preventDefault();
                        setIsDragOver(false);
                        if (e.dataTransfer.files?.[0]) handleImageFile(e.dataTransfer.files[0]);
                      }}
                      onClick={() => fileInputRef.current?.click()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          fileInputRef.current?.click();
                        }
                      }}
                      className={`flex aspect-[4/3] cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed p-8 text-center transition-all duration-300 ${
                        isDragOver
                          ? 'scale-[0.99] border-clay bg-clay-soft'
                          : 'border-line-strong bg-paper hover:border-ink-faint'
                      }`}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        className="hidden"
                        accept="image/png, image/jpeg, image/webp"
                        onChange={(e) => {
                          if (e.target.files?.[0]) handleImageFile(e.target.files[0]);
                          e.target.value = '';
                        }}
                      />
                      <svg
                        width="36"
                        height="36"
                        viewBox="0 0 24 24"
                        fill="none"
                        aria-hidden="true"
                        className="text-ink-faint"
                      >
                        <rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="1.5" />
                        <circle cx="9" cy="9" r="1.8" fill="currentColor" />
                        <path d="M4 17l5-5 4 4 3-3 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                      </svg>
                      <div>
                        <p className="text-sm font-semibold text-ink">
                          Drag a photo here, or click to browse
                        </p>
                        <p className="mt-1.5 text-xs text-ink-faint">
                          JPG · PNG · WebP, up to 10MB
                          <br />
                          Automatically optimized to 1024px on upload
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-line shadow-lift">
                      <Image src={uploadedImage} alt="Uploaded room preview" fill className="object-cover" />
                      <button
                        onClick={resetAll}
                        title="Remove photo"
                        className="absolute right-3 top-3 flex h-9 w-9 cursor-pointer items-center justify-center rounded-full bg-ink/75 text-paper backdrop-blur-sm transition-all duration-200 hover:bg-ink active:scale-95"
                      >
                        ✕
                      </button>
                    </div>
                  )}
                </div>

                {/* 03+04. Options (mode-dependent) */}
                <div className="flex flex-col gap-8">
                  {mode.needsRoomType && (
                  <div className="flex flex-col gap-3">
                    <label className="flex items-baseline gap-2 text-base font-bold text-ink">
                      <span className="font-display text-sm text-clay">{roomStepNo}</span>
                      Room type
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {ROOM_TYPES.map((room) => (
                        <button
                          key={room.id}
                          onClick={() => {
                            setSelectedRoom(room.id);
                            setErrorMsg(null);
                          }}
                          className={`cursor-pointer rounded-full px-5 py-2.5 text-sm font-semibold transition-all duration-200 ${
                            selectedRoom === room.id
                              ? 'bg-ink text-paper shadow-lift'
                              : 'border border-line bg-paper text-ink-soft hover:border-line-strong hover:text-ink'
                          }`}
                        >
                          {room.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  )}

                  {mode.needsStyle && (
                  <div className="flex flex-col gap-3">
                    <label className="flex items-baseline gap-2 text-base font-bold text-ink">
                      <span className="font-display text-sm text-clay">{styleStepNo}</span>
                      Design style
                    </label>
                    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
                      {STYLES.map((style) => (
                        <button
                          key={style.id}
                          onClick={() => {
                            setSelectedStyle(style.id);
                            setErrorMsg(null);
                          }}
                          className={`flex cursor-pointer flex-col items-start gap-2 rounded-xl border p-3.5 text-left transition-all duration-200 ${
                            selectedStyle === style.id
                              ? 'border-clay bg-clay-soft shadow-lift'
                              : 'border-line bg-paper hover:-translate-y-0.5 hover:border-line-strong'
                          }`}
                        >
                          <span className="flex items-center gap-1">
                            {style.swatch.map((color) => (
                              <span
                                key={color}
                                className="h-3 w-3 rounded-full border border-ink/10"
                                style={{ backgroundColor: color }}
                              />
                            ))}
                          </span>
                          <span className="text-xs font-bold text-ink sm:text-sm">
                            {style.label}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                  )}

                  {!mode.needsRoomType && !mode.needsStyle && MODE_TIPS[mode.id] && (
                    <div className="flex h-full flex-col justify-center gap-3 rounded-2xl border border-line bg-paper p-6">
                      <p className="text-sm font-bold text-ink">{MODE_TIPS[mode.id].title}</p>
                      <ul className="flex flex-col gap-2 text-xs leading-relaxed text-ink-soft">
                        {MODE_TIPS[mode.id].items.map((tip) => (
                          <li key={tip}>• {tip}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Sign-in nudge + error + generate button (full width) */}
                <div className="flex flex-col gap-5 lg:col-span-2">
                  {authEnabled && !user && (
                    <div className="flex items-center justify-between gap-4 rounded-2xl border border-line bg-paper p-5">
                      <div>
                        <p className="text-sm font-bold text-ink">Get free credits</p>
                        <p className="mt-0.5 text-xs text-ink-soft">
                          Sign in with Google and get bonus credits — plus shareable
                          before/after pages for your clients.
                        </p>
                      </div>
                      <button
                        onClick={() => void signInWithGoogle()}
                        className="shrink-0 cursor-pointer rounded-full border border-line-strong bg-paper-raised px-5 py-2.5 text-xs font-bold text-ink transition-colors hover:border-ink"
                      >
                        Sign in with Google
                      </button>
                    </div>
                  )}

                  {errorMsg && (
                    <div
                      role="alert"
                      className="rounded-xl border border-clay/30 bg-clay-soft p-4 text-xs leading-relaxed text-clay-deep"
                    >
                      {errorMsg}
                    </div>
                  )}

                  <button
                    onClick={handleGenerate}
                    disabled={isLoading || !uploadedImage}
                    className={`w-full rounded-2xl py-4 text-base font-bold transition-all duration-300 ${
                      isLoading || !uploadedImage
                        ? 'cursor-not-allowed bg-sand text-ink-faint'
                        : 'cursor-pointer bg-ink text-paper shadow-lift hover:-translate-y-0.5 hover:bg-clay active:scale-[0.99]'
                    }`}
                  >
                    {isLoading
                      ? 'Designing your space...'
                      : GENERATE_LABELS[mode.id] ?? 'Generate'}
                  </button>

                  {isLoading && (
                    <div className="flex flex-col items-center gap-4 rounded-2xl border border-line bg-paper py-8">
                      <div className="flex items-center gap-2">
                        {[0, 150, 300].map((delay) => (
                          <span
                            key={delay}
                            className="h-2 w-2 animate-bounce rounded-full bg-clay"
                            style={{ animationDelay: `${delay}ms` }}
                          />
                        ))}
                      </div>
                      <p className="text-sm font-semibold text-ink" aria-live="polite">
                        {loadingStatuses[loadingStep]}
                      </p>
                      <p className="text-xs text-ink-faint">
                        The first generation takes about 10 seconds.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
