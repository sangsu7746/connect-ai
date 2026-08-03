# 쓰레드 답글 자동광고 — 설계서 (1단계)

- 작성일: 2026-08-03
- 대상 프로젝트: `통합광고접수-AutoAd`
- 범위: **1단계 — 단일 계정 답글 파이프라인**. 계정 풀 확장(하루 100건↑)은 2단계 별도 스펙.

---

## 1. 목적

Threads 추천(For You) 피드의 글을 읽고, 그 글에 맞는 답글을 생성해 발행한다.
답글은 맥락 공감과 홍보를 한 덩어리로 담는 **1단 통합 답글**이며, 마지막에 자사
웹서비스로 유도하는 문구와 추적 링크가 들어간다.

기존 AutoAd 3채널(밴드·페북·카카오)이 **"내가 정한 곳에 내 글을 민다"(push)** 인 반면,
이 기능은 **"피드를 훑어 판정하고 반응한다"(pull)** 이다. 모양이 다르므로 기존
`ChannelAdapter` 계약에 끼우지 않고 별도 패키지로 만들되, 승인 큐·DB·대시보드·
컴플라이언스 가드는 전부 재사용한다.

### 결정 사항 (2026-08-03 협의)

| 항목 | 결정 |
|---|---|
| 광고 대상 | 자사 웹서비스 (photomagic / mirizip / inkcraft / memoryfilm / estate-reels 등) |
| 답글 구조 | 1단 통합 답글 (맥락 + 홍보 한 덩어리) |
| 타겟 선별 | 키워드 1차 필터 → LLM 2차 판정 |
| 승인 게이트 | 점수별 하이브리드 (고점수 자동 발행, 애매한 건 승인 큐) |
| 하루 볼륨 | 최종 목표 100건↑ → **1단계는 20건**, 계정 풀은 2단계 |

### 명시적 비목표 (1단계)

- 계정 풀·프록시 로테이션·계정 워밍업 (2단계)
- 대출(loan) 프로필 적용 — 대부업법 의무표기를 짧은 답글에 담을 수 없음
- 2단 셀프답글 구조 — 1단 통합으로 확정
- 답글에 대한 재답글 대응(대화 이어가기)
- 이미지 첨부 답글

---

## 2. 알려진 리스크

설계에 반영은 하되, 없앨 수는 없는 것들이다.

1. **공식 API 경로 없음.** Threads API는 자기 글 관리와 자기 글에 달린 답글 처리
   위주라, 추천 피드 순회와 제3자 글 답글에 해당하는 엔드포인트가 없다. 따라서
   브라우저 자동화가 유일한 수단이다.

   **스택은 Selenium** — 기존 `facebook_automator.py` 의 스텔스 설정
   (`navigator.webdriver` 은폐 · `excludeSwitches`), 계정별 쿠키 저장·복원,
   세션 자동 복구, 팝업 처리를 그대로 따른다. 스레드도 Meta라 같은 탐지 계열을
   받으므로, 실전에서 살아남은 설정을 버리고 새 스택으로 시작할 이유가 없다.
2. **밴 리스크가 기존 채널보다 높다.** 가입한 그룹에 내 글을 올리는 것과, 모르는
   사람 글에 홍보 답글을 다는 것은 Meta 기준에서 후자가 스팸 판정에 훨씬 가깝다.
   상한·간격·작성자 쿨다운을 보수적으로 잡는 이유가 이것이다.
3. **자동 발행 임계값이 미검증 상태다.** 점수 임계값은 골든셋 실측 전까지 근거가
   없다. 그래서 `AUTO_THRESHOLD`를 90으로 높게 시작하고, 자동 발행분 전용 일일
   상한을 따로 둔다.
4. **셀렉터 취약성.** threads.net DOM이 바뀌면 수집이 0건이 되거나 엉뚱한 곳에
   답글이 들어갈 수 있다. 3회 연속 0건이면 자동 강등한다.

