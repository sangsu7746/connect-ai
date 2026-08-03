# AutoAd 실가동 런북 (GO-LIVE)

> **원칙: 완전 무인 아님 · 첫 발행은 반드시 버너/테스트 채널 · 항상 사람 승인 · 낮은 상한부터.**
> 되돌리기: 언제든 `.env`의 `GLOBAL_DRY_RUN=1` → 실발행 즉시 정지.

준비 점검은 항상 먼저: `python preflight.py`

---

## 0단계 — 준비물 채우기 (preflight ⚠️ 해소)

| 항목 | 방법 |
|---|---|
| **Anthropic 크레딧** | console.anthropic.com → Plans & Billing 충전. 확인: 아래 "카피 라이브 테스트" |
| **채널 등록** | `python register_channels.py` (카톡방 자동 import·비활성) + 밴드/페북은 `add_band/add_facebook` |
| **대출앱 구동**(접수 종착) | 대출앱 폴더에서 `python -m uvicorn app:app --port 8000` (헤드리스). `.env` `LOAN_API_BASE` 일치 확인 |
| (선택) 텔레그램 승인 | `.env` `TELEGRAM_TOKEN` + `pip install python-telegram-bot` |

**카피 라이브 테스트(크레딧 확인):**
```bash
python -c "from content import copy_engine as c; print(c.generate_copy({'title':'테스트','product':'담보대출'},{'platform':'band','audience':'consumer'}))"
```
→ JSON 카피가 나오면 크레딧 OK. `credit balance too low` 나오면 충전 필요.

---

## 1단계 — 광고 대상 채널만 켜기 (아주 중요)

⚠️ `chatrooms.json`에서 온 카톡방은 **대부분 B2B(대부업체 접수/답변방)**입니다. **여기에 소비자 광고를 보내면 안 됩니다.** 실제로 광고할 채널만 골라 켜세요.

```bash
# 채널 목록·id 확인
python -c "import db,json; print(json.dumps(db.list_channels(),ensure_ascii=False,indent=2))"
# 광고할 채널만 활성화 (예: id 5)
python -c "import db; db.set_channel_enabled(5, True)"
```
- 밴드/페북 소비자 채널을 우선 추가·활성화:
```bash
python -c "import register_channels as r; r.add_band('https://band.us/band/XXXX','우리동네 정보방','consumer',enabled=True)"
```

---

## 2단계 — 무장 전 최종 리허설 (여전히 DRY-RUN)

`GLOBAL_DRY_RUN=1` 그대로. 실제 채널 1개만 켜고 전 구간 확인:
```bash
python -m uvicorn app:app --port 8010      # 접수+승인+스케줄러 상주
```
- 캠페인 실행(오케스트레이터) → `http://127.0.0.1:8010/approvals` 에서 전단·캡션 확인 → 승인 → **로그에 `[DRY-RUN][band] POST …`** 뜨는지 확인.
- 접수폼 `http://127.0.0.1:8010/intake` 제출 → 대출앱 loans.json 반영 확인.

여기까지 문제 없으면 실발행 준비 완료.

---

## 3단계 — 실발행 무장 (버너 채널부터)

1. **버너/테스트 채널 준비** — 내가 소유한 테스트 밴드(또는 부계정) 1개.
2. `.env` → `GLOBAL_DRY_RUN=0`, `DAILY_POST_LIMIT=2` (낮게 시작).
3. **로그인 세션 만들기** — 비밀번호는 시스템에 넣지 않습니다.

   ```bash
   python login.py --check                                  # 저장된 세션 목록·나이 확인
   python login.py band     --account 내네이버아이디          # 창에서 직접 로그인
   python login.py facebook --account 내이메일@example.com
   python login.py kakao                                     # 안내만(로그인 불필요)
   ```

   - 브라우저 창이 열리면 **사장님이 직접** 아이디·비밀번호를 입력하고 2FA/캡차를 통과합니다.
     스크립트는 "로그인됐는지"만 감지해 **세션(쿠키)을 저장**합니다.
   - 이후 시스템은 **비밀번호 없이** 이 세션으로 발행합니다 (`adapter.login()` 인자 없이 호출).
   - 세션이 만료되면 발행 시 "저장된 세션 만료" 로그가 뜨고, 위 명령을 다시 실행하면 됩니다.
   - 카카오는 **PC 카카오톡을 로그인 상태로 열어두기만** 하면 됩니다(AHK가 창을 조작).
4. 버너 채널로 캠페인 → 승인 → **실제 1건 게시** → 밴드/페북/카톡에서 눈으로 확인.
5. 이상 없으면 실제 소비자 채널로 **한 채널씩** 확대(밴드 → 페북 → 카카오), 상한을 서서히 올림.

---

## 카카오 실전송 주의 (특히 취약)

- 데스크톱 카톡 창이 **열려 있고 로그인**돼 있어야 함. AutoHotkey가 창을 제어.
- 전송 중 **다른 창 포커스 뺏기 금지**(오전송 위험). 해상도/카톡 업데이트 시 셀렉터 깨질 수 있음.
- 어댑터가 **방 이름 검증**을 하지만, 켜는 방은 **정확한 이름**으로. 첫 전송은 테스트 방으로.

---

## 일상 운영 루프

```
1. python -m uvicorn app:app --port 8010   (상주 · 스케줄러 포함)
2. 캠페인 생성 → 자동으로 채널별 전단+캡션 → 승인 큐
3. /approvals 에서 사진·문구 보고 승인/수정/거절
4. 승인 → 즉시 or 예약 발행 → posts 기록
5. 접수 오면 /intake → 대출DB 자동 등록
```

## 안전·컴플라이언스 체크
- [ ] 대출광고 의무표기 — 전단(재사용)에 내장. 신규 생성 시 의무표기 고정층 확인.
- [ ] 접수폼 개인정보 — 동의 필수(자동), 주민번호 미수집(자동).
- [ ] B2B 방에 소비자 광고 금지 — 활성 채널 재확인.
- [ ] 계정 보호 — 버너 우선, 낮은 상한, 사람 승인 유지, 밴/checkpoint 모니터.
- [ ] 정지 위험은 상수 — 자동화는 ToS 위반. 본계정 대량발행 금지.

## 비상 정지
```bash
# .env 에서
GLOBAL_DRY_RUN=1
```
→ 모든 실발행 즉시 차단(예약분 포함, 다음 발행부터 dry). 서버 재시작.
