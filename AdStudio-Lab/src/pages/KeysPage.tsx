import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Key, Eye, EyeOff, CheckCircle, XCircle, Loader,
  ExternalLink, Shield, AlertTriangle, ChevronDown, ChevronUp,
  BarChart3, Clock, Wand2, X, UserCheck, CreditCard, Globe2, Sparkles, ClipboardPaste
} from 'lucide-react'
import { useKeysStore, KeyVault, ALIBABA_FREE_QUOTA_SECONDS, ALIBABA_FREE_QUOTA_DAYS, GEMINI_FREE_IMAGE_RPD, GEMINI_FREE_TEXT_RPD, alibabaFreeDaysLeft } from '../stores/keysStore'
import { useUserStore } from '../stores/userStore'
import type { ProviderKey } from '../types'
import { clsx } from 'clsx'

// iOS(아이폰·아이패드)는 어떤 브라우저를 쓰든(사파리·크롬 등 모두 내부적으로 WebKit) 애플의
// ITP 정책 적용을 받아, 한동안 재방문이 없으면 저장된 데이터가 지워질 수 있다 — 그래서 "사파리"가
// 아니라 "iOS 기기 여부"로 판별한다. iPadOS 13+는 데스크톱 Mac과 동일한 UA를 쓰지만 터치 지원으로 구분.
function isIOSDevice(): boolean {
  const ua = navigator.userAgent
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

// ── 제공자 설정 ───────────────────────────────────────────────
interface ProviderConfig {
  id: ProviderKey
  name: string
  badge: string
  badgeType: 'free' | 'paid'
  desc: string
  guideUrl: string
  freeQuota?: string
  placeholder: string
  costPerScene?: string
}

const PROVIDERS: ProviderConfig[] = [
  {
    id: 'alibaba', name: '알리바바 Model Studio', badge: '무료 쿼터',
    badgeType: 'free', guideUrl: 'https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key',
    desc: '무료 AI 영상 레인 · 신규 가입 시 1,650초 무료 쿼터 (5초 클립 약 330개)',
    freeQuota: '1,650초', placeholder: 'sk-xxxxxxxxxxxxxxxxxxxxxxxx',
  },
  {
    id: 'gemini', name: 'Google Gemini Flash', badge: '무료', badgeType: 'free',
    guideUrl: 'https://aistudio.google.com/apikey',
    desc: '스토리보드 생성 · 다국어 번역 · 이미지 분석 (일 1,500 요청)',
    // 구글이 2025년부터 새 형식(AQ.Ab8…) 키를 발급한다 — 구형식(AIza…)도 그대로 유효하다
    placeholder: 'AQ.Ab8… 또는 AIza…',
  },
  {
    id: 'kaggle', name: 'Kaggle (LTX 오픈소스)', badge: '무료 GPU', badgeType: 'free',
    guideUrl: 'https://www.kaggle.com/settings',
    desc: '저품질 무료 AI 영상 — 내 Kaggle GPU(주 30시간, 매주 갱신)에서 LTX 오픈소스 실행 · 느림(씬당 10~30분) · "유저명:키" 형식으로 입력 (kaggle.com Settings → API → Create New Token으로 받은 kaggle.json의 username과 key)',
    freeQuota: '주 30 GPU시간', placeholder: 'username:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
  },
  {
    id: 'seedance', name: 'Seedance 2.0 Fast', badge: '유료', badgeType: 'paid',
    guideUrl: 'https://byteplus.com',
    desc: '일반 씬 기본 모델 · 720p · 전용 리소스팩 선불 구매 필요',
    // fast 리소스팩 단가 $3.30/M 토큰 기준, 앱이 실제로 호출하는 사양(720p·5초·오디오 없음)
    // = 약 103K 토큰 → $0.34/씬. (6초 $0.41 / 480p로 낮추면 $0.16)
    // 이전 표기 '~$0.11'은 실제와 3배 차이라 정정했고, '1080p'도 실제 호출 사양(720p)으로 맞췄다.
    placeholder: 'bp-xxxxxxxxxxxxxxxxxxxx', costPerScene: '~$0.34',
  },
  {
    // 앱이 실제로 호출하는 모델은 표준 'MiniMax-Hailuo-2.3'이다(-Fast 변형이 아니다) —
    // 이름을 'Fast'로 적으면 단가($0.28)와 어긋나 자기모순이 된다.
    id: 'hailuo', name: 'Hailuo 2.3', badge: '유료', badgeType: 'paid',
    // 국제판 키 발급 직링크(중국판 platform.minimaxi.com 키는 api.minimax.io에서 동작하지 않는다)
    guideUrl: 'https://platform.minimax.io/user-center/basic-information/interface-key',
    desc: '동작·애니·수묵 스타일 씬',
    // 공식 가격표(2026-07) 확인값: 768P·6초 $0.28 (앱은 이 사양으로 호출한다)
    placeholder: 'sk-api-…', costPerScene: '~$0.28',
  },
  {
    id: 'kling', name: 'Kling 3.0', badge: '유료', badgeType: 'paid',
    guideUrl: 'https://kling.ai/dev/api-key',
    desc: '인물 클로즈업 · 인물 일관성 중요 씬 · 720p(std)',
    // 공식 단가(2026-07) 확인값: 1 Unit=$0.14, Kling 3.0(오디오 없음) 720p=0.6 Unit/초
    // → 앱이 호출하는 사양(std 720p·5초)은 $0.42 (1080p pro는 0.8 Unit/초 → 5초 $0.56)
    // ⚠️ 미확인: Kling API Key의 실제 문자열 접두사(다른 제공자의 'sk-' 'bp-'처럼) — 콘솔에서 확인 후
    // 다른 제공자처럼 구체적 형식 힌트로 교체. 지금은 형식을 추측하지 않고 "무엇을 넣는지"만 명시한다.
    placeholder: 'API Key (Access/Secret Key 아님)', costPerScene: '~$0.42',
  },
  {
    id: 'veo', name: 'Veo 3.1 Fast', badge: '유료', badgeType: 'paid',
    guideUrl: 'https://ai.google.dev',
    desc: '대사·오디오 씬 (립싱크 내장) · 결제 계정 연결 필수 (무료 등급에는 Veo 쿼터가 없음)',
    // 공식 가격표(ai.google.dev/gemini-api/docs/pricing) 확인값: Veo 3.1 Fast 720p $0.10/초.
    // 앱은 720p·6초로 고정 호출하므로 씬당 6 × $0.10 = 약 $0.60. (1080p $0.12/초, 4k $0.30/초)
    placeholder: 'AQ.Ab8… 또는 AIza…', costPerScene: '~$0.60',
  },
]

// ── Alibaba API 키 발급 가이드 마법사 ────────────────────────────
// 계정 생성·결제수단 등록·본인인증처럼 비밀번호·카드번호·신분증이 필요한 단계는 자동화하지
// 않는다(보안·이용약관상 사람이 직접 해야 하는 부분) — 대신 정확히 어디로 가서 무엇을 눌러야
// 하는지 짚어주고, 그 사이 비민감 단계(페이지 이동·리전 선택 등)만 링크로 바로 연결해준다.
interface WizardStep {
  title: string
  icon: React.ReactNode
  needsUserAction: boolean // true면 비밀번호·카드번호 등 사용자가 직접 입력해야 하는 단계
  body: React.ReactNode
  linkLabel?: string
  linkUrl?: string
}

const ALIBABA_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. 계정 만들기',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 Alibaba Cloud 가입 페이지를 새 탭에서 엽니다.
        <strong> "Sign up with Google"</strong>을 눌러 구글 계정으로 가입하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 비밀번호·2단계 인증은 직접 입력해주세요 (여기서 대신 할 수 없어요).
        </div>
      </>
    ),
    linkLabel: 'Alibaba Cloud 가입 페이지 열기',
    linkUrl: 'https://account.alibabacloud.com/login/login.htm',
  },
  {
    title: '2. 본인 인증',
    icon: <Shield size={18} />,
    needsUserAction: true,
    body: (
      <>
        이메일·휴대폰으로 온 인증 코드를 입력해 계정을 활성화합니다.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 인증 코드는 직접 입력해주세요.
        </div>
      </>
    ),
  },
  {
    title: '3. 결제수단 등록',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        카드·계좌·USDT 중 하나로 결제수단을 등록합니다.
        <div style={{ marginTop: 8, color: 'var(--color-text-secondary)' }}>
          💡 이 단계에서 실제 청구는 되지 않아요 — 카드 유효성 확인용 임시 승인만 걸립니다.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 카드번호는 반드시 본인이 직접 입력해주세요.
        </div>
      </>
    ),
  },
  {
    title: '4. Model Studio로 이동',
    icon: <Globe2 size={18} />,
    needsUserAction: false,
    body: (
      <>
        가입이 끝나면 아래 버튼으로 Model Studio API 키 관리 화면(Singapore 리전)으로 바로 이동할 수 있어요.
      </>
    ),
    linkLabel: 'Model Studio API 키 화면 열기',
    linkUrl: 'https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key',
  },
  {
    title: '5. API 키 발급',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        <strong>"Create API Key"</strong> 클릭 → Workspace는 기본값, Permission은{' '}
        <strong>All</strong> 선택 → 확인을 누르면 키가 생성됩니다.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 키는 이 화면을 닫으면 다시 볼 수 없어요 — 바로 다음 단계로 등록해주세요.
        </div>
      </>
    ),
  },
  {
    title: '6. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: (
      <>
        생성된 키를 복사해서 아래에 붙여넣으면 바로 저장돼요.
        (또는 북마크바에 등록해둔 "AdStudio 키 등록기"를 그 화면에서 클릭해도 자동 등록됩니다.)
      </>
    ),
  },
]

