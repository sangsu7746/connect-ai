# AutoAd — 인수인계 (STATUS)

> 밴드·페이스북·카카오 자동광고 + AI 팜플렛(전단 재사용) + 소비자 접수 → 대출프로그램 자동등록 **통합 시스템**.
> 위치: `D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd\` · 최종갱신 2026-07-24
> 설계서: claude.ai/code/artifact/720a2e63-9c84-4501-97e4-559cba6fdaa0
> 운영 원칙: **완전 무인 아님 — "승인 1클릭 반자동".** 기본값 전부 DRY-RUN(`GLOBAL_DRY_RUN=1`).

---

## 1. 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| P0 | 기반: `config.py`·`db.py`(6테이블)·`channels/base.py`(ChannelAdapter) | ✅ 검증 |
| P1-1 | `content/copy_engine.py` — 캡션 생성 + 금칙어 가드 · **provider 전환(gemini/claude)** | ✅ Gemini 라이브(무료티어) · 목 6/6 |
| P1-2 | `content/pamphlet.py`+`registry.py` — 더스틴홀딩스 전단 재사용/프로모 오버레이 | ✅ 실물 PNG |
| P1-8 | `orchestrator.py` — 캠페인→성향라우팅→전단+캡션→승인큐→승인→발행(dry) | ✅ 드라이런 |
| P1-9 | `app.py`+`intake/` — 접수폼→동의→대출DB 등록 (**요구사항 6**) | ✅ 종단(스텁) |
| P1-6 | **웹 승인 콘솔** `/approvals` + `approval.py` | ✅ 웹 검증(브라우저) · 텔레그램 경로는 코드완성(토큰 필요) |
| P3 | **운영 대시보드** `/dashboard` + `stats.py` | ✅ 집계 정확도 대조 + XSS 하드닝 검증 |
| P3 | **준비 상태 패널** — 대시보드 상단에 7개 항목 상시 표시 | ✅ `stats.readiness()` (30초 캐시) |
| P1-7 | `scheduler.py` — APScheduler+JobStore · 웹서버 lifespan 통합 | ✅ 검증(firing·재시작복구·승인전용) |
| P1-3 | `channels/{band,facebook,kakao}.py` — 3채널 실발행 어댑터 + 3중 안전장치 | ✅ dry-run 검증(3채널 동시) (실게시=계정/카톡창+`GLOBAL_DRY_RUN=0`) |
| P1-10 | **상시 구동** `service.py` — 3개 프로세스 감독·자동재시작·로그 | ✅ `--once` 3/3 기동 검증 (등록은 `--install`) |

**검증된 전체 흐름 (크레딧·계정 없이 실제로 동작):**
```
[광고]  캠페인 → 성향라우팅 → 전단+캡션 → 승인큐 → 승인 → 발행(dry)
[소비자] 팜플렛 QR(channel/utm) → 접수폼 → 동의 → 대출DB 등록 → 전환추적
```

---

## 2. 파일 지도

| 경로 | 역할 |
|---|---|
| `config.py` / `.env` | 시크릿(.env 일원화·`.strip()`)·경로·브랜드·안전장치. `COPY_MODEL=claude-sonnet-5` |
| `db.py` | `data/autoad.db` — channels·campaigns·creatives·posts·consumers·approvals |
| `orchestrator.py` | 지휘부: `run_campaign()`·`approve_and_publish()`·`seed_demo_channels()` |
| `app.py` | AutoAd 웹서버: `GET /intake`(폼)·`POST /api/intake/lead` |
| `content/copy_engine.py` | 캡션 생성(Claude, `_llm` 주입 가능)·`BANNED_PHRASES` 가드 |
| `content/pamphlet.py` | `render_from_template(상품,채널,promo)`(기본)·`render_pamphlet`(신규생성) |
| `content/registry.py` | 전단 라이브러리 17종(성향 태깅). `products()`·`get(key)`·`by_audience()` |
| `content/templates/flyers` `psd` | 더스틴홀딩스 전단 JPG 15 + PSD 17 (143MB) |
| `channels/{band,facebook,kakao}.py` | 채널 어댑터(스텁·dry-run 동작). 래핑대상=`페이스북-광고글/app`, 대출앱 `sender.py` |
| `intake/bridge.py`·`form.html` | 소비자폼 → `IntakeRegisterModel` 매핑 → 대출앱 register |
| `profiler.py`·`scheduler.py`·`approval.py` | P1 스텁 |

**상품 라우팅**: consumer→아파트/토지/임야/빌라후순위, business→공장/사업자/숙박/콜자금, mixed→종합/배너.
(전단 JPG 없는 2종=빌라다가구후순위·콜자금 → PSD 편집 P2.)

---

## 3. 실행 / 재개

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd"
pip install -r requirements.txt          # 최초 1회
python db.py                              # DB 초기화 → data/autoad.db
python config.py                          # 설정·미설정 시크릿 점검
python -m content.registry                # 전단 라이브러리 17종 확인
python -m uvicorn app:app --port 8010     # 접수 웹서버 → http://127.0.0.1:8010/intake
```
- 오케스트레이터 드라이런: `orchestrator.seed_demo_channels()` 후 `run_campaign({...}, copy_fn=목)` → `approve_and_publish()`.
- 팜플렛 1장: `python -c "from content import pamphlet; print(pamphlet.render_from_template('apart','band',promo='7월 이벤트'))"`

---

## 4. 사장님 액션 아이템

