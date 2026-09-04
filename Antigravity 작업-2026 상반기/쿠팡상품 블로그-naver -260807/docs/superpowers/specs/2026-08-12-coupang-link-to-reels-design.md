# 쿠팡 링크 → 릴스 자동 생성 설계

작성일: 2026-08-12
대상 프로젝트: `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807`

## 1. 배경과 목표

릴스 생성 엔진(`reels_generator.py`)과 실측 수집기(`coupang_live_collector.py`)는
이미 각각 동작한다. 2026-08-10에 실제로 15MB짜리 1080×1920 릴스가 생성됐다.

문제는 둘이 이어져 있지 않다는 점이다. `generate_product_reels_video(url)`는
URL에서 `product_id`만 뽑아 **로컬 DB를 조회**하고, 없으면 `ValueError`를 던진다.
즉 지금은 "골드박스에서 미리 수집해둔 상품"만 릴스가 된다.

**목표:** 대시보드에 쿠팡 상품 링크를 붙여넣으면 MP4와 업로드 문구 세트가 나온다.

## 2. 범위

**포함**
- 링크 입력 → 상세 수집 → 릴스 MP4 생성
- 수집 차단 시 수동 입력 폴백
- 상품 사진이 부족할 때 리뷰 첨부 사진으로 보충
- 업로드 문구 세트(제목 후보 3개 / 설명문 / 해시태그 / 대가성 고지)
- 상품평 데이터가 없을 때 허위 기본값이 영상에 실리는 기존 결함 수정

**제외**
- 유튜브·블로그 자동 업로드 (문구 생성까지만)
- 웹앱화, CLI 진입점 (`coupang_reels_flow`는 CLI에서도 호출 가능한 형태로 두되 이번에 만들지 않음)
- 골드박스 배치 수집 경로 변경

## 3. 구조

신규 2개, 수정 2개.

```
dashboard.py                [수정 — UI만]
  링크칸 + [🔗 링크로 릴스]
      ↓ 워커 스레드
coupang_reels_flow.py       [신규 — 오케스트레이터]
  resolve_product()   수집·판정·저장
  plan_photos()       사진 4장 선정 + 출처 라벨
  pick_concept()      컨셉 자동 선택
  build_from_product() 릴스 + 문구 생성
reels_caption.py            [신규 — 문구 세트 + 금지어 목록]
reels_generator.py          [수정 — 함수 추출 + 결함 수정]
coupang_live_collector.py   [수정 — 리뷰 이미지 추출 추가]
```

`dashboard.py`는 입력을 받아 호출하고 진행 로그를 찍는 껍데기만 담당한다.
분기 로직은 전부 `coupang_reels_flow.py`에 둔다. 이 모듈은 Tkinter를 임포트하지
않으므로 단위 테스트와 향후 CLI 재사용이 가능하다.

## 4. 모듈 계약

### 4.1 `coupang_reels_flow.py`

```python
@dataclass
class NeedsManual:
    reason: str        # 'blocked' | 'partial'
    detail: str        # 사용자에게 보여줄 설명
    prefilled: dict    # 확보한 값 (partial일 때 일부 채워짐)
    url: str
    product_id: str

@dataclass
class PhotoPlan:
    photos: list[str]           # 씬 0~3에 쓸 4개 (URL 또는 로컬경로)
    sources: list[str]          # 각각의 출처: 'gallery'|'vendor'|'review'|'derived'
    needs_confirm: bool         # 'review'가 하나라도 포함되면 True

@dataclass
class FlowResult:
    mp4_path: str
    caption: CaptionSet
    product: dict
    concept_id: str
    photo_plan: PhotoPlan
    warnings: list[str]

def resolve_product(url: str) -> tuple[dict | None, NeedsManual | None]
def plan_photos(product: dict) -> PhotoPlan
def pick_concept(product: dict, diag: dict) -> str
def build_from_product(product: dict, *, concept_id: str | None,
                       photos: list[str], affiliate_url: str | None) -> FlowResult
```

`resolve_product`는 예외 대신 `(product, None)` 또는 `(None, NeedsManual)`을 돌려준다.
차단은 예상되는 정상 경로이지 오류가 아니다.

### 4.2 `reels_caption.py`

```python
BANNED: tuple[str, ...]   # 영상·문구 공용 금지어
DISCLOSURE: str           # 대가성 고지 (고정 문자열)

@dataclass
class CaptionSet:
    titles: list[str]     # 3개
    description: str      # 고지문이 최상단에 포함된 상태
    hashtags: list[str]

def build(product: dict, diag: dict, affiliate_url: str) -> CaptionSet
def has_banned(text: str) -> str | None    # 걸린 단어 반환, 없으면 None
```