// 결제수단 등록이 필요 없는 무료 제공자(Gemini)는 가입→키 발급이 훨씬 짧다
const GEMINI_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. 구글 계정으로 로그인',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 Google AI Studio를 새 탭에서 엽니다. 구글 계정으로 로그인하세요(이미 로그인돼 있으면 바로 통과돼요).
        <div style={{ marginTop: 8, color: 'var(--color-success)' }}>
          💳 결제수단 등록 없이 무료로 바로 사용할 수 있어요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 로그인은 직접 진행해주세요.
        </div>
      </>
    ),
    linkLabel: 'Google AI Studio 열기',
    linkUrl: 'https://aistudio.google.com/app/apikey',
  },
  {
    title: '2. API 키 생성',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        <strong>"Create API key"</strong> 클릭 → <strong>"새 프로젝트에서 생성"</strong>을 선택하면
        가장 간단하게 만들어져요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 키는 생성 즉시 복사해서 안전한 곳에 보관해주세요.
        </div>
      </>
    ),
  },
  {
    title: '3. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: <>생성된 키를 복사해서 아래에 붙여넣으면 바로 저장돼요. (<strong>AQ.Ab8…</strong>로 시작하는 새 형식과 <strong>AIza…</strong> 구형식 모두 정상이에요)</>,
  },
]

// Kaggle — 무료 GPU(주 30시간)에서 LTX 오픈소스로 저품질 무료 AI 영상을 만드는 토큰.
// GPU 노트북 실행에는 전화번호 인증이 필요하다는 점을 안내에 포함한다.
const KAGGLE_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. Kaggle 가입 + 전화 인증',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 Kaggle을 새 탭에서 열고 구글 계정으로 가입/로그인하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          📱 GPU 사용에는 Settings → Phone verification에서 전화번호 인증이 꼭 필요해요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-success)' }}>
          💳 결제수단 등록 없이 매주 30 GPU시간이 무료로 갱신돼요.
        </div>
      </>
    ),
    linkLabel: 'Kaggle 설정 열기',
    linkUrl: 'https://www.kaggle.com/settings',
  },
  {
    title: '2. API 키 파일 받기',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        Settings의 API Tokens 탭 아래쪽 <strong>"Create Legacy API Key"</strong> 버튼을 누르면
        <strong> kaggle.json</strong> 파일이 자동 다운로드돼요. 이게 가장 쉬운 방법이에요.
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          (위쪽 "API Tokens"에서 Generate한 토큰을 쓰는 방법도 있어요 — 이 경우엔 3단계에서
          유저명:토큰 형식으로 직접 입력해야 해요.)
        </div>
      </>
    ),
  },
  {
    title: '3. AdStudio에 등록 — 붙여넣기 한 번이면 끝',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: (
      <>
        다운로드된 <strong>kaggle.json 파일을 메모장으로 열어 내용 전체를 복사</strong>한 뒤,
        아래 입력칸에 <strong>그대로 붙여넣기만 하면 끝</strong>이에요 — 유저명이 뭔지 몰라도
        앱이 자동으로 인식해요.
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          ⏳ 이 레인은 내 Kaggle GPU에서 오픈소스 LTX 모델을 직접 실행해요 — 씬당 10~30분 정도
          걸리는 대신 완전 무료예요(저품질·워터마크 포함).
        </div>
      </>
    ),
  },
]

