# 소재 생성 전환 — Ollama + Stable Diffusion — 설계서

- 작성일: 2026-09-08
- 대상 프로젝트: `통합광고접수-AutoAd`
- 범위: **소재(캡션·이미지) 생성 엔진 교체 + 생성량 통제**. 발행 경로(Selenium/AHK)는 건드리지 않는다.

---

## 1. 목적

지금 AutoAd 의 외부 유료 API 는 **Gemini 하나**다. 캡션은 `gemini-flash-lite-latest`,
카드 이미지는 `gemini-3-pro-image`(`config.py:110`)를 쓴다. 이미지 쪽은 2026-08-14
운영자 지시로 잠겨 있다(`.env:113`, `IMAGE_GEN_LOCKED=1`) — 이유는 품질이 아니라
**과금**이다.

이 설계는 둘 다 대체한다.

```
캡션    Gemini            →  Ollama gemma4:31b-cloud
이미지  gemini-3-pro-image →  gemma4 가 SD 프롬프트 작성 → 로컬 Stable Diffusion
글자    AI 가 그림 안에 그림 →  Pillow 가 찍음 (한글 오타 원천 차단)
```

그리고 잠금을 푸는 것만으로는 **과금이 다시 폭주**하므로, 생성량 통제를 같이 넣는다.

### 결정 사항 (2026-09-08 협의)

| 항목 | 결정 |
|---|---|
| 캡션 엔진 | Ollama `gemma4:31b-cloud` (`COPY_PROVIDER=ollama` 신설) |
| 이미지 엔진 | 로컬 SD WebUI (`D:\sd-webui`, AUTOMATIC1111, DreamShaper_8) |
| 프롬프트 작성 | gemma4 가 영문 SD 프롬프트 + 네거티브를 생성 |
| 한글 | **전부 Pillow.** SD 는 글자를 그리지 않는다 |
| 소재 단위 | **상품 1개 × 한 바퀴 = 이미지 1장** (발행 1건당 1장 아님) |
| 생성 상한 | 하루 단위 예산(`IMAGE_DAILY_BUDGET`). 지금은 주기 단위뿐 |
| 되돌리기 | `CARD_ENGINE` / `COPY_PROVIDER` 값만 바꾸면 Gemini 로 복귀 |
| loan 업종 | **손대지 않는다.** 기성 전단(무료·의무표기 내장) 유지 |
| 격자 칸 수 | 고정값 폐기. **채널 규격에서 유도** — band·kakao 4장, facebook 2장 |
| 확산 통제 | **팬아웃 상한** `IMAGE_FANOUT_MAX=20`. 시간 분산이 아니다 |
| 생성 예산 | **엔진별로 분리** — SD 12/일, Gemini 2/일 |
| 체크포인트 | DreamShaper_8 **유지**. SDXL 은 재검토 조건 충족 시에만 |

### 명시적 비목표

- 발행 경로(밴드·페북 Selenium, 카카오 AHK) 변경
- 체크포인트 교체(SDXL/Flux) — 별도 검토. 이번엔 DreamShaper_8 로 간다
- 영상 업종(adstudio·오마주·memoryfilm)의 **프레임 캡처** 구현 — 후속 스펙
- 크롬 크래시(페이징 파일 부족) 복구 — 별개 작업이며 **선행되어야 한다**
- Anthropic/Groq 경로 제거 — 코드는 남긴다

---

## 2. 실측 근거 (2026-09-08 스파이크)

설계의 모든 수치는 이 PC 에서 직접 측정한 것이다. 버릴 코드로 3회 돌렸다.

| 항목 | 측정값 |
|---|---|
| SD 예열(첫 장) | **5.3초** — page-out 지연은 없었다 |
| gemma4 프롬프트 생성 | **2.0 ~ 2.4초** |
| SD 768×768 / 30스텝 | **13.2 ~ 16.0초** |
| 결과물 격자 4장 | **54.1초** (1282×1374) |
| 한글 오타 | **0** (Pillow 렌더) |
| Gemini 비용 | **0원** |