### 4.3 `reels_generator.py` 수정

현재 `generate_product_reels_video(product_id_or_url, concept_id)`의 DB 조회 이후
본체를 아래로 추출한다.

```python
def generate_from_product(product_info: dict, concept_id: str = "price_focus",
                          photos: list[str] | None = None) -> str
```

기존 함수는 DB에서 찾아 이 함수를 호출하는 래퍼로 남긴다.
**기존 호출부(대시보드 "부동산 릴스 영상 생성", 배치 경로)의 시그니처와 동작은 불변.**

## 5. 수집 판정 3갈래

`classify_detail()`이 이미 내놓는 판정을 그대로 분기로 쓴다.

| 판정 | 조건 | 동작 |
|---|---|---|
| `ok` | 가격 > 0 이고 이미지 ≥ 1 | `save_real_products()` 후 생성 진행 |
| `partial` | 제목은 있으나 가격 0 또는 이미지 0 | 확보한 값을 채운 `NeedsManual('partial')` |
| `blocked` | 제목 없음 (`'쿠팡!'` 등) | 빈 `NeedsManual('blocked')` |

`partial`을 통과시키지 않는 것이 중요하다. 하이드레이션이 덜 끝나면 제목만 오고
가격·이미지가 0으로 비는데, 그대로 만들면 "0원" 영상이 나간다.

DB 저장은 `ok`일 때만 한다. 저장 시 기존 UPSERT 가드(`CASE WHEN excluded.X>0`)와
이미지 병합(더 많은 쪽을 남김)을 그대로 탄다.

**수동 입력분은 DB에 저장하지 않는다.** 손으로 넣은 값이 실측 테이블에 섞이면
`is_real` 구분이 무의미해지고 가격 이력이 오염된다. 메모리에 남은 사고(상세 단독
실행이 목록 값을 0으로 밀어 167,700원 → 0, 리뷰 75,742 → 0)와 같은 종류의 위험이다.
수동 경로는 메모리상 dict로만 릴스를 만들고 끝낸다.

## 6. 사진 소스 우선순위

| 순위 | 출처 | 판별 | 비고 |
|---|---|---|---|
| 1 | 상단 갤러리 | `thumbnails/remote` | 이 상품 사진인 것이 확실 |
| 2 | 판매자 상세 | `vendor_inventory` | '판매자의 다른 상품'이 섞임 |
| 3 | **리뷰 첨부 사진** | (실측으로 확정) | 신규 |
| 4 | 메인 사진 크롭 파생 | — | 최후 수단 |

갤러리가 2장 이상이면 갤러리를 우선하는 기존 규칙은 유지한다.
4씬을 채우지 못할 때 3번이 들어가고, 그래도 모자라면 4번으로 떨어진다.

공통 필터(기존 유지):
- `image/displayitem/` 제외 (쿠팡 공통 광고 배너)
- 최소변 500px 미만 제외
- 중복 URL 제거

### 6.1 리뷰 사진 수집

`coupang_live_collector.py`의 상세 추출 JS(`detail_images`·`thumbnails`를 반환하는
부분)에 `review_images`를 추가한다.

- **이미 열려 있는 상세페이지 세션에서 리뷰 영역까지 스크롤**해 수집한다.
  리뷰 전용 API를 새로 호출하지 않는다 — 새 요청 패턴은 차단 위험을 올리는 반면,
  스크롤은 정상 사용자 행동이라 워밍업에 가깝다.
- **URL 패턴은 구현 첫 단계에서 실측으로 확정한다.** 갤러리 필터가
  `thumbnail\d*.coupangcdn.com/thumbnails/remote/\d+x\d+ex/`로 못박혀 있듯,
  리뷰 사진도 고유 경로가 있을 것이나 현재 미확인이다. 추측으로 박지 않는다.
- `hi_res()`(230x230 → 1000x1000 치환)가 리뷰 이미지에도 적용되는지 함께 확인한다.
  적용되지 않으면 500px 필터에서 대부분 탈락해 이 기능이 무의미해진다 (§12 리스크).
- 최대 12장까지만 담는다.

### 6.2 리뷰 사진 사용 확인 단계

`PhotoPlan.needs_confirm`이 `True`면 생성 전에 확인 창을 띄운다.
썸네일 미리보기 + 개별 체크박스, 기본값은 전부 체크.