// 아래 4개(Seedance/Hailuo/Kling/Veo)는 모두 유료 레인 — 결제수단 등록이 필요하다.
// Alibaba와 같은 원칙: 결제·본인인증·로그인처럼 카드번호나 비밀번호가 필요한 단계는
// 자동화하지 않고 명확히 표시만 하며, 페이지 이동 같은 비민감 단계만 버튼으로 대신해준다.
const SEEDANCE_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. 계정 만들기',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 BytePlus를 새 탭에서 엽니다. 이메일 등으로 가입하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 비밀번호·이메일 인증은 직접 입력해주세요.
        </div>
      </>
    ),
    linkLabel: 'BytePlus 가입 페이지 열기',
    linkUrl: 'https://www.byteplus.com',
  },
  {
    title: '2. 결제수단 등록',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        ModelArk(Seedance 모델 콘솔)는 결제수단을 등록해야 API 키가 실제로 동작해요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 카드번호는 반드시 본인이 직접 입력해주세요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          ※ 결제수단 등록만으로는 Seedance 호출이 안 돼요 — 다음 단계의 리소스팩 구매가 필요해요.
        </div>
      </>
    ),
  },
  {
    // ModelArk는 Seedance를 종량과금이 아니라 "모델별 전용 리소스팩 선불" 방식으로 판다.
    // 이 단계를 빼먹으면 키가 정상인데도 400 'No available resource packs'로 실패한다
    // (callProxy의 seedance 분기가 이 오류를 전용 안내로 바꿔준다).
    // 단가 $3.30/M 토큰(fast)은 공개 가격표와 일치하는 확인값.
    // ⚠️ 미확인: 최소 구매 단위·유효기간·환불 정책. 사용자 관측값은 9M 토큰 $29.70·90일·환불 불가지만,
    //   공개 가격표에는 1M $3.30 / 10M $33 / 100M $330 구성으로 나와 조건이 갈린다 — 콘솔 결제 화면에서
    //   확인 후 아래 문구의 숫자를 확정할 것. 그래서 UI에도 "관측 기준"으로만 적고 재확인을 안내한다.
    title: '3. Seedance 전용 리소스팩 구매',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        콘솔의 <strong>ModelArk → Resource packs</strong>에서 <strong>Dreamina-Seedance-2.0-fast</strong>{' '}
        팩을 구매하세요. 모델별 전용 팩이라, <strong>fast 팩은 fast 모델에만 차감</strong>돼요 —
        일반 2.0 팩을 사면 이 앱이 쓰는 모델에는 쓸 수 없어요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 선불 구매가 필수예요. 팩이 없으면 키가 정상이어도
          &quot;No available resource packs&quot; 오류로 영상이 생성되지 않아요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          💰 단가 $3.30/M 토큰(fast) 기준 720p·5초 씬 약 $0.34. 관측된 최소 구매 조건은
          9M 토큰 $29.70 · 유효기간 90일 · 환불 불가 — 팩 구성과 조건은 바뀔 수 있으니
          결제 전 콘솔 화면에서 직접 확인해주세요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 결제는 반드시 본인이 직접 진행해주세요.
        </div>
      </>
    ),
  },
  {
    title: '4. ModelArk 콘솔에서 API 키 발급',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        콘솔의 <strong>ModelArk</strong> 메뉴 → API Key 관리에서 새 키를 생성하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 키는 생성 즉시 복사해서 안전한 곳에 보관해주세요.
        </div>
      </>
    ),
  },
  {
    title: '5. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: (
      <>
        생성된 키를 복사해서 아래에 붙여넣으면 바로 저장돼요.
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          ※ 키는 발급 리전(Asia Pacific / Johor)에 묶여요 — 다른 리전에서 만든 키는 401·404로 실패해요.
        </div>
      </>
    ),
  },
]

const HAILUO_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. 계정 만들기',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 <strong>국제판</strong> MiniMax 플랫폼(platform.minimax.io)을 새 탭에서 엽니다.
        이메일로 가입하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 중국판(platform.minimaxi.com)에서 발급한 키는 이 앱이 호출하는 국제판 API(api.minimax.io)에서
          동작하지 않아요. 반드시 아래 버튼의 국제판에서 가입·발급해주세요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 비밀번호·이메일 인증은 직접 입력해주세요.
        </div>
      </>
    ),
    linkLabel: 'MiniMax 국제판 플랫폼 열기',
    linkUrl: 'https://platform.minimax.io',
  },
  {
    title: '2. API 키 발급',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        <strong>User Center</strong> → <strong>Basic Information</strong> → <strong>Interface Key</strong>에서
        새 키를 생성하세요(아래 버튼이 이 화면을 바로 엽니다).
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 키는 생성 즉시 복사해서 안전한 곳에 보관해주세요.
        </div>
      </>
    ),
    linkLabel: 'API 키 발급 화면 열기',
    linkUrl: 'https://platform.minimax.io/user-center/basic-information/interface-key',
  },
  {
    // 충전 위치를 혼동하면 "충전했는데 잔액 부족(1008)" 상황이 생긴다 — 어디를 채워야 하는지 명시한다.
    title: '3. 잔액(Balance) 충전 위치 확인',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        영상 생성에 쓰이는 건 <strong>User Center → Payment → Balance</strong>의 잔액이에요.
        이 Balance를 충전해야 영상이 생성돼요 — <strong>Token Plan의 Credits는 영상 생성에 쓰이지 않아요</strong>.
        <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>
          잔액이 없으면 API가 "insufficient balance(1008)" 오류를 돌려주고 영상이 만들어지지 않아요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 카드번호 입력·충전은 반드시 본인이 직접 진행해주세요.
        </div>
      </>
    ),
  },
  {
    title: '4. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: <>생성된 키를 복사해서 아래에 붙여넣으면 바로 저장돼요.</>,
  },
]