### 현재 자산

```
활성 채널 370개  ─ band 184 · facebook 186 · kakao 0 · threads 0
  ad_policy 분포 ─ topic_only 237 · unknown 124 · allow 9
                    → 361개(97.6%)가 '콘텐츠형 격자'를 원한다
활성 업종 12종   ─ + profile_key 가 빈 채널 7개(아래 ⚠)
보유 이미지 351장 ─ adstudio 83 · inkcraft 75 · printcraft 53 · mirizip 31
                    · proheadshot 25 · lifealbum 11 · weddingstudio 11 · colorcraft 3
showcase SPECS   ─ 3종만 등록(inkcraft · weddingstudio · lifealbum)
```

⚠ **활성 채널 7개에 `profile_key` 가 비어 있다.** `do_generate` 는
`profs = sorted(p for p in profs if p)` 로 빈 값을 걸러내므로 이 채널들은
**소재를 배정받지 못한다.** 이 설계의 범위는 아니지만, 재고 산수를 하기 전에
귀속을 채우거나 채널을 꺼야 한다.

**어제까지 만들던 '광고형 배너'는 채널 9개만 원하는 형태였다.** 이 설계가 뒤집는
가장 큰 전제가 이것이다.

---

## 3. 알려진 리스크

없앨 수 없고, 설계로 완화만 하는 것들.

1. **SD 는 지시를 자주 어긴다.** SD1.5 계열은 "어디를 비워라", "흰 배경만" 같은
   공간·배경 지시를 지키지 못한다. 스파이크에서 4장 중 1장이 흰 배경 대신 사진
   배경으로 나왔다. → **품질 게이트로 걸러 재시도**(§5.4).
2. **DreamShaper_8 은 인물 편향이 매우 강하다.** "노트북 화면의 편집 UI" 를 요구해도
   인물 사진을 낸다. → 네거티브를 **코드에서 강제 주입**(§5.3). LLM 출력에 맡기면 안 된다.
3. **SD 는 로컬 GPU·RAM 을 쓴다.** 이 PC 는 16GB 이고 발행 루프가 크롬을 3개 병렬로
   띄운다(`PARALLEL_PUBLISH=1`). 8/28·9/2 실패 로그가 "페이징 파일이 너무 작습니다",
   "can't start new thread" 다. → **이미지 배치는 발행 시간대 밖으로 분리**(§5.6).
4. **추상 배경은 서비스를 설명하지 못한다.** 그래서 배너를 기본형으로 두지 않고
   결과물 격자를 기본으로 한다(§4).
5. **Ollama cloud 는 외부 의존**이다. 끊기면 캡션·프롬프트가 모두 멈춘다.
   → 실패 시 기존 `_fallback_caption` 과 **재고 재사용**으로 버틴다.

---

## 4. 아키텍처 — 소재 3계층

`orchestrator.creative_form()`(`orchestrator.py:728`)이 이미 채널을 두 갈래로 나눈다.
이 설계는 그 갈래를 **채우는 쪽**이다.

| 채널 정책 | 소재 형태 | 무엇을 보여주나 | 대상 |
|---|---|---|---|
| `topic_only` · `unknown` (361개) | **결과물 격자** | 제품이 실제로 만든 결과물 4장 | 이미지 생성 업종 10종 |
| 〃 (영상 업종) | **도해 + 프레임** | 3단계 흐름 · 결과 영상 프레임 | adstudio·오마주·memoryfilm |
| `allow` (9개) | 광고형 배너 | 추상 배경 + 헤드라인 | 홍보 허용 그룹 |
| — | 기성 전단 | 인쇄된 전단 그대로 | loan |

**결과물 격자가 기본형이다.** `showcase.py` 의 설계 의도가 이미 그렇게 적혀 있다:

> *브랜드 카드(배너)는 어느 모임에서나 '광고'로 읽힌다. 주제 중심 모임에서는 그 자체로
> 규칙 위반이 되거나 승인 대기에 걸린다(실측). 반대로 제품이 만든 결과물은 그 모임의
> 주제에 맞는 내용이라 환영받는다.*