리뷰 사진은 구매자가 찍은 것이라 **얼굴·집 내부·택배 송장**이 찍힌 경우가 흔하고,
쿠팡 이용약관은 쿠팡에 대한 이용허락이지 파트너스 활동자가 광고 영상에 재사용하는
것까지 보장하지 않는다. 또 **다른 색상·사이즈 옵션** 사진인 경우가 많다.

자동 판별(얼굴 인식 등)은 오탐이 더 위험하므로 넣지 않는다. 사람이 한 번 보고
빼는 이 단계가 저작권·초상권·옵션불일치를 동시에 거른다.

갤러리만으로 4씬이 채워지면 이 창은 뜨지 않는다.

체크를 전부 해제하면 리뷰 사진 없이 진행한다 — 빈 자리는 4순위(크롭 파생)로 채운다.
남은 사진이 0장이 되는 경우는 없다(1~2순위가 최소 1장은 있어야 `ok` 판정이므로).

## 7. 수동 입력 폴백

`NeedsManual`을 받으면 대시보드가 모달(Toplevel)을 띄운다.

| 필드 | 필수 | 없을 때 |
|---|---|---|
| 상품명 | ✅ | 진행 불가 |
| 현재가 | ✅ | 진행 불가 |
| 정가 | ❌ | 할인 표현 생략 (기존 `has_discount` 분기가 처리) |
| 상품평 수 | ❌ | 씬 2를 대체 구성으로 (§8) |
| 사진 1~4장 | ✅ 최소 1장 | 진행 불가 |

사진은 로컬 파일 선택 또는 이미지 URL 붙여넣기 둘 다 받는다.
`fetch_product_multi_images()`가 http(s) URL과 로컬 경로를 모두 받도록 확장한다
(로컬 경로는 다운로드 없이 바로 열되, 500px 규칙은 동일 적용).

`partial`인 경우 확보한 값을 미리 채워 띄운다.

파일명은 `reels_manual_{product_id}_{timestamp}.mp4`로 실측분과 구분한다.

## 8. 기존 결함 수정 — 허위 기본값

`reels_generator.py:222-223`이 현재 이렇다.

```python
rating = product_info.get("rating", 4.8)
review_cnt = product_info.get("review_count", 1200)
```

데이터가 없으면 **평점 4.8, 상품평 1,200개**가 기본값으로 들어가고, 씬 2가 이 값을
그대로 자막·나레이션에 싣는다("상품평이 1,200개 쌓인 상품입니다"). 존재하지 않는
숫자가 영상에 실린다. `CONCEPTS.review.hook_badge`의 하드코딩 "4.9"를 사실 기반으로
고쳤던 것과 같은 종류의 문제가 한 겹 더 남아 있었다.

**수정:**
- 기본값 제거 → `product_info.get("review_count") or 0`
- `build_estatereels_storyboard()` 안의 지역변수 `rating`은 어디서도 참조되지 않는
  죽은 코드이므로 삭제한다. `product_info['rating']` 필드 자체는 유지한다
  (§9의 컨셉 선택 규칙이 사용한다)
- 씬 2 구성을 데이터 유무에 따라 결정:

| 조건 | 씬 2 구성 |
|---|---|
| `monthly_buyers` 있음 | 기존대로 그 문구 |
| `review_count > 0` | "상품평 N개" |
| 위 둘 다 없고 `specs` 있음 | 스펙 첫 항목을 사실로 |
| 아무것도 없음 | 가격 사실로 (`정가보다 N원 낮음` / `현재가 N원`) |

기존 골드박스 상품 중 상품평 수가 실제로 0이던 건은 문구가 바뀐다. 의도된 변경이다.

## 9. 컨셉 자동 선택

`purple_cow.diagnose()`는 점수(0~4)와 훅 후보를 주지만 컨셉을 고르지는 않는다.
현재 컨셉은 항상 `price_focus`로 고정돼 있다. 아래 규칙으로 결정한다(위에서부터 먼저 맞는 것).

1. `monthly_buyers`가 있으면 → `bestseller`
2. `original_price > current_price` 이고 `discount_rate >= 20` → `price_focus`
3. `review_count >= 1000` 이고 `rating > 0`(상세에서 실측된 값) → `review`
4. `specs` 항목이 5개 이상 → `specs`
5. 그 외 → `price_focus`

대시보드 드롭다운에서 "자동"을 고르면 이 규칙이, 특정 컨셉을 고르면 그것이 쓰인다.
`diagnose()`의 훅 후보는 지금처럼 씬 0의 자막에 계속 사용한다.