---

## 3. 아키텍처

### 3.1 데이터 흐름

```
[수집]  harvester.harvest(account, limit=60)
        Selenium → threads.net 추천 탭 스크롤 → 글 카드 파싱
        → RawPost{url, author, text, posted_at, likes, replies}
        → db.threads_target_upsert()      ← post_url UNIQUE 로 재수집 자동 배제

[선별]  gate.screen(posts, profile) → Verdict{passed, score, reason, angle}
        1차 키워드(비용 0)
          · 프로필 관심 키워드 매칭
          · 하드블록(부고·사고·질병·정치·분쟁) 걸리면 즉시 탈락
        2차 LLM (1차 통과분만 배치)
          → {score: 0~100, reason, angle, safe}
          · angle = "이 글에 어떤 각도로 답해야 자연스러운가"
        → threads_targets.score / verdict / reason 갱신

[생성]  reply_writer.write(post, verdict, profile) → Reply{text}
        원글 + angle + 브랜드 + 추적링크 → 1단 통합 답글
        가드: copy_engine._find_banned / _find_leaks 재사용
             + 신규(길이·이모지 수·링크 1개·원글 인용 금지)
        → db.add_creative(kind="threads_reply", copy_json={...})

[분기]  runner.route(score)
        score >= THREADS_AUTO_THRESHOLD → 자동 발행 (자동분 일일 상한 내)
        score >= THREADS_GATE_THRESHOLD → db.enqueue_approval() → /approvals
        그 미만                          → 폐기 (verdict='dropped', 사유 기록)

[발행]  publisher.reply(post_url, text, dry_run)
        BaseAdapter 안전장치 통과 → Selenium 답글 작성
        → db.record_post / db.update_post_status(perm_url)
```

### 3.2 모듈 경계

패키지: `threads/`

| 모듈 | 공개 계약 | 브라우저 의존 | 테스트 방법 |
|---|---|---|---|
| `harvester.py` | `harvest(account, limit, headless) -> list[RawPost]` | 필요 | 저장된 HTML 픽스처 |
| `gate.py` | `screen(posts, profile, _llm=None) -> list[Verdict]` | **없음** | `_llm` 주입 |
| `reply_writer.py` | `write(post, verdict, profile, _llm=None) -> Reply`<br>`validate(text, profile) -> list[str]` | **없음** | `_llm` 주입 |
| `publisher.py` | `ThreadsPublisher(BaseAdapter)`<br>`.login()` / `.reply(url, text, dry_run)` / `.delete_reply(url)` | 필요 | dry-run |
| `runner.py` | `run_once(account, profile) -> dict` | 간접 | 위 4개 목킹 |

`gate.py`와 `reply_writer.py`가 브라우저를 전혀 모르는 것이 이 설계의 핵심이다.
계정도 로그인도 없이 저장된 샘플 글로 "이 글을 통과시키는가 / 뭐라고 답하는가"를
반복 검증할 수 있다. 이 시스템에서 유일하게 예측 불가능한 부분이 그것이며,
자동 발행 임계값도 여기서 나온다.

`_llm` 주입은 기존 `copy_engine.generate_copy(_llm=...)` 패턴을 그대로 따른다.

`publisher.py`만 `BaseAdapter`를 상속한다. 다만 **상한 계산은 물려받지 않고
재정의한다.** 기존 `_rate_ok()` 는 `config.DAILY_POST_LIMIT`(10)과
`config.CHANNEL_DAILY_LIMIT`(1)을 보는데, 답글은 전부 채널 1행(`@계정핸들`)에
귀속되므로 `CHANNEL_DAILY_LIMIT=1` 을 그대로 쓰면 **하루 첫 답글 이후 전부
차단된다.** `ThreadsPublisher` 는 `_rate_ok()` / `_rate_reason()` 을 오버라이드해
`THREADS_DAILY_LIMIT` / `THREADS_AUTO_DAILY_LIMIT` 을 보게 한다.
`_log_dry()` 와 `blocked` / `error` 구분 규약은 그대로 물려받는다.