그리고 **이미지 생성 업종에서는 SD 출력물이 곧 제품 출력물**이다. 타투 도안 4장을
보여주면 "타투 도안을 만들어 준다" 는 설명이 필요 없다. 설명력 문제가 여기서 풀린다.

---

## 5. 컴포넌트 설계

### 5.1 config — 스위치 3개 신설

```python
# 캡션
COPY_PROVIDER = "gemini" | "claude" | "ollama"      # ollama 추가
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")

# 이미지
CARD_ENGINE   = os.getenv("CARD_ENGINE", "gemini")   # "gemini" | "sd"
SD_WEBUI_URL  = os.getenv("SD_WEBUI_URL", "http://127.0.0.1:7860")
SD_STEPS / SD_CFG / SD_SAMPLER

# 생성량
#  ⚠ 예산은 '목표'가 아니라 '천장'이다. 실제 생성량은 재고 목표치가 정하고,
#    목표에 닿으면 need=0 이 되어 저절로 멈춘다.
#  ⚠ 엔진별로 나눈다. 하나로 두면 CARD_ENGINE=gemini 로 되돌리는 순간
#    같은 천장이 그대로 '과금'이 된다 — 롤백 스위치가 과금 스위치가 되어 버린다.
IMAGE_DAILY_BUDGET_SD     = int(os.getenv("IMAGE_DAILY_BUDGET_SD", "12"))
IMAGE_DAILY_BUDGET_GEMINI = int(os.getenv("IMAGE_DAILY_BUDGET_GEMINI", "2"))
#  재고 목표는 상수를 따로 두지 않고 CREATIVE_COOLDOWN_DAYS 에서 유도한다(§5.7).
IMAGE_FANOUT_MAX   = int(os.getenv("IMAGE_FANOUT_MAX", "20"))    # §5.6

def image_daily_budget() -> int:
    return (IMAGE_DAILY_BUDGET_SD if CARD_ENGINE == "sd"
            else IMAGE_DAILY_BUDGET_GEMINI)
```

`SHOWCASE_TILES` 는 **고정값을 폐기**하고 채널 규격에서 유도한다(§5.5).

**기존 Gemini 경로를 지우지 않는다.** SD 품질이 기대에 못 미치면 `.env` 한 줄로
되돌아갈 수 있어야 한다.

### 5.2 `copy_engine._call_ollama()`

`copy_engine.py:885` 의 디스패치에 한 갈래를 더한다.

```python
def _call_llm(prompt):
    if config.COPY_PROVIDER == "ollama": return _call_ollama(prompt)
    return _call_gemini(prompt) if config.COPY_PROVIDER == "gemini" else _call_claude(prompt)
```

- `POST {OLLAMA_URL}/api/generate`, `{"format": "json", "stream": false}`
- **요청·응답 모두 명시적 UTF-8**(§6-①)
- 응답 파싱은 관대한 파서(§6-②)
- 금칙어(`{banned}`)·업종 주입은 기존 프롬프트 자리표시자를 그대로 쓴다 — 손댈 것 없음

### 5.3 `content/sd_backend.py` (신규)

```python
NEG_FORCE = ("person, people, woman, man, face, portrait, human, hands, body, skin, "
             "text, letters, words, korean text, watermark, signature, typography, "
             "logo, caption, ui, numbers")

def build_prompt(brief, channel, form) -> dict      # gemma4 페르소나 → {prompt, negative}
def txt2img(prompt, negative, w, h) -> Image        # SD WebUI /sdapi/v1/txt2img
def warmup() -> float                               # 첫 장 지연 방지
def is_clean_white(img) -> bool                     # 품질 게이트(§5.4)
def gen_tile(prompt, retries=2) -> Image            # 게이트 통과할 때까지 재시도
```

`build_prompt` 의 페르소나에는 **네 가지를 반드시 넣는다**(스파이크에서 확인):

