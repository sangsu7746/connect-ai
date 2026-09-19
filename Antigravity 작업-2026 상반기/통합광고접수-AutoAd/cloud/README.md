# 접수폼 클라우드 공개 (headjim-loan)

광고에 실리는 **소비자 접수 링크**를 외부에 공개하고, 들어온 리드를 사무실 PC의 대출앱으로 회수하는 구성.

```
소비자 → https://headjim-loan.web.app/?channel=band_1&utm=...
            ↓ POST /api/intake  (호스팅 rewrite → 함수, 같은 출처라 CORS 불필요)
         loanIntakeSubmit → Firestore `loanLeads` (status=pending)
            ↓                 ← PC 꺼져 있어도 여기 안전하게 쌓임
         [사무실 PC] python cloud_sync.py --watch
            ↓ loanIntakePull (Bearer 토큰)
         대출앱 /api/intake/register → loans.json
```

## 왜 이 구조인가
- **URL이 영구 고정** — 광고에 박힌 링크는 못 고치므로 바뀌면 안 됨
- **PC가 꺼져도 리드 보존** — 소비자는 밤에도 광고를 봄. 유실 = 매출 손실
- **PC를 인터넷에 노출하지 않음**
- **기존 사이트·함수 무영향** — `codebase: loanintake` 로 분리, 함수명 `loanIntake*` 접두사

## 배포 (최초 1회)

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd\cloud"

# 1) 호스팅 사이트 생성
npx firebase-tools hosting:sites:create headjim-loan --project headjim-ai

# 2) 함수 의존성 설치
cd functions && npm install && cd ..

# 3) 회수 토큰을 Secret Manager 에 등록 (.env 의 LEAD_PULL_TOKEN 과 같은 값)
npx firebase-tools functions:secrets:set LOAN_PULL_TOKEN --project headjim-ai

# 4) 배포 — ⚠ 반드시 대상을 지정해 기존 함수/사이트를 덮어쓰지 않는다
npx firebase-tools deploy --project headjim-ai \
  --only "functions:loanintake,hosting:loanintake"
```

## 배포 후 설정

AutoAd `.env`:
```
PUBLIC_BASE=https://headjim-loan.web.app
LEAD_PULL_URL=https://us-central1-headjim-ai.cloudfunctions.net/loanIntakePull
LEAD_PULL_TOKEN=<위 3)에서 넣은 값과 동일>
```

확인:
```bash
python preflight.py          # "접수 링크 공개" ✅ 로 바뀌어야 함
python cloud_sync.py         # 1회 동기화 (새 접수 없으면 "새 접수 없음")
python cloud_sync.py --watch # 상시 동기화 (3분 간격)
```

## 보안 메모
- `loanIntakePull` 의 보호 장치는 **Bearer 토큰 하나뿐**이다. 토큰이 새면 리드가 유출된다.
  `.env` 는 git 에 커밋되지 않으며(.gitignore), 유출 의심 시 `functions:secrets:set` 로 교체 후 재배포.
- 접수폼은 **이름·연락처만** 수집한다. 주민등록번호 필드는 폼·함수·스키마 어디에도 없다.
- 봇 차단: 허니팟(`company_website`) + 동의 필수 + 연락처 형식 검증 + 필드 길이 제한.
- Firestore 보안 규칙은 **건드리지 않는다** — 함수가 admin SDK 로 쓰므로 공용 규칙 변경 불필요.

## 리드 유실 주의
`loanIntakePull` 은 가져간 즉시 `pulled` 로 표시하므로 **재요청해도 다시 오지 않는다**.
대출앱 등록이 실패하면 `cloud_sync.py` 가 로컬 `consumers` 테이블에 보관하고 로그에 남긴다.
장애 시 Firestore 콘솔(`loanLeads`)에서 `status=pulled` 문서를 직접 확인할 수 있다.