`delete_reply()`를 1단계부터 넣는다. 자동 발행을 켜는 이상 잘못 나간 답글을
되돌릴 손잡이가 반드시 있어야 한다.

### 3.3 재사용 / 신규

**그대로 재사용**
- `approval.py` — 승인 큐 로직 (`pending()` / `decide()`)
- `db.py` — `creatives` / `approvals` / `posts` / `channels`
- `config.py` — 안전장치 패턴
- `stats.py` — 대시보드 집계
- `profiles/*.yaml` — 브랜드·금칙어·의무표기
- `/t/` 추적 링크 (`AD_CLICK_URL`, `TRACK_PREFIX`)
- `content/copy_engine.py` 의 `_find_banned` / `_find_leaks`

**신규**
- `threads/` 패키지 5개 모듈
- `threads/automator.py` — Selenium 드라이버·쿠키·스텔스
  (`facebook_automator.py` 패턴 이식, threads.net 도메인용)
- `threads_targets` 테이블 1개
- `profiles/*.yaml` 에 `threads:` 섹션 (관심 키워드 · 하드블록 키워드)
- `/approvals` 화면에 원글 표시 블록
- `login.py` 에 `threads` 대상 추가
- **pytest + `tests/`** — 현재 이 프로젝트엔 테스트 러너가 없다
  (검증이 `demo.py` · `preflight.py` · `tools/rehearsal.py` 실행 스크립트로만
  되어 있음). gate 골든셋을 반복 실행하려면 러너가 필요하므로 추가한다.
  기존 코드는 건드리지 않고 `tests/` 만 새로 만든다.

---

## 4. 데이터 모델

### 4.1 신규 테이블

```sql
CREATE TABLE IF NOT EXISTS threads_targets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url     TEXT NOT NULL UNIQUE,     -- 재수집 중복 배제의 핵심
    author       TEXT NOT NULL,
    text         TEXT,
    posted_at    TEXT,                     -- 원글 작성 시각(신선도 판정)
    likes        INTEGER DEFAULT 0,
    replies      INTEGER DEFAULT 0,
    profile_key  TEXT,                     -- 어느 업종이 이 글을 잡았나
    score        INTEGER,                  -- LLM 관련성 0~100 (NULL=미판정)
    verdict      TEXT,                     -- pending | passed | dropped
    reason       TEXT,                     -- 왜 떨어졌나 / 어떤 각도인가
    creative_id  INTEGER REFERENCES creatives(id),
    harvested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_targets_author  ON threads_targets(author);
CREATE INDEX IF NOT EXISTS idx_threads_targets_verdict ON threads_targets(verdict);
```

기존 테이블 스키마는 변경하지 않는다.

### 4.2 기존 테이블 사용 방식

- `channels` — `platform='threads'`, `target_ref='@계정핸들'` 1행 등록.
  채널 행을 만드는 이유는 `db.posts_today(channel_id)` 상한과 대시보드 집계가
  **코드 수정 없이 그대로 돌기** 때문이다.
- `creatives` — `kind='threads_reply'` (스키마 변경 아님, 값만 추가).
  `campaign_id`는 "쓰레드 답글" 상시 캠페인 1건을 만들어 붙인다.
- `approvals` / `posts` — 변경 없이 그대로.

### 4.3 `copy_json` 형식

```json
{
  "reply": "생성된 답글 전문",
  "target_url": "https://www.threads.net/@author/post/XXXX",
  "target_author": "@author",
  "target_excerpt": "원글 앞 120자",
  "score": 87,
  "angle": "사진 보정 고민을 말하는 글 — 도구 추천 각도",
  "profile_key": "photomagic",
  "brand": "PhotoMagic"
}
```