1. 주제는 반드시 브리프에서 나올 것 — 일반 광고 이미지로 대체 금지
2. 네거티브에 글자·인물 금지 어휘 전부 포함
3. 여백 지시(`generous negative space`)와 **어느 쪽**을 비울지 명시
4. 과장 표현(폭발 그래프·트로피·1등 배지) 금지

`NEG_FORCE` 는 **LLM 이 무엇을 내놓든 코드가 뒤에 덧붙인다.** 모델이 빠뜨릴 수 있고,
실제로 1차 스파이크에서 인물 금지가 없어 인물 사진이 나왔다.

### 5.4 품질 게이트 — 이번 스파이크의 핵심 산출물

Gemini 는 배경 지시를 잘 지켜서 게이트 없이 돌아갔다. **SD 는 아니다.**

```
tile 생성 → 가장자리 4변의 밝기 검사 → 흰색 아니면 버리고 재시도(최대 2회)
                                    → 3회 실패하면 그 타일만 건너뛴다
```

- 판정 기준: 상하좌우 테두리 밴드의 평균 밝기와 분산. `showcase._fit_tile` 의
  '잉크 탐지' 와 같은 계열이라 그 코드 옆에 둔다.
- 실패율 25%(스파이크 실측)여도 재시도 비용은 **13초**뿐이다.
- 배너형에는 적용하지 않는다(배경이 흰색일 필요가 없다).

### 5.5 `showcase.SPECS` 확장

지금 3종뿐이다. 이미지 생성 업종 전체로 넓힌다.

```
등록됨(3)        inkcraft(채널 8) · weddingstudio(1) · lifealbum(1)
먼저 추가(7)     printcraft(50) · mirizip(26) · proheadshot(18)
                 · colorcraft(1) · petportrait(1) · wallpreview(1) · nailpreview(1)
나중(2)          stickerme · photomagic  ← 지금 활성 채널이 0개다
```

**채널 수가 많은 순으로 한다.** printcraft·mirizip·proheadshot 셋이 활성 채널
94개를 덮으므로, 이 셋만 끝내도 콘텐츠형 대상의 대부분이 커버된다.
stickerme·photomagic 은 발행할 곳이 없으므로 채널을 등록한 뒤에 쓴다
(스파이크는 stickerme 로 했는데, 이는 '채널 없는 업종도 SPECS 작성이 가능한가'를
확인한 것이지 우선순위가 높아서가 아니다).

- 한 칸 ≈ **35줄**(styles 4 + motifs 6). 스파이크에서 stickerme 로 실제 작성해 확인.
- **작성 시 프로필의 `compliance.note` 를 반드시 반영한다.** 예: stickerme 는
  "타 IP·캐릭터 연상 표현 금지" 라 모티프에 기존 캐릭터를 연상시키는 것을 넣지 않는다.
- 초안은 업종별 홍보서 PDF(`content/templates/광고홍보서/`, 14종 보유)를 gemma4 에게
  읽혀 뽑고 **사람이 검수**한다.
- `showcase._gen_one` 은 `CARD_ENGINE` 에 따라 Gemini/SD 로 분기한다.

**칸 수는 채널 규격이 정한다.** 격자 코드가 `cols = min(n, 2)` 라서 칸 수가 곧
결과물의 비율을 결정한다 — 고정값 하나로 둘 수 없다.

| 칸 수 | 격자 | 결과 비율 | 맞는 채널 |
|---|---|---|---|
| 2 | 2×1 | 1282×740 (가로 1.73) | facebook 1200×630 (1.90) |
| 4 | 2×2 | 1282×1374 (세로 0.93) | band·kakao 1080×1080 (1.00) |

```python
def tiles_for(channel_platform) -> int:
    w, h = config.CHANNEL_SPECS.get(channel_platform, (1080, 1080))
    return 2 if w / h >= 1.5 else 4      # 가로형이면 2×1, 아니면 2×2
```
SD 기준 4장이 54초, 2장이 27초다. 비용은 0이므로 시간만 보면 된다.

### 5.6 소재 단위 재정의 + 생성 예산