1. **Anthropic 크레딧 충전** (console.anthropic.com → Plans & Billing) — 충전 즉시 실제 카피 생성. *코드는 검증 완료, 크레딧 부족만 막힘.*
2. **Groq 키** — `.env`에 새 키 반영됨. 기존 노출 키(`대출위젯-카카오/config.py:16`)가 **콘솔에서 폐기**됐는지 확인.
3. `.env`에 **`TELEGRAM_TOKEN`** (P1-6 승인 콘솔용) / **`BRAND_REG_NO`**(대부중개 등록번호, 신규 전단 생성 시).
4. 실 발행 시 **부계정·발행량 하향·인간형 딜레이** (계정 정지 리스크 상수).

---

## 5. 핵심 결정 · 주의점

- **팜플렛 = 기존 전단 재사용 + 캡션 자동생성** (신규 AI생성 아님). 이미지는 프로 퀄리티·컴플라이언스 그대로, `copy_engine`은 **게시 문구(캡션)** 담당.
- **요구사항 6 연결점**: 소비자폼 → `app.py /api/intake/lead` → `bridge` → 대출앱 `POST {LOAN_API_BASE}/api/intake/register`. **실연결 = `.env`의 `LOAN_API_BASE`를 실대출앱으로** + 대출앱을 uvicorn 헤드리스 구동(현재 데스크톱 GUI). 검증은 실데이터 오염방지 위해 미러 스텁으로 함.
- **개인정보**: 주민번호 미수집, 동의 필수(없으면 400), consumers에 동의시각·utm 저장.
- **컴플라이언스**: 대부 광고 의무표기는 전단에 내장(재사용이 안전). 신규생성 시 의무표기 고정층·금칙어 가드 필수. 게시 전 사람 승인 유지.
- **브랜드**: (주)더스틴홀딩스대부중개 · ☎010-4649-5078 · 대구·경북·전국비대면 · 카톡·텔레그램.
- **환경**: python 3.14 · cp949 콘솔이라 로그 한글 깨져 보임(파일/DB는 UTF-8 정상). 설치됨=anthropic·Pillow·fastapi·uvicorn·httpx·requests.

---

## 6. 다음 재개 지점

**핵심 모듈 + 밴드·페북·카카오 3채널 어댑터 전부 dry-run 검증 완료.** 남은 건 전부 사장님 자원/결정:

**실발행 켜는 법(공통 → 채널별):**
- 공통: `.env`에서 `GLOBAL_DRY_RUN=0` (일일 상한 `DAILY_POST_LIMIT`·부계정·발행량 하향 권장)
- ✅ **접수폼 공개 완료** — https://headjim-loan.web.app (Firebase, `cloud/` 참조). `PUBLIC_BASE` 설정됨.
  - 리드는 Firestore `loanLeads`에 쌓이고, PC에서 `python cloud_sync.py --watch` 로 대출앱에 자동 등록됩니다.
  - **대출앱을 uvicorn으로 상시 구동**해야 최종 등록까지 완결됩니다.
- **밴드/페북**: 계정 자격증명 준비 → `BandAdapter()`/`FacebookAdapter().login({"password": "..."})` (2FA/캡차는 열린 크롬 창에서 직접 통과)
- **카카오**: 데스크톱 카톡 로그인 상태 + AutoHotkey(설치 확인됨) → 방 이름 검증 후 전송

**그 외 남은 것:**
- **P1-10 OS 자동시작** — 서버+스케줄러 lifespan 통합됨, Windows 작업스케줄러 등록만.
- 실 카피 = **Gemini 무료티어로 라이브 동작(기본, `COPY_PROVIDER=gemini`)**; Claude는 크레딧 시 선택(`=claude`). 모바일 승인 = `TELEGRAM_TOKEN` / **댓글·문의 수집(피드백 루프) = P2**.

**실가동 도구**: `python preflight.py`(준비 점검·읽기전용) · `python register_channels.py`(채널 등록) · [GO_LIVE.md](GO_LIVE.md)(단계별 런북·비상정지 포함).
preflight 판정(현재): 카피·팜플렛·밴드·페북·카카오 발행 전부 ✅ / 접수→대출만 ⚠(대출앱 uvicorn 미구동).

**상시 구동(권장)** — 3개를 한 번에 관리:
```bash
python service.py --status     # 지금 떠 있는지
python service.py --once       # 기동 검증 후 종료
python service.py --install    # 로그온 시 자동 실행 등록
python service.py              # 포그라운드로 상시 구동
```
감독 대상: ① AutoAd 서버(8010: 접수·승인·대시보드·스케줄러) ② 대출앱 서버(8000: 접수 종착점) ③ 클라우드 동기화(`cloud_sync --watch`).
죽으면 자동 재시작(백오프 5→120초), 로그는 `data/logs/{autoad,loanapp,sync,service}.log`.

수동 단일 실행: `python -m uvicorn app:app --port 8010` → 접수(`/intake`)·승인(`/approvals`)·**대시보드(`/dashboard`)**·예약 스케줄러.

> ⚠️ **8010 포트는 절대 외부에 열지 마세요.** `/api/dashboard` 는 인증이 없고 접수자 개인정보(이름·연락처)를 반환합니다.
> 소비자용 공개 창구는 Firebase(`headjim-loan.web.app`) 하나뿐이며, 이 서버는 **로컬 전용(127.0.0.1)** 으로 두는 것이 설계입니다.
→ 새 세션에서 **"댓글 피드백"(P2)**, 또는 **"AutoAd 이어서"**.