`approval.pending()` 이 이미 `copy_json` 을 통째로 UI에 넘기므로, `/approvals`
템플릿에 원글 블록만 추가하면 된다. 승인자가 원글을 못 보면 답글이 적절한지
판단할 수 없으므로 이 표시는 필수다.

### 4.4 프로필 yaml 확장

```yaml
threads:
  interest_keywords: [사진, 셀카, 프로필사진, 보정, 인생네컷, ...]
  hard_block:        [부고, 삼가, 사고, 확진, 투병, 고소, 정당, ...]
  landing:           "https://photomagic.example/t/threads"
```

`hard_block` 은 `interest_keywords` 보다 우선한다. 관심 키워드가 들어 있어도
하드블록이 하나라도 걸리면 LLM 호출 없이 즉시 탈락시킨다.

---

## 5. 설정 (config.py 신규)

```
THREADS_ENABLED              = 0     # 마스터 스위치 (GLOBAL_DRY_RUN 과 AND)
THREADS_ACCOUNT              = ""    # 쿠키 파일명을 결정 (login.py --account 와 일치)
THREADS_DAILY_LIMIT          = 20    # 하루 총 답글
THREADS_AUTO_DAILY_LIMIT     = 3     # 그중 자동 발행분 (1단계 상향 한도 8)
THREADS_AUTO_THRESHOLD       = 90    # 자동 발행 임계
THREADS_GATE_THRESHOLD       = 70    # 승인 큐 진입 임계
THREADS_REPLY_INTERVAL_MIN   = 180   # 답글 간 최소 간격(초)
THREADS_REPLY_INTERVAL_MAX   = 600
THREADS_AUTHOR_COOLDOWN_DAYS = 30    # 같은 사람 재답글 금지
THREADS_POST_MAX_AGE_MIN     = 90    # 이보다 오래된 글은 수집해도 버림
THREADS_REPLY_MAX_CHARS      = 280
THREADS_HARVEST_LIMIT        = 60    # 1회차 수집 목표 건수
```

기존 `GLOBAL_DRY_RUN` 과 `THREADS_ENABLED` 는 **AND** 로 동작한다. 둘 중 하나라도
꺼져 있으면 실발행되지 않는다.

### 값 선택 근거

- **`AUTO_THRESHOLD=90`** — 임계값은 골든셋 실측 전까지 근거가 없다. 낮게 잡아
  잘못 나가는 것보다, 높게 잡아 자동 발행이 하루 2건만 나가는 쪽이 회복 가능하다.
- **`AUTO_DAILY_LIMIT` 을 총 상한과 별도로 두는 이유** — 자동 발행분은 사람이 안
  본 채 나간다. 총 상한만 있으면 gate 오작동으로 전부 95점이 매겨지는 순간
  하루치 20건이 전부 무검수로 나간다. 자동분 상한이 그 사고의 크기를 묶는다.
- **작성자 쿨다운 30일** — 같은 사람에게 반복 답글이 붙는 것이 신고로 가는 가장
  빠른 경로다.
- **신선도 90분** — 오래된 글의 답글은 아무도 보지 않는다. 노출 없는 리스크다.

---

## 6. 오류 처리

| 상황 | 처리 |
|---|---|
| 셀렉터 변경(수집 0건) | `run_once()` 3회 연속 0건 → `THREADS_ENABLED=0` 자동 강등 + 대시보드 경고 |
| 로그인 세션 만료 | `PostResult(blocked=True, error="세션 만료 — login.py threads")` |
| LLM JSON 파싱 실패 | 해당 글만 폐기(`verdict='dropped'` + 사유), 배치는 계속 |
| LLM 할당량 초과 | 회차 중단. 수집분은 `verdict='pending'` 으로 남아 다음 회차 재판정 |
| 답글 가드 위반 | 1회 재생성 → 재차 위반 시 폐기 (`copy_engine` 패턴과 동일) |
| 발행 중 차단·캡차 | `THREADS_ENABLED=0` 즉시 강등 + 알림. **재시도 금지** |
| 발행 성공·URL 미확보 | `posts.status='posted'`, `perm_url=NULL` + 경고. 상한에는 계산 |
| 작성자 쿨다운 위반 | 발행 전 차단, `blocked=True` |