**지금 코드는 발행 1건마다 이미지 1장을 쓴다.** 세 곳이 그렇게 강제한다.

| # | 위치 | 지금 | 바꿀 것 |
|---|---|---|---|
| 1 | `db.image_cooldown_left(path, days)` (`db.py:411`) | 이미지 **전역** 쿨다운 | **(이미지 × 채널)** 단위 |
| 2 | `orchestrator._claimed_images()` (`:514`) | 대기 소재가 그림 독점 | 같은 바퀴 안에서는 공유 허용 |
| 3 | `orchestrator._used_paths` | 실행 내 재사용 금지 | 바퀴 단위로 1장 배정 |

**"한 바퀴"의 정의** — 한 상품(`profile_key`)에 대해 `run_campaign` 이 한 번 도는 것.
그 실행에서 만들어지는 창작물 전부가 **같은 `image_path` 를 공유**한다.
식별자는 `creatives` 에 신설하는 `round_id`(캠페인 실행 시각 기반 UUID)로 하고,
쿨다운·독점 판정은 `(image_path, channel_id)` 와 `round_id` 두 축으로 본다.
`round_id` 없이 "같은 캠페인" 으로만 묶으면, 캠페인을 두 번 돌렸을 때 두 바퀴가
한 덩어리로 보여 그림이 재사용되지 않는다.
| 4 | 발행 게이트 (`orchestrator.py:1368`) | 전역 쿨다운 재검사 | 1번과 같은 규칙 |

쿨다운을 방 단위로 좁히는 근거는 `.env` 주석에 이미 있다 —
*"매 건 다른 문구로 나가고, 그림도 쿨다운 때문에 같은 것이 다시 쓰이지 않는다 —
**'같은 방에 같은 글'이 아니다**"*. 목적 자체가 **같은 방**에서의 반복 방지였고,
전역으로 건 것은 구현 편의였다.

바꾼 뒤의 산수:

```
상품 12종 × 하루 1바퀴          = 하루 12장 소모, 363건 발행
쿨다운 14일 → 상품당 14장이면 무한 순환
필요 재고 = 12 × 14           = 168장
현재 재고                      = 351장   ← 이미 충족(총량 기준)
→ 정상 운영 시 신규 생성 0장. 하루 1장은 '신선도 교체분'
```

⚠ **총량은 충분해도 업종별로는 편중돼 있다.** 그래서 하루 예산의 배분은 총량이
아니라 **업종별 부족분** 을 봐야 한다(아래 배분 규칙).

| 업종 | 보유 | 목표 14 대비 부족 |
|---|---:|---:|
| inkcraft 75 · printcraft 53 · mirizip 31 · proheadshot 25 | 충분 | 0 |
| weddingstudio | 11 | 3 |
| lifealbum | 11 | 3 |
| colorcraft | 3 | 11 |
| petportrait · wallpreview · nailpreview | 0 | 각 14 |
| **부족분 합계** | | **59장** |

SD 로 하루 12장씩이면 **5일이면 채워진다.** 그 뒤로는 생성이 0 으로 수렴한다.

그리고 생성 상한을 **주기 단위에서 하루 단위로** 옮긴다. 지금은
`per_cycle_cap()`(`tools/auto_loop.py:188`)뿐이라 10분 주기 × 하루 144주기가 곱해진다.

```python
need = min(room, free_ch, plat_cap, remaining_image_budget_today()) - have
```

배분은 **재고가 가장 모자란 상품 우선**, 동률이면 가장 오래 안 만든 상품(라운드로빈).
`per_cycle_cap` 의 `min_n` 바닥값(2026-08-14 사고 대응)은 그대로 둔다.

### 5.7 팬아웃 상한 — 같은 그림이 몇 방에 뿌려지나

한 바퀴에 그림 1장이면 adstudio 는 **페북 그룹 66곳에 같은 그림**이 하루에 나간다.
플랫폼이 가장 빨리 잡는 패턴이다.

