# AutoAd — 통합 광고·접수 자동화 시스템

밴드·페이스북·카카오 자동광고 + AI 팜플렛 생성 + 소비자 접수 → 대출접수 파이프라인을
하나의 지휘부로 묶는 통합 시스템. 설계서: `설계서 아티팩트`(별도).

> **운영 원칙: 완전 무인 아님.** 대출광고 규제·플랫폼 ToS 때문에 목표는
> "승인 1클릭 반자동(human-in-the-loop)". 기본값은 전부 **DRY-RUN**.

## 현재 상태 — Phase 0 (스캐폴딩)

| 코드 | 파일 | 상태 |
|---|---|---|
| P0-1 | `config.py` · `.env.example` | ✅ 구현 — 시크릿 .env 일원화, 하드코딩 키 0 |
| P0-2 | `db.py` | ✅ 구현 — 신규 6테이블(channels·campaigns·creatives·posts·consumers·approvals) |
| P0-3 | `channels/base.py` | ✅ 구현 — `ChannelAdapter` 인터페이스 + `PostResult`/`Feedback` |
| P1-* | 그 외 모듈 | 🚧 스텁 (시그니처만, `TODO(P1-x)`) |

## 폴더 구조

```
autoad/
├─ config.py            시크릿·경로·안전장치
├─ db.py                공용 DB (신규 6테이블)
├─ orchestrator.py      캠페인→생성→승인→예약→발행 조율   (P1-8 스텁)
├─ profiler.py          채널 성향 태그                     (P1 스텁)
├─ scheduler.py         예약 발행 + JobStore               (P1-7 스텁)
├─ approval.py          승인 큐 + 텔레그램                 (P1-6 스텁)
├─ content/
│  ├─ copy_engine.py    카피 생성 (Claude)                 (P1-1 스텁)
│  ├─ pamphlet.py       PrintCraft 배경 + 텍스트 합성      (P1-2 스텁)
│  └─ prompts/          채널별 프롬프트 + 의무표기
├─ channels/
│  ├─ base.py           공용 인터페이스                    ✅
│  ├─ band.py           BandAutomator 래핑                 (P1-3 스텁)
│  ├─ facebook.py       FacebookAutomator 래핑             (P1-4 스텁)
│  └─ kakao.py          sender/crawler 래핑                (P1-5 스텁)
└─ intake/
   ├─ form.html         소비자 접수폼(동의)                ✅ 초안
   └─ bridge.py         폼 → /api/intake/register          (P1-9 스텁)
```

## 설치 & 초기화

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env      # 값 채우기 (특히 재발급한 GROQ_API_KEY)
python db.py                # DB 초기화 → data/autoad.db 에 6테이블 생성
python config.py            # 설정·미설정 시크릿 점검
```

## DB 배치

- 기본: 자체 `data/autoad.db` (신규 6테이블). 기존 대출 `kakao_crawl.db` 와 분리 → **안전**.
- 단일 DB 원하면 `.env` 의 `AUTOAD_DB` 를 대출앱 `kakao_crawl.db` 경로로 지정
  (신규 테이블은 additive라 기존 `crawled_messages`/`loan_records` 무손상).
- 접수는 DB 직접 쓰기가 아니라 대출앱 `POST /api/intake/register`(HTTP)로 연결 → 파이프라인 재사용.

## ⚠ 착수 전 필수

1. **노출 Groq 키 재발급** — `대출위젯-카카오/config.py:16` 하드코딩 키 폐기 후 재발급본을 `.env` 에.
2. 가동은 `GLOBAL_DRY_RUN=1` 로 시작 → 밴드부터 순차 점화.

## 다음 (Phase 1)

`content/copy_engine.py`(P1-1) → `content/pamphlet.py`(P1-2) → `channels/band.py`(P1-3) →
`approval.py`(P1-6) → `orchestrator.py`(P1-8) → `intake/`(P1-9) 순으로 밴드 1채널 end-to-end.