### 원칙

- **조용한 실패 없음.** 모든 폐기·차단은 사유가 DB에 남고 대시보드에 뜬다.
- **`blocked` 와 `error` 를 섞지 않는다.** `blocked` = 안전장치가 막음(상한·시간대·
  쿨다운·미로그인), `error` = 진짜 실패(셀렉터·네트워크·차단). 섞으면 운영자가
  원인을 헛짚는다. 기존 `channels/base.py` 주석 규칙을 그대로 따른다.
- **캡차에서 재시도 금지.** 캡차가 뜬 계정을 계속 두들기면 정지 수순이다.

---

## 7. 테스트 전략

1. **gate 골든셋 (관문)**
   샘플 추천글 100건을 JSON 픽스처로 저장하고 사람이 "달아야 함/말아야 함"
   라벨링. 실제 LLM으로 `gate.screen()` 을 돌려 정확도와 **점수 분포**를 확인한다.
   `AUTO_THRESHOLD` / `GATE_THRESHOLD` 는 이 결과에서 결정한다.
   특히 확인할 것: 하드블록이 걸러야 할 글(부고·사고·질병)이 높은 점수를 받는
   사례가 있는가. 하나라도 있으면 자동 발행을 켜지 않는다.

2. **reply_writer 가드**
   목 LLM으로 다음을 주입해 전부 걸리는지: 금칙어 / 타사 링크 / 길이 초과 /
   이모지 폭주 / 원글 인용 / 자리표시자 미치환.

3. **publisher dry-run**
   기존 3채널 dry-run 검증과 동일 패턴. 상한·간격·시간대·쿨다운이 각각
   `blocked` 를 정확한 사유와 함께 반환하는지.

4. **runner 통합**
   4개 모듈을 목킹하고 점수별 분기(자동/승인/폐기)와 상한 소진을 검증.
   특히 `AUTO_DAILY_LIMIT` 소진 후 고점수 건이 승인 큐로 흘러가는지.

5. **harvester**
   저장된 threads.net HTML 픽스처로 파싱만 검증. 라이브 확인은 수동 1회.

러너는 pytest, 위치는 `tests/`. 1·2·4·5번은 `pytest tests/ -v` 로 돌고,
1번의 실제 LLM 호출분은 `pytest -m golden` 으로 분리해 평소엔 제외한다
(할당량 소모 방지).

---

## 8. 실가동 순서

```
1. THREADS_ENABLED=0 · dry-run 으로 전 구간 관통
2. gate 골든셋 실행 → 임계값 확정
3. 전건 승인 모드로 30건 실발행 → 승인률·답글 품질 확인
4. AUTO_THRESHOLD 켜기 (THREADS_AUTO_DAILY_LIMIT=3 부터)
5. 1주 무사고 시 상한 단계적 상향
```

3단계에서 승인률이 낮으면(예: 절반 이상 거절) 4단계로 넘어가지 않는다.
자동 발행은 "사람이 봤으면 승인했을 것"이 전제이므로, 승인률이 그 전제의
유일한 증거다.

---

## 9. 2단계 예고 (별도 스펙)

하루 100건↑ 목표는 계정 1개로 달성 불가능하다. 이 파이프라인이 검증된 뒤
다음을 별도 설계한다.

- 계정 풀 관리 (계정별 쿠키·브라우저 프로필 격리)
- IP 분리 (프록시) — 같은 IP의 다중 계정이 가장 쉽게 잡히는 신호
- 계정 워밍업 스케줄 (신규 계정의 초기 평판 축적)
- 계정 간 문체 분산 (동일 문투 클러스터 방지)
- 계정 단위 격리 차단 (한 계정 정지가 나머지에 번지지 않게)