**시간 분산(한 바퀴를 2~3일에 걸쳐 돌기)은 이 문제를 못 고친다.** 노출 속도만 늦출 뿐
'같은 그림이 66곳에 남아 있다' 는 사실은 그대로고, 플랫폼이 보는 것은 속도가 아니라
콘텐츠 지문이다. (시간 분산은 이미 `POST_INTERVAL` 90~300초가 하고 있다.)

그래서 **위험의 원인을 직접 제한한다.**

```python
IMAGE_FANOUT_MAX = 20                      # 그림 1장이 덮는 채널 수 상한
images_per_round = ceil(enabled_channels(profile) / IMAGE_FANOUT_MAX)
stock_target     = images_per_round * CREATIVE_COOLDOWN_DAYS
```

⚠ **재고는 업종이 아니라 (업종 × 플랫폼) 단위다.** 파일명이
`showcase_{업종}_{플랫폼}_v{n}.png` 라 밴드용 그림과 페북용 그림은 서로 다른 재고다.
따라서 `n_imgs` 와 풀도 **플랫폼마다 따로** 산정해야 한다 — 전체 채널 수로 한 번만
계산해 모든 플랫폼에 같은 값을 쓰면, 소수 플랫폼이 필요보다 2~4배 많은 그림을 쓴다
(2026-09-08 Task 8 리뷰에서 발견. 이 문서의 이전 판이 프로필 단위로만 세어 틀렸다).

플랫폼 단위 실측:

| 업종 | 플랫폼 | 채널 | 라운드당 | 필요 | 보유 | 부족 |
|---|---|---:|---:|---:|---:|---:|
| adstudio | facebook | 66 | 4 | 56 | 73 | 0 |
| printcraft | facebook | 40 | 2 | 28 | 53 | 0 |
| mirizip | facebook | 15 | 1 | 14 | 7 | **7** |
| mirizip | band | 11 | 1 | 14 | 24 | 0 |
| printcraft | band | 10 | 1 | 14 | **0** | **14** |
| proheadshot | band | 9 | 1 | 14 | 21 | 0 |
| proheadshot | facebook | 9 | 1 | 14 | 4 | **10** |
| adstudio | band | 8 | 1 | 14 | 10 | **4** |
| inkcraft | facebook | 8 | 1 | 14 | 73 | 0 |
| colorcraft | facebook | 1 | 1 | 14 | 3 | **11** |
| lifealbum · weddingstudio | band | 각 1 | 1 | 각 14 | 각 11 | 각 **3** |
| nailpreview · petportrait · wallpreview | facebook | 각 1 | 1 | 각 14 | **0** | 각 **14** |
| **합계** | | | | **266** | | **94** |

**부족 94장 = SD 로 20분.** 하루 예산 12장이면 8일에 채워지고 그 뒤 0 으로 수렴한다.

⚠ 눈에 띄는 구멍: `printcraft/band` 는 채널이 10개인데 재고가 **0장**이고,
`nailpreview`·`petportrait`·`wallpreview` 의 facebook 도 전부 0장이다. 이 업종들은
SPECS 는 갖췄지만 그 플랫폼용 그림을 한 번도 만든 적이 없다.

⚠ **20 이라는 값의 근거.** 10 으로 조이면 adstudio 가 `ceil(74/10)=8 × 14 = 112장`
필요한데 83장뿐이라 부족해진다. 20 은 **지금 재고로 감당되는 가장 강한 상한**이다.
재고가 늘면 낮출 수 있고, 낮출수록 안전하다.

---

## 6. 반드시 지킬 함정 6가지

스파이크에서 **전부 실제로 밟았다.** 하나라도 빠지면 같은 자리에서 다시 터진다.

**① PowerShell 로 Ollama 를 부르지 않는다.**
한글이 mojibake 로 깨져 브리프가 통째로 무시됐다. "AI 광고영상 서비스" 를 넣었는데
**화장품 세럼 제품샷**이 나왔다. Python + 명시적 UTF-8 로 바꾸자 즉시 정상 인식했다.
`json.dumps(..., ensure_ascii=False).encode("utf-8")` + `charset=utf-8` 헤더.
→ [[windows-bat-codepage-trap]] 과 같은 뿌리다.