## 10. 문구 세트

- **제목 후보 3개** — 검증된 훅 공식 `[훅] │ [숫자·배지] │ [상품명]`
  (EstateReels `hooks.ts`의 오프라인 템플릿 방식 이식)
- **설명문** — 고지문 + 훅 + 데이터에서 나온 사실 3줄 + 파트너스 링크
- **해시태그** 8~12개 — 카테고리·브랜드·상품명 기반
- **금지어 가드** — 현재 `reels_generator.py:359-361`에 인라인으로 박힌 `_ban` 목록
  (역대급/절호의 기회/품절 임박/NO.1/최저가/1위 등)을 `reels_caption.BANNED`로 옮기고
  `reels_generator`가 이를 임포트해 쓴다. 지금은 영상에만 적용되고 문구에는 없다.
- **대가성 고지 강제** — 설명문 최상단에 아래를 삽입하고 제거 경로를 두지 않는다.

  > 이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.

- **파트너스 링크** — 입력되면 사용하고 `set_affiliate_link()`로 저장한다.
  비어 있으면 원본 URL을 쓰되 결과창에 경고를 띄운다(수수료가 붙지 않는 링크이므로).

## 11. 대시보드 UI

쿠팡 탭 액션카드 위에 한 줄 추가한다.

```
[쿠팡 상품 링크 ________________]  [파트너스 링크(선택) ______]  [컨셉 ▼ 자동]  [🔗 링크로 릴스]
```

- 수집에 30~60초 걸리고 **Playwright 창이 실제로 떠야 한다**(headless 금지).
  진행 상황은 기존 `self._log`로 흘리고 버튼은 작업 중 잠근다.
- UI 갱신은 기존 `self.after(0, ...)` 패턴을 따른다 (워커 스레드에서 위젯 직접 조작 금지).
- 완료 시 결과창: 저장 경로 + 문구 3종 textarea + 각 복사 버튼 + 경고 목록.

## 12. 오류 처리와 리스크

| 상황 | 처리 |
|---|---|
| 쿠팡 URL이 아님 | 입력 즉시 검증, `parse_product_url`의 `ValueError`를 메시지로 |
| 상세 차단 | `NeedsManual` → 폴백창 (오류 아님) |
| 사진 0장 | 생성 거부. 플레이스홀더 카드로 만들지 않는다 |
| TTS 실패 | 기존 edge-tts → gTTS 폴백 유지. 둘 다 실패면 무음 대신 생성 실패 |
| MoviePy 내보내기 실패 | 기존대로 예외 전파, 대시보드가 로그·메시지박스 |

**리스크**

1. **리뷰 이미지 URL 패턴 미확정.** 실측 전까지 §6.1은 구현할 수 없다. 첫 작업 항목이다.
2. **리뷰 이미지 해상도가 500px 미만일 가능성.** `hi_res()` 치환이 안 먹으면 전부
   탈락해 기능이 무의미해진다. 그 경우 리뷰 사진에 한해 하한을 낮출지 별도 판단이 필요하다.
3. **차단 빈도.** 상세 접근이 자주 막히면 수동 폴백이 사실상 기본 경로가 된다.
   그렇게 되면 링크 입력의 이점이 줄어들므로, 실사용 후 재검토한다.
4. 리뷰 영역까지 스크롤하면 체류 시간이 늘어 차단 위험이 소폭 오를 수 있다.

## 13. 검증 계획

1. **E2E(수집 성공)** — 실제 링크 1건으로 MP4 + 문구 생성, 영상 육안 확인
2. **차단 경로** — `COUPANG_DETAIL_BACKEND`로 강제 실패시켜 폴백창 동작 확인
3. **리뷰 사진 경로** — 갤러리가 1~2장뿐인 상품으로 3순위가 실제로 채워지는지,
   확인 창이 뜨고 체크 해제가 반영되는지
4. **단위 테스트** (`test_reels_flow.py`, 기존 `test_parser.py` 옆)
   - 금지어 가드 (`has_banned`)
   - 상품평 없을 때 씬 2 대체 구성 (§8 표의 4가지 분기)
   - 사진 우선순위 정렬 (`plan_photos`)
   - 컨셉 선택 규칙 (§9의 5분기)
   - `NeedsManual` 판정 3갈래
5. **회귀** — 기존 "부동산 릴스 영상 생성" 버튼과 골드박스 배치 경로가 그대로 동작