const KLING_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. 계정 만들기',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        아래 버튼으로 Kling AI 개발자 포털을 새 탭에서 엽니다. 계정을 가입하세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 비밀번호·이메일 인증은 직접 입력해주세요.
        </div>
      </>
    ),
    linkLabel: 'Kling AI 개발자 포털 열기',
    linkUrl: 'https://kling.ai/dev',
  },
  {
    title: '2. 영상 생성용 리소스 패키지 구매(결제)',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        Kling은 무료 크레딧만으로는 API 호출이 안 되고, <strong>영상 생성용 리소스 패키지 구매</strong>(결제)가
        필요해요. 아래 버튼이 가격표의 영상(Video) 항목으로 바로 이동해요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 결제 정보는 반드시 본인이 직접 입력해주세요.
        </div>
      </>
    ),
    linkLabel: 'Kling 요금·패키지 구매 페이지 열기',
    linkUrl: 'https://kling.ai/dev/pricing?scrollTo=video',
  },
  {
    title: '3. API Key 발급',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        Console에서 <strong>API Key</strong>를 발급하세요(<strong>Access Key/Secret Key가 아닙니다</strong>).
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 같은 페이지의 Access Key/Secret Key(AK/SK) 쌍을 붙여넣으면 반드시 실패해요 — AK/SK 방식은
          매 호출마다 JWT 서명을 만들어야 하는 별도 인증이라, 이 앱은 API Key 단독 인증만 씁니다.
        </div>
      </>
    ),
    linkLabel: 'Kling API Key 발급 페이지 열기',
    linkUrl: 'https://kling.ai/dev/api-key',
  },
  {
    title: '4. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: <>발급한 API Key를 복사해서 아래에 붙여넣으면 바로 저장돼요.</>,
  },
]

const VEO_WIZARD_STEPS: WizardStep[] = [
  {
    title: '1. Google Cloud 프로젝트 만들기',
    icon: <UserCheck size={18} />,
    needsUserAction: true,
    body: (
      <>
        Veo는 무료 Gemini 키(aistudio.google.com)와는 별개로, <strong>Google Cloud 프로젝트 + 결제 계정</strong>이
        필요해요. 아래 버튼으로 Google Cloud 콘솔을 열고 새 프로젝트를 만드세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 구글 로그인은 직접 진행해주세요.
        </div>
      </>
    ),
    linkLabel: 'Google Cloud 콘솔 열기',
    linkUrl: 'https://console.cloud.google.com',
  },
  {
    title: '2. 결제 계정 연결',
    icon: <CreditCard size={18} />,
    needsUserAction: true,
    body: (
      <>
        프로젝트에 결제 계정을 연결합니다. <strong>Veo는 무료 등급에 쿼터가 아예 없어서</strong>,
        결제 계정 연결이 선택이 아니라 필수예요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ Google Cloud 신규 가입 $300 무료 크레딧은 Gemini API·Veo 사용료에는 쓸 수 없어요 —
          2026년 3월 2일 이후에 만든 계정은 이 크레딧이 Gemini API/AI Studio 사용료에 적용되지 않습니다
          (그전에 받은 크레딧만 만료 전까지 사용 가능). 즉 영상 생성분은 처음부터 실제 청구예요.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-text-secondary)' }}>
          💡 이 앱은 Veo를 720p·6초로 고정 호출해요 — 공식 단가 $0.10/초 기준 씬당 약 $0.60,
          8씬 광고 하나면 약 $4.8입니다.
        </div>
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          🔒 카드번호는 반드시 본인이 직접 입력해주세요.
        </div>
      </>
    ),
  },
  {
    title: '3. Generative Language API 활성화',
    icon: <Globe2 size={18} />,
    needsUserAction: true,
    body: (
      <>
        프로젝트에서 <strong>Generative Language API</strong>를 활성화하세요.
        <div style={{ marginTop: 8, color: 'var(--color-text-secondary)' }}>
          💡 Vertex AI가 아니라 이 API입니다 — Vertex AI는 API 키를 받지 않고 OAuth 토큰을
          요구해서 브라우저에서 직접 호출할 수 없어요.
        </div>
      </>
    ),
  },
  {
    title: '4. AI Studio에서 API 키 발급',
    icon: <Sparkles size={18} />,
    needsUserAction: true,
    body: (
      <>
        <strong>aistudio.google.com/apikey</strong>에서 <strong>2단계에서 결제를 연결한 그 프로젝트</strong>를
        선택해 API 키를 만드세요.
        <div style={{ marginTop: 8, color: 'var(--color-warning, #f59e0b)' }}>
          ⚠️ 결제가 연결되지 않은 무료 등급 키로는 Veo 호출이 거부돼요(영상 생성은 유료 기능).
          분석용으로 쓰는 Gemini 키와 다른 키일 수 있으니 주의하세요.
        </div>
      </>
    ),
    linkLabel: 'Google AI Studio 키 페이지 열기',
    linkUrl: 'https://aistudio.google.com/apikey',
  },
  {
    title: '5. AdStudio에 등록',
    icon: <ClipboardPaste size={18} />,
    needsUserAction: false,
    body: <>생성된 키를 복사해서 아래에 붙여넣으면 바로 저장돼요.</>,
  },
]

const WIZARD_STEPS_BY_PROVIDER: Partial<Record<ProviderKey, WizardStep[]>> = {
  alibaba: ALIBABA_WIZARD_STEPS,
  gemini: GEMINI_WIZARD_STEPS,
  kaggle: KAGGLE_WIZARD_STEPS,
  seedance: SEEDANCE_WIZARD_STEPS,
  hailuo: HAILUO_WIZARD_STEPS,
  kling: KLING_WIZARD_STEPS,
  veo: VEO_WIZARD_STEPS,
}