**② `format:"json"` 을 줘도 코드펜스로 감싸 온다.**
실제로 파서가 터졌다. 첫 `{` 부터 마지막 `}` 까지 떼어 읽는 관대한 파서를 쓴다.

**③ SD1.5 는 "어디를 비워라" 를 못 지킨다.**
gemma4 는 지시대로 `generous negative space in the upper third` 를 넣었는데 SD 가
무시했다. 반투명 그라데이션으로 덮어도 얼굴이 비쳐 헤드라인이 눈·이마를 관통했다.
→ **여백은 Pillow 가 불투명 패널로 확보한다.** SD 에 맡기지 않는다.

**④ 인물 금지는 코드가 강제한다.**
`NEG_FORCE` 를 LLM 출력 뒤에 항상 덧붙인다. 모델이 빠뜨릴 수 있다.

**⑤ 흰 배경은 게이트로 확인한다.**
`pure white background` + 네거티브 `photo background` 를 넣고도 사진 배경이 나왔다
(4장 중 1장). 프롬프트만 믿지 않는다.

**⑥ SPECS 는 컴플라이언스와 함께 쓴다.**
프로필의 `compliance.note`·`banned_phrases` 를 보지 않고 모티프를 지으면
타 IP 연상·과장 표현이 그대로 나간다.

추가로 기존 코드가 이미 남겨 둔 교훈 하나 — `pamphlet.py:356`:
> *"채팅 UI 등 잔글씨가 많은 목업은 만들지 마세요. 뭉개져서 못 씁니다.
> 목업 안에 텍스트가 필요하면 글자 없이 도형·아이콘으로 표현하세요."*

**AI 에게 UI 를 그리게 하지 않는다.** 그 자리는 Pillow 도해가 대신한다.

---

## 7. 되돌리기

| 되돌릴 것 | 방법 |
|---|---|
| 캡션을 Gemini 로 | `.env` `COPY_PROVIDER=gemini` |
| 이미지를 Gemini 로 | `.env` `CARD_ENGINE=gemini` |
| 생성 전면 중지 | `.env` `IMAGE_GEN_LOCKED=1` (기존 게이트 유지) |
| 생성량만 조이기 | `.env` `IMAGE_DAILY_BUDGET=1` |
| 소재 단위 원복 | 쿨다운 스코프 플래그를 `global` 로 |

**기존 경로를 삭제하지 않는 것이 이 설계의 전제다.**

---

## 8. 테스트

- `sd_backend.is_clean_white()` — 흰 배경/사진 배경 샘플로 판정 경계 확인
- `_call_ollama()` — 한글 왕복(mojibake 회귀 방지). **이 테스트가 함정 ①의 재발을 막는다**
- 관대한 파서 — 코드펜스 있는/없는 응답 둘 다
- 쿨다운 스코프 — 같은 이미지가 **다른 방**에는 나가고 **같은 방**에는 안 나가는지
- 하루 예산 — 예산 소진 후 `do_generate` 가 0을 반환하는지
- 회귀: `CARD_ENGINE=gemini` 로 두면 기존 동작과 **완전히 동일**한지

---

## 9. 구현 순서

선행 조건이 하나 있다. **크롬 크래시(페이징 파일 부족)를 먼저 고쳐야 한다.**
그것 없이는 소재를 만들어도 나갈 곳이 없다(2026-08-26 이후 발행 0건).

1. 운영 폴더 확정 — 낡은 사본(`D:\Antigravity 작업-2026 상반기\...`)에서 도는
   service.py 3종을 내리고 라이브 사본으로 갈아탄다
