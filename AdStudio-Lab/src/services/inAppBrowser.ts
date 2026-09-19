// ============================================================
// 인앱 브라우저(웹뷰) 감지 및 외부 브라우저 탈출
// ------------------------------------------------------------
// 카카오톡·네이버·인스타그램 등의 앱 내장 브라우저에서는 Google이
// OAuth 로그인을 정책적으로 차단한다(403 disallowed_useragent).
// 우회는 불가능하므로, 감지해서 외부 브라우저로 열도록 안내한다.
// ============================================================

export type InAppBrowserName =
  | 'kakaotalk'
  | 'naver'
  | 'instagram'
  | 'facebook'
  | 'line'
  | 'daum'
  | 'band'
  | 'other';

/** 인앱 브라우저면 그 종류를, 일반 브라우저면 null 을 돌려준다. */
export function detectInAppBrowser(): InAppBrowserName | null {
  if (typeof navigator === 'undefined') return null;
  const ua = navigator.userAgent.toLowerCase();

  if (ua.includes('kakaotalk')) return 'kakaotalk';
  if (ua.includes('naver')) return 'naver';
  if (ua.includes('instagram')) return 'instagram';
  if (ua.includes('fbav') || ua.includes('fb_iab')) return 'facebook';
  if (ua.includes('line/')) return 'line';
  if (ua.includes('daumapps')) return 'daum';
  if (ua.includes('band/')) return 'band';
  if (ua.includes('android') && ua.includes('; wv)')) return 'other';

  return null;
}

export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function isAndroid(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /android/i.test(navigator.userAgent);
}

/**
 * 현재 페이지를 외부(기본) 브라우저로 다시 연다.
 * 카카오톡은 전용 스킴, 그 외 안드로이드는 intent 스킴으로 크롬을 띄운다.
 * iOS 인앱 브라우저는 자동 전환이 차단돼 있어 false 를 반환한다.
 */
export function openInExternalBrowser(): boolean {
  if (typeof window === 'undefined') return false;
  const url = window.location.href;
  const browser = detectInAppBrowser();

  if (browser === 'kakaotalk') {
    window.location.href = `kakaotalk://web/openExternal?url=${encodeURIComponent(url)}`;
    return true;
  }

  if (isAndroid()) {
    const noScheme = url.replace(/^https?:\/\//, '');
    window.location.href =
      `intent://${noScheme}#Intent;scheme=https;package=com.android.chrome;end`;
    return true;
  }

  return false;
}

/** 인앱 브라우저별 "직접 여는 방법" 안내 문구 */
export function externalBrowserHint(browser: InAppBrowserName): string {
  if (isIOS()) {
    if (browser === 'kakaotalk') return '오른쪽 아래 [⋯] → "다른 브라우저로 열기"를 눌러주세요.';
    if (browser === 'instagram' || browser === 'facebook') return '오른쪽 위 [⋯] → "브라우저에서 열기"를 눌러주세요.';
    return '화면의 [⋯] 또는 [공유] 버튼 → "Safari로 열기"를 눌러주세요.';
  }
  return '오른쪽 아래 [⋮] 메뉴 → "다른 브라우저로 열기"를 눌러주세요.';
}

/**
 * Google 로그인 직전에 호출. 인앱 브라우저면 외부 브라우저로 전환을 시도하고,
 * 로그인을 진행하면 안 된다는 뜻으로 Error 를 던진다(호출부가 메시지를 표시).
 */
export function guardGoogleSignIn(): void {
  const browser = detectInAppBrowser();
  if (!browser) return;
  const escaped = openInExternalBrowser();
  throw new Error(
    escaped
      ? '앱 안에서는 Google 로그인이 차단돼요. 브라우저로 이동합니다.'
      : `앱 안에서는 Google 로그인이 차단돼요. ${externalBrowserHint(browser)} (또는 이메일로 로그인해 주세요)`
  );
}