function ProviderSignupWizard({ providerId, providerName, placeholder, onClose }: {
  providerId: ProviderKey
  providerName: string
  placeholder: string
  onClose: () => void
}) {
  const { saveKey, setKeyStatus, setValidating } = useKeysStore()
  const [stepIdx, setStepIdx] = useState(0)
  const [pastedKey, setPastedKey] = useState('')
  const [saved, setSaved] = useState(false)
  const wizardSteps = WIZARD_STEPS_BY_PROVIDER[providerId] ?? []
  const step = wizardSteps[stepIdx]
  const isLastStep = stepIdx === wizardSteps.length - 1

  const handleSaveKey = async () => {
    if (!pastedKey.trim()) return
    await saveKey(providerId, pastedKey.trim())
    setValidating(providerId, true)
    await new Promise(r => setTimeout(r, 1200))
    setValidating(providerId, false)
    setKeyStatus(providerId, { isSet: true, isValid: true, validatedAt: new Date() })
    setSaved(true)
  }

  if (!step) return null

  return (
    <motion.div
      className="modal-overlay"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onClick={onClose}
    >
      <motion.div
        className="modal-sheet"
        initial={{ y: 100 }} animate={{ y: 0 }}
        onClick={e => e.stopPropagation()}
      >
        <div className="modal-sheet__handle" />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Wand2 size={18} color="var(--color-brand-400)" />
            {providerName} API 키 발급 가이드
          </h2>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: 16 }}>
          {stepIdx + 1} / {wizardSteps.length} 단계 ·{' '}
          {step.needsUserAction ? '직접 입력이 필요해요' : '자동으로 도와드릴 수 있어요'}
        </p>

        {/* 진행 바 */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 20 }}>
          {wizardSteps.map((_, i) => (
            <div key={i} style={{
              flex: 1, height: 4, borderRadius: 2,
              background: i <= stepIdx ? 'var(--gradient-brand)' : 'var(--color-border)',
            }} />
          ))}
        </div>

        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, fontWeight: 700 }}>
            {step.icon} {step.title}
          </div>
          <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
            {step.body}
          </div>

          {step.linkUrl && (
            <a
              href={step.linkUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary btn-full"
              style={{ marginTop: 14 }}
            >
              <ExternalLink size={14} /> {step.linkLabel}
            </a>
          )}

          {isLastStep && (
            <div style={{ marginTop: 14 }}>
              {saved ? (
                <div className="key-badge valid" style={{ justifyContent: 'center' }}>
                  <CheckCircle size={14} color="var(--color-success)" />
                  <span style={{ fontSize: '0.8rem' }}>키가 저장됐어요!</span>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    className="input"
                    value={pastedKey}
                    onChange={e => setPastedKey(e.target.value)}
                    placeholder={placeholder}
                  />
                  <button className="btn btn-primary btn-sm" onClick={handleSaveKey} disabled={!pastedKey.trim()}>
                    저장
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: stepIdx === 0 ? '1fr' : '1fr 1fr', gap: 8 }}>
          {stepIdx > 0 && (
            <button className="btn btn-outline" onClick={() => setStepIdx(i => i - 1)}>이전</button>
          )}
          {saved ? (
            <button className="btn btn-primary" onClick={onClose}>완료</button>
          ) : !isLastStep ? (
            <button className="btn btn-primary" onClick={() => setStepIdx(i => i + 1)}>다음</button>
          ) : null}
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── 키 입력 아이템 ────────────────────────────────────────────
function KeyProviderItem({ config }: { config: ProviderConfig }) {
  const { keyStatuses, isValidating, saveKey, removeKey, setKeyStatus, setValidating, accountRegisteredProviders } = useKeysStore()
  const status = keyStatuses[config.id]
  const registeredElsewhere = !status?.isSet && accountRegisteredProviders.includes(config.id)

  const [expanded, setExpanded] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)

  // 실제 저장된 키가 있는지 확인 (마운트 시)
  useEffect(() => {
    KeyVault.hasKey(config.id).then(has => {
      if (has) setKeyStatus(config.id, { isSet: true })
    })
  }, [config.id, setKeyStatus])

  const handleSave = async () => {
    if (!inputValue.trim()) return
    await saveKey(config.id, inputValue.trim())
    setInputValue('')
    // 키 유효성 검사 (실제 API 호출 전까지 목업)
    setValidating(config.id, true)
    await new Promise(r => setTimeout(r, 1500))
    setValidating(config.id, false)
    setKeyStatus(config.id, { isValid: true, validatedAt: new Date() })
  }

  const handleRemove = async () => {
    await removeKey(config.id)
    setKeyStatus(config.id, { isSet: false, isValid: null })
  }

  const validating = isValidating[config.id]

  return (
    <motion.div
      className="card"
      layout
      style={{
        borderColor: status?.isValid === true
          ? 'rgba(16,185,129,0.3)'
          : status?.isValid === false
          ? 'rgba(239,68,68,0.3)'
          : 'var(--color-border)',
      }}
    >
      {/* 헤더 행 */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{
          width: 36, height: 36, borderRadius: 10, flexShrink: 0,
          background: status?.isSet ? 'rgba(16,185,129,0.1)' : 'var(--color-bg-base)',
          border: `1px solid ${status?.isSet ? 'rgba(16,185,129,0.2)' : 'var(--color-border)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Key size={16} color={status?.isSet ? 'var(--color-success)' : 'var(--color-text-muted)'} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
            <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>{config.name}</span>
            <span className={clsx('badge', config.badgeType === 'free' ? 'badge-success' : 'badge-warning')}>
              {config.badge}
            </span>
            {config.costPerScene && (
              <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>{config.costPerScene}/씬</span>
            )}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {config.desc}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {validating ? (
            <Loader size={16} className="animate-spin" color="var(--color-brand-400)" />
          ) : status?.isValid === true ? (
            <CheckCircle size={16} color="var(--color-success)" />
          ) : status?.isValid === false ? (
            <XCircle size={16} color="var(--color-error)" />
          ) : status?.isSet ? (
            <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>미검증</span>
          ) : null}
          {expanded ? <ChevronUp size={16} color="var(--color-text-muted)" /> : <ChevronDown size={16} color="var(--color-text-muted)" />}
        </div>
      </div>

      {/* 확장 영역 */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* 설명 */}
              <div style={{
                fontSize: '0.8rem', color: 'var(--color-text-secondary)',
                padding: '8px 12px', background: 'var(--color-bg-base)',
                borderRadius: 8, lineHeight: 1.5,
              }}>
                {config.desc}
                {config.freeQuota && (
                  <div style={{ marginTop: 4, color: 'var(--color-success)', fontWeight: 600 }}>
                    🎁 무료 쿼터: {config.freeQuota}
                  </div>
                )}
              </div>

              {/* 현재 상태 */}
              {status?.isSet && (
                <div className="key-badge valid" style={{ justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <CheckCircle size={14} color="var(--color-success)" />
                    <span style={{ fontSize: '0.8rem' }}>키 저장됨 · 브라우저 암호화 보관</span>
                  </div>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={handleRemove}
                    style={{ fontSize: '0.7rem', color: 'var(--color-error)' }}
                  >
                    삭제
                  </button>
                </div>
              )}

              {/* 다른 기기에서 이미 등록했던 제공자 안내 (계정에는 등록 여부만 기록, 키 값은 기기별 로컬 보관) */}
              {registeredElsewhere && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  fontSize: '0.75rem', color: 'var(--color-text-muted)',
                  background: 'var(--color-bg-base)', borderRadius: 8, padding: '8px 12px',
                }}>
                  💡 다른 기기에서 이미 등록한 적 있어요 — 키 값은 기기마다 따로 저장되니 이 기기에서도 입력해주세요
                </div>
              )}

              {/* 키 입력 */}
              {!status?.isSet && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <div style={{ flex: 1, position: 'relative' }}>
                    <input
                      className="input"
                      type={showKey ? 'text' : 'password'}
                      value={inputValue}
                      onChange={e => setInputValue(e.target.value)}
                      placeholder={config.placeholder}
                      onKeyDown={e => e.key === 'Enter' && handleSave()}
                    />
                    <button
                      style={{
                        position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
                        background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)',
                      }}
                      onClick={() => setShowKey(!showKey)}
                    >
                      {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSave}
                    disabled={!inputValue.trim() || validating}
                  >
                    {validating ? <Loader size={14} className="animate-spin" /> : '저장'}
                  </button>
                </div>
              )}

              {/* 단계별 가이드 마법사가 있는 제공자는 버튼으로 노출 — 키 저장 후에도
                  재발급·다른 기기 등록에 쓰이므로 항상 보여준다 */}
              {WIZARD_STEPS_BY_PROVIDER[config.id] && (
                <button
                  className="btn btn-primary btn-sm"
                  style={{ justifyContent: 'center' }}
                  onClick={() => setWizardOpen(true)}
                >
                  <Wand2 size={13} /> {config.name} 키 구하기 (단계별 안내)
                </button>
              )}

              {/* 발급 가이드 링크 */}
              <a
                href={config.guideUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-ghost btn-sm"
                style={{ justifyContent: 'flex-start', fontSize: '0.75rem' }}
              >
                <ExternalLink size={13} />
                {config.name} 키 발급 가이드 →
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {wizardOpen && (
        <ProviderSignupWizard
          providerId={config.id}
          providerName={config.name}
          placeholder={config.placeholder}
          onClose={() => setWizardOpen(false)}
        />
      )}
    </motion.div>
  )
}

// ── 쿼터 대시보드 ─────────────────────────────────────────────
function QuotaDashboard() {
  const { quotas, keyStatuses, alibabaPaidMode, renewAlibabaFree, confirmAlibabaPaid } = useKeysStore()
  const alibabaStatus = keyStatuses['alibaba']
  const totalFree = ALIBABA_FREE_QUOTA_SECONDS
  const used = quotas['alibaba']?.estimatedSecondsUsed ?? 0
  const pct = Math.min(100, (used / totalFree) * 100)
  // 무료 기한 D-day — 만료되면(≤0) 알리바바 사용이 전면 자동 중단되고 아래 갱신 배너가 뜬다
  const daysLeft = alibabaFreeDaysLeft()
  const expired = daysLeft !== null && daysLeft <= 0

  if (!alibabaStatus?.isSet) return null

  return (
    <div className="quota-card" style={{ marginBottom: 16 }}>
      <div className="flex-between">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <BarChart3 size={16} color="var(--color-brand-400)" />
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>알리바바 무료 쿼터</span>
        </div>
        {alibabaPaidMode ? (
          <span className="badge badge-brand"><Clock size={10} /> 유료 모드</span>
        ) : (
          <span className={clsx('badge', expired ? 'badge-error' : (daysLeft !== null && daysLeft <= 7) ? 'badge-warning' : 'badge-success')}>
            <Clock size={10} /> {expired ? '기한 만료' : `D-${daysLeft ?? ALIBABA_FREE_QUOTA_DAYS}`}
          </span>
        )}
      </div>

      {expired && (
        <div style={{
          margin: '10px 0', padding: '10px 12px', borderRadius: 10,
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 10 }}>
            <AlertTriangle size={15} color="var(--color-error)" style={{ flexShrink: 0, marginTop: 1 }} />
            <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, margin: 0 }}>
              <strong style={{ color: 'var(--color-error)' }}>무료 사용 기한(등록 후 {ALIBABA_FREE_QUOTA_DAYS}일 추정)이 지나
              알리바바 사용을 자동 중단했어요.</strong> 기한이 지난 뒤의 호출은 콘솔 설정에 따라 실제 요금이
              청구될 수 있어요. 알리바바 콘솔에서 상태를 확인한 뒤 아래에서 갱신을 선택해주세요.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary btn-sm" style={{ flex: 1 }} onClick={renewAlibabaFree}>
              새 무료 쿼터로 갱신 (+{ALIBABA_FREE_QUOTA_DAYS}일)
            </button>
            <button className="btn btn-outline btn-sm" style={{ flex: 1 }} onClick={confirmAlibabaPaid}>
              유료 전환함 — 기한 없이 사용
            </button>
          </div>
        </div>
      )}

      <div className="quota-bar">
        <motion.div
          className="quota-bar__fill"
          style={{
            background: pct > 80 ? 'var(--color-error)' : pct > 60 ? 'var(--color-warning)' : 'var(--gradient-brand)',
            width: `${pct}%`,
          }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8 }}
        />
      </div>

      <div className="flex-between">
        <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
          잔여 약 <strong style={{ color: 'var(--color-text-primary)' }}>{totalFree - used}</strong>초
        </span>
        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
          {used}/{totalFree}초 사용 (추정치)
        </span>
      </div>

      <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textAlign: 'center' }}>
        💡 추정치입니다. 정확한 값은 알리바바 콘솔에서 확인하세요.
      </div>
    </div>
  )
}

/** QuotaDashboard의 알리바바 막대 하나를 그대로 본떠 만든 서브 컴포넌트 — Gemini는 "초" 대신
 * "하루 요청 수" 2종(이미지 생성/텍스트·비전)을 따로 보여줘야 해서 막대를 2개 그린다. */
function GeminiUsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, (used / limit) * 100)
  return (
    <div>
      <div className="quota-bar">
        <motion.div
          className="quota-bar__fill"
          style={{
            background: pct > 80 ? 'var(--color-error)' : pct > 60 ? 'var(--color-warning)' : 'var(--gradient-brand)',
            width: `${pct}%`,
          }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8 }}
        />
      </div>
      <div className="flex-between">
        <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{label}</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
          {used}/{limit}회 사용 (추정치)
        </span>
      </div>
    </div>
  )
}

// ── Gemini 쿼터 대시보드 ─────────────────────────────────────
function GeminiQuotaDashboard() {
  const { keyStatuses, getGeminiUsageToday } = useKeysStore()
  const geminiStatus = keyStatuses['gemini']
  if (!geminiStatus?.isSet) return null

  const usage = getGeminiUsageToday()

  return (
    <div className="quota-card" style={{ marginBottom: 16 }}>
      <div className="flex-between">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <BarChart3 size={16} color="var(--color-brand-400)" />
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Gemini 오늘 사용량</span>
        </div>
        <span className="badge badge-success">
          <Clock size={10} /> 태평양 시간 자정 리셋
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <GeminiUsageBar label="이미지 생성" used={usage.image} limit={GEMINI_FREE_IMAGE_RPD} />
        <GeminiUsageBar label="검증·번역·분석" used={usage.text} limit={GEMINI_FREE_TEXT_RPD} />
      </div>

      <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textAlign: 'center' }}>
        💡 무료 티어 한도는 계정마다 다를 수 있어 보수적으로 추정한 값이에요 — 정확한 값은 Google AI
        Studio에서 확인하세요. 한도를 넘겨도 자동으로 다른 제공자로 대체되니 생성이 멈추진 않아요.
      </div>
    </div>
  )
}

// ── 메인 키 설정 페이지 ───────────────────────────────────────
export default function KeysPage() {
  const navigate = useNavigate()
  const { user } = useUserStore()
  const [activeTab, setActiveTab] = useState<'free' | 'paid'>('free')
  const [isIOS] = useState(isIOSDevice)

  const freeProviders = PROVIDERS.filter(p => p.badgeType === 'free')
  const paidProviders = PROVIDERS.filter(p => p.badgeType === 'paid')

  // URL에서 import_provider와 import_key 파라미터 감지하여 자동 등록
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const importProvider = params.get('import_provider')
    const importKey = params.get('import_key')

    if (importProvider && importKey) {
      const provider = importProvider as ProviderKey
      const saveKeyAndNotify = async () => {
        const { saveKey, setKeyStatus, setValidating } = useKeysStore.getState()
        
        // 1. 키 저장
        await saveKey(provider, importKey)
        
        // 2. 유효성 검증 애니메이션
        setValidating(provider, true)
        await new Promise(r => setTimeout(r, 1200))
        setValidating(provider, false)
        setKeyStatus(provider, { isSet: true, isValid: true, validatedAt: new Date() })

        // 3. 안내 알림
        alert(`🎉 ${provider.toUpperCase()} API 키가 자동으로 정상 등록되었습니다!`)

        // 4. URL 파라미터 클린업
        const newUrl = window.location.pathname
        window.history.replaceState({}, document.title, newUrl)
      }
      saveKeyAndNotify()
    }
  }, [])

  return (
    <div style={{ padding: '20px 16px', paddingBottom: 100 }}>

      {/* 헤더 */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: '1.375rem', fontWeight: 800, marginBottom: 6 }}>API 키 설정</h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          키는 내 브라우저에만 저장돼요
        </p>
      </div>

      {/* API 자동발급기 연동 카드 */}
      <div className="card" style={{
        background: 'linear-gradient(145deg, rgba(124,58,255,0.08), rgba(245,158,11,0.03))',
        borderColor: 'rgba(124,58,255,0.2)',
        marginBottom: 20
      }}>
        <h3 style={{ fontSize: '0.85rem', fontWeight: 800, color: 'var(--color-brand-300)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          🚀 API 자동발급기로 1초 만에 키 등록하기
        </h3>
        <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, marginBottom: 12 }}>
          아래 버튼을 누르면 <strong>API 자동발급기</strong> 사이트가 새 탭으로 열려요.
          안내에 따라 키를 발급받으면 여기로 자동으로 돌아와 즉시 저장됩니다!
        </p>

        <a
          href="https://headjim-api.web.app"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '10px 16px',
            borderRadius: 8,
            background: 'var(--gradient-brand)',
            color: '#fff',
            fontSize: '0.8rem',
            fontWeight: 700,
            textDecoration: 'none',
            border: '1px solid rgba(255,255,255,0.1)',
            boxShadow: '0 4px 12px rgba(124,58,255,0.2)'
          }}
        >
          ✨ API 자동발급기 열기
        </a>
      </div>

      {/* 보안 배너 */}
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 14px', borderRadius: 12,
          background: 'rgba(16,185,129,0.08)',
          border: '1px solid rgba(16,185,129,0.2)',
          marginBottom: 20,
        }}
      >
        <Shield size={18} color="var(--color-success)" style={{ flexShrink: 0 }} />
        <div>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-success)', marginBottom: 2 }}>
            키 보안 원칙
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, marginBottom: 0 }}>
            API 키는 WebCrypto로 암호화해 이 브라우저에만 저장됩니다. 서버로 전송되지 않으며, 프록시 요청 로그에도 키를 남기지 않습니다.
          </div>
        </div>
      </motion.div>

      {/* 아이폰/아이패드 데이터 자동 삭제 경고 — 애플 ITP 정책으로 오래 재방문 없으면 로컬 저장된
          키가 지워질 수 있다는 걸 기술 용어 없이 쉽게 안내 */}
      {isIOS && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 10,
          padding: '12px 14px', borderRadius: 12,
          background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
          marginBottom: 20,
        }}>
          <AlertTriangle size={18} color="var(--color-warning, #f59e0b)" style={{ flexShrink: 0, marginTop: 1 }} />
          <div>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: 2 }}>
              📱 아이폰·아이패드를 쓰신다면 꼭 알아두세요
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
              이 앱을 <strong>한동안(약 일주일 이상) 다시 안 열면</strong>, 아이폰이 저장해둔 API 키를
              스스로 지워버릴 수 있어요. 이건 애플이 개인정보 보호를 위해 만든 정책이라 앱에서는 막을 수
              없어요. 오랜만에 들어왔는데 등록한 키가 안 보인다면 지워진 거니, 다시 입력해주시면 돼요.
              {user && ' 로그인해두셨다면 어떤 걸 등록했었는지는 계정이 기억하고 있어요.'}
            </div>
          </div>
        </div>
      )}

      {/* 회원가입 안내 — 로그인하면 "어떤 제공자를 등록했었는지" 여부만 계정에 저장돼 다른 기기에서도
          기억할 수 있다(키 값 자체는 여전히 기기별 로컬에만 남는다) */}
      {!user && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 14px', borderRadius: 12,
          background: 'rgba(124,58,255,0.06)', border: '1px solid rgba(124,58,255,0.2)',
          marginBottom: 20,
        }}>
          <UserCheck size={18} color="var(--color-brand-400)" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: 2 }}>
              회원 로그인하면 등록 상태가 유지돼요
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
              로그인하면 어떤 제공자를 등록했었는지가 계정에 저장돼요. 다른 기기에서 로그인해도 등록했던
              목록을 알 수 있어요 (키 값 자체는 그대로 기기별로만 저장돼요).
            </div>
          </div>
          <button className="btn btn-outline btn-sm" style={{ flexShrink: 0 }} onClick={() => navigate('/profile')}>
            로그인
          </button>
        </div>
      )}

      {/* 알리바바 쿼터 대시보드 */}
      <QuotaDashboard />

      {/* Gemini 오늘 사용량(추정) 대시보드 */}
      <GeminiQuotaDashboard />

      {/* 탭 */}
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button
          className={clsx('tab', activeTab === 'free' && 'active')}
          onClick={() => setActiveTab('free')}
        >
          🎁 무료 API (필수)
        </button>
        <button
          className={clsx('tab', activeTab === 'paid' && 'active')}
          onClick={() => setActiveTab('paid')}
        >
          ⭐ 유료 고퀄 레인
        </button>
      </div>

      {/* 무료 제공자 목록 */}
      {activeTab === 'free' && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          <div style={{
            padding: '10px 12px', borderRadius: 10,
            background: 'rgba(124,58,255,0.06)',
            border: '1px solid rgba(124,58,255,0.15)',
            fontSize: '0.8rem', color: 'var(--color-text-secondary)',
            marginBottom: 4,
          }}>
            💡 알리바바 키 하나면 무료 AI 영상 레인을 사용할 수 있어요. Gemini는 스토리보드 생성에 사용됩니다.
          </div>
          {freeProviders.map(p => <KeyProviderItem key={p.id} config={p} />)}
        </motion.div>
      )}

      {/* 유료 제공자 목록 */}
      {activeTab === 'paid' && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          <div style={{
            padding: '10px 12px', borderRadius: 10,
            background: 'rgba(245,158,11,0.06)',
            border: '1px solid rgba(245,158,11,0.15)',
            fontSize: '0.8rem', color: 'var(--color-text-secondary)',
            marginBottom: 4,
          }}>
            ⚡ 스마트 라우팅이 씬 특성에 따라 최적의 모델을 자동 선택해요. 씬당 비용이 발생하며 해당 제공자에서 직접 청구됩니다.
          </div>

          {/* 스마트 라우팅 설명 */}
          <div className="card" style={{ marginBottom: 4 }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 700, marginBottom: 10 }}>🔀 스마트 라우팅</h3>
            {[
              // Veo 3.1 Fast 720p $0.10/초 × 6초 = $0.60 (공식 가격표 확인값)
              { cond: '대사/오디오 씬', model: '→ Veo 3.1', cost: '$0.60' },
              { cond: '동작·애니·스타일 씬', model: '→ Hailuo 2.3', cost: '$0.28' },
              { cond: '인물 클로즈업', model: '→ Kling 3.0', cost: '$0.42' },
              { cond: '그 외 일반 씬', model: '→ Seedance 2.0', cost: '$0.34' },
            ].map(r => (
              <div key={r.cond} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', padding: '5px 0', borderBottom: '1px solid var(--color-border)' }}>
                <span style={{ color: 'var(--color-text-secondary)' }}>{r.cond}</span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <span style={{ color: 'var(--color-brand-400)', fontWeight: 600 }}>{r.model}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>{r.cost}/씬</span>
                </div>
              </div>
            ))}
          </div>

          {paidProviders.map(p => <KeyProviderItem key={p.id} config={p} />)}
        </motion.div>
      )}

    </div>
  )
}