2. PC 환경 복구 — 가상메모리 확대, 크롬/드라이버 정합, 고아 크롬 정리
3. 소재 경로 1,448건 일괄 치환(옛 PC 경로 → 현재 폴더)
4. **§5.6 소재 단위 재정의** — 이것만으로 재고 351장이 무한 순환에 들어간다
5. **§5.1~5.2 Ollama 캡션** — Gemini 캡션 과금 종료
6. **§5.3~5.4 SD 백엔드 + 품질 게이트**
7. **§5.5 SPECS 확장** — 업종당 20~30분
8. 영상 업종 도해·프레임 캡처 — 후속 스펙

4·5 는 서로 독립이라 순서를 바꿔도 된다. 6 은 4 가 끝난 뒤가 안전하다
(재고가 순환에 들어가면 생성 압력이 낮아져 실패해도 광고가 안 멈춘다).

---

## 10. 결정 완료 (2026-09-08 운영자 승인)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 1 | 격자 칸 수 | **규격에서 유도** — band·kakao 4, facebook 2 | 칸 수가 비율을 정한다(§5.5). SD 라 비용 0 |
| 2 | 확산 통제 | **팬아웃 상한 20** (시간 분산 아님) | 시간 분산은 지문을 못 줄인다. 상한은 원인을 직접 막고 큰 업종은 재고가 이미 충족(§5.7) |
| 3 | 생성 예산 | **SD 12/일 · Gemini 2/일 분리** | 하나로 두면 롤백이 곧 과금이 된다(§5.1) |
| 4 | 체크포인트 | **DreamShaper_8 유지** | 아래 |

### 체크포인트를 유지하는 이유

실측: **RTX 4060 · VRAM 8,188 MiB · 사용 중 2,832 MiB(여유 약 5.3GB)**.
(Windows `Win32_VideoController` 는 4GB 로 보고하지만 그 API 의 상한일 뿐이다.)

SDXL 이 기술적으로 불가능하지는 않으나 여유 5.3GB 는 빠듯하고, 셋을 더 본다.

1. **이 PC 는 이미 메모리 부족으로 크롬을 죽이고 있다**(8/28 `can't start new thread`,
   9/2 "페이징 파일이 너무 작습니다"). 광고가 안 나가는 원인을 고치기 전에 무게를 더하지 않는다.
2. **용도가 SD1.5 의 강점과 겹친다** — 스티커·타투 도안·컬러링은 전부 플랫 일러스트다.
   스파이크에서 4장 중 3장이 바로 쓸 수준이었다.
3. **나머지 1장은 13초 재시도로 해결된다.** 품질 게이트가 6.5GB 다운로드보다 싸다.

**재검토 조건** — 둘 중 하나가 성립하면 SDXL 을 다시 검토한다.
- 품질 게이트 재시도율이 **30% 를 지속적으로** 넘을 때
- PC 메모리 문제 해결 후, 영상 업종 도해에 **사진급 배경**이 필요해질 때

---

## 11. 남은 미결정 — 이 설계 범위 밖

| 항목 | 내용 |
|---|---|
| 대부업 광고 번호 | 등록증 기재 010-7697-5684 vs 실제 광고 010-2577-2679. 변경등록 확인 전까지 **loan 은 현행 유지**(이 설계가 loan 을 건드리지 않으므로 영향 없음) |
| 귀속 없는 채널 7개 | `profile_key` 가 빈 활성 채널. 소재를 배정받지 못한다(§2). 귀속을 채우거나 채널을 끈다 |

---

## 부록 — 스파이크 산출물

`%TEMP%\claude\spike-sd\` (버릴 파일)

| 파일 | 내용 |
|---|---|
| `card_adstudio_band.png` | 1차 — 인물이 나오고 헤드라인이 얼굴에 겹침(실패 사례) |
| `card_v2.png` | 2차 — 인물 금지 + Pillow 여백. 배너형 성공 사례 |
| `showcase_stickerme.png` | 3차 — 결과물 격자. 4장 중 1장이 흰 배경 위반(게이트 필요 근거) |

관련: [[loan-widget-kakao-sender]] · [[sd-false-death-trap]] · [[windows-bat-codepage-trap]]
· `docs/superpowers/specs/2026-08-03-threads-reply-ad-design.md`
