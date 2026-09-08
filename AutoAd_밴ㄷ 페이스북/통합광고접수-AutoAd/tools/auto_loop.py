# -*- coding: utf-8 -*-
"""auto_loop.py — 컴퓨터가 켜져 있는 동안 알아서 광고를 만들고 내보낸다

한 주기가 하는 일:
  1. 지금이 발행 허용 시간대인가 — 아니면 아무것도 하지 않고 잔다
  2. 승인 대기 중인 소재를 발행한다
  3. **오늘 남은 발행 여유만큼만** 새 소재를 만든다
  4. 다음 주기까지 잔다

── 왜 '남은 여유만큼만' 인가 ────────────────────────────────
소재를 만들 때마다 이미지 생성비가 든다. 반면 하루 발행량은
DAILY_POST_LIMIT(플랫폼당 기본 10건)으로 묶여 있다.
여유를 안 보고 주기마다 고정 개수를 만들면, 하루 10건 내보내려고
수백 장을 만들어 버린다. 만든 소재는 쿨다운까지 잡아먹어 다음 날
쓸 그림도 줄어든다. 그래서 **부족한 만큼만** 만든다.

── 로그인 실패 처리 ─────────────────────────────────────
캡차·2단계 인증은 사람이 풀어야 한다. 실패했는데 주기마다 계속
재시도하면 계정이 잠긴다. 연속 실패마다 대기를 두 배로 늘리고,
사람이 `python login.py <platform>` 을 해줄 때까지 조용히 기다린다.

사용:
  python tools/auto_loop.py                          # 활성 업종 전부
  python tools/auto_loop.py --profiles printcraft,inkcraft
  python tools/auto_loop.py --dry-run                # 무엇을 할지만 본다
"""
import os
import io
import sys
import time
import tempfile
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

def _utf8_stdout():
    """콘솔 한글 깨짐 방지 — 스크립트로 실행될 때만.
    ⚠ 모듈 최상단에서 바꾸면 이 파일을 import 한 쪽의 출력이 닫혀버린다
      (check_group_rules·classify_channels·publish_campaign 에서 겪은 사고다.
       여기서도 같은 일이 났다: tests 가 auto_loop 을 import 하자마자
       pytest 의 캡처 파일이 닫혀 'I/O operation on closed file' 로 한 건도
       못 돌았다)."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass


BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import config
import db
import orchestrator as O
import singleton

# 기본 자동화에서 빼는 업종. --profiles 로 명시하면 포함된다.
#
# loan 은 2026-08-10 운영자 지시로 자동화에 편입했다. 그 전제는 다음 셋이며,
# 하나라도 무너지면 다시 빼야 한다:
#   1) 전단에 인쇄된 번호 = 등록 광고용 번호(010-2577-2679).
#      flyers_v2/ 를 쓴다. flyers/ 원본에는 아직 구번호가 박혀 있다.
#   2) 대부업법 제9조 의무표기 4항목이 profiles/loan.yaml 에 채워져 있다
#      (config.compliance_gaps('loan') 이 빈 목록이어야 한다).
#   3) facts 가 비어 있어 금리·한도·기간 수치를 카피가 쓰지 못한다.
#      loan 에 facts 를 채우려면 실증자료부터 확보할 것.
# ⚠ 등록증(2026-01-05) 기재 광고용 번호는 010-7697-5684 다. 운영자 확인에 따라
#   010-2577-2679 를 쓰고 있으나, 변경등록 완료 여부는 별도로 확인이 필요하다.
OPT_IN_ONLY = set()

LOGIN_HINT = "python login.py {platform}"

# 계정별 병렬 발행. 기본은 꺼 둔다(코드를 고치지 않고 되돌릴 수 있어야 한다).
#   켜기: .env 또는 환경변수에 PARALLEL_PUBLISH=1
# ⚠ 켜기 전 확인할 것 — 발행 구간이 클립보드를 쓰지 않아야 한다.
#   band/facebook 엔진이 CLIPBOARD_FREE_POST 를 선언하고 CDP 가 실제로 동작할 때만
#   orchestrator 가 발행 구간 잠금을 푼다(_post_needs_crosslock). 둘 중 하나라도
#   아니면 잠금이 그대로라 병렬로 띄워도 서로 기다리기만 한다 - 위험하지는 않다.
PARALLEL_PUBLISH = os.getenv("PARALLEL_PUBLISH", "0").strip() == "1"

# 다른 루프가 이미 돌고 있어 뜨지 못했다는 뜻. '자동광고 실행.bat' 이 이 코드를
# 보고 60초 재시도를 멈춘다 — 안 그러면 같은 거절을 1분마다 영원히 찍는다.
EXIT_ALREADY_RUNNING = 3


# 콘솔 창이 닫히면 그 안의 출력은 함께 사라진다. 2026-08-12 루프가 발행 도중
# 멈췄는데 원인을 알 수 없었다 - 출력이 창에만 있었기 때문이다. 파일로도 남긴다.
LOG_PATH = BASE / "data" / "auto_loop.log"


def log(msg=""):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}" if msg else ""
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass          # 로그 때문에 발행이 멈추면 안 된다


def _kill_tree(pid):
    """자식과 **손자까지** 죽인다.

    publish_campaign 은 chromedriver 를 띄우고 chromedriver 는 chrome 을 띄운다.
    자식만 죽이면 손자가 그대로 남아 계속 쌓인다(실측: 고아 크롬 52개).
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=60)
    else:
        import signal
        os.killpg(os.getpgid(pid), signal.SIGKILL)


def run(cmd, env=None, timeout=1800):
    """자식 프로세스 실행. 반환 (성공여부, 표준출력).

    ⚠ 출력을 **파이프로 받지 않는다**. 임시 파일로 받는다.
      subprocess.run(capture_output=True, timeout=...) 은 타임아웃이 나면
      자식을 죽인 뒤 파이프를 한 번 더 비우는데, 손자(chromedriver·chrome)가
      그 파이프의 쓰기 핸들을 물려받아 살아 있으면 EOF 가 오지 않아
      **타임아웃 처리 안에서 영원히 멈춘다**. 타임아웃이 있으나 마나가 된다.

      실측(2026-08-13): 주기 #5 가 23:55 에 시작해 06:21 까지 6시간 24분 멈췄고
      그동안 발행 0건이었다. timeout=1800 은 00:25 에 제때 발동했지만, 그 뒤
      고아 chromedriver 2개가 파이프를 붙들어 부모가 빠져나오지 못했다.
      고아를 죽이자 루프가 그 즉시 재개됐다.

      파일로 받으면 핸들을 누가 물고 있든 부모는 기다리지 않는다.
    """
    e = dict(os.environ)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        e.update(env)
    try:
        with tempfile.TemporaryFile() as f:
            p = subprocess.Popen([sys.executable, "-u"] + cmd, cwd=str(BASE),
                                 env=e, stdout=f, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
            timed_out = False
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(p.pid)
                try:
                    p.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    pass
            f.seek(0)
            out = f.read().decode("utf-8", "replace")
        if timed_out:
            return False, out + f"\n타임아웃({timeout}초) — 자식 트리를 종료했습니다"
        return p.returncode == 0, out
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"


# ── 상태 조회 ────────────────────────────────────────────

def platforms_in_use(profiles=None):
    """켜진 채널이 있는 플랫폼 목록."""
    out = {}
    for c in db.list_channels(enabled_only=True):
        if db.is_demo_channel(c):
            continue
        if profiles and c["profile_key"] not in profiles:
            continue
        out.setdefault(c["platform"], set()).add(c["profile_key"])
    return out


def accounts_of(platform: str, profiles=None) -> list:
    """그 플랫폼에서 실제로 쓰는 계정 목록."""
    accs = {(c["account"] or "").strip()
            for c in db.list_channels(platform=platform, enabled_only=True)
            if not db.is_demo_channel(c)
            and (not profiles or c["profile_key"] in profiles)}
    return sorted(a for a in accs if a) or [""]


_INTERVAL = [1200]          # main() 이 실제 주기로 채운다


def per_cycle_cap(min_n: int = 0) -> int:
    """한 주기에 만들 소재 수의 상한.

    한 주기에 실제로 발행할 수 있는 건수에서 거꾸로 계산한다.
      건당 소요 = 발행 간격(평균) + 게시 자체에 걸리는 시간(~30초)
    거기에 2배의 여유를 둔다(발행이 빨리 끝났을 때 놀지 않게).

    min_n: 이번에 나눠 가질 **업종 수**. 이 아래로는 못 내려간다.
      ⚠ 주기를 짧게 잡으면 이 계산값이 작아진다. 활성 업종 수보다 작아지면
        need 를 업종 수로 나눌 때 나머지 배분이 앞쪽 몇 개에서 끝나,
        뒤쪽 업종은 매 주기 share=0 으로 밀려 **영영 소재를 못 받는다**.
        실측(2026-08-14): 주기 20분→10분으로 줄이자 이 값이 10→4로 줄었고,
        12개 업종 중 뒤쪽 8개(mirizip·proheadshot·lifealbum 등)가 7시간
        넘게 소재를 하나도 못 받았다 — 앞 4개(adstudio·colorcraft·inkcraft·
        loan)만 매 주기 반복 생성되고 있었다.
      그래서 do_generate 가 '이번에 나눠 가질 업종 수'를 넘겨 바닥을 보장한다
      — 체크 주기를 짧게 가져가도 업종 다양성을 잃지 않는다.
    """
    per_post = (config.POST_INTERVAL_MIN + config.POST_INTERVAL_MAX) / 2 + 30
    n = int(_INTERVAL[0] / max(1.0, per_post)) * 2
    return max(2, n, min_n)


def free_channels(platform: str, profiles=None) -> int:
    """오늘 아직 한 건도 안 올린 채널 수.

    CHANNEL_DAILY_LIMIT(기본 1) 때문에 이 숫자가 오늘 발행 가능한 실제 상한이다.
    상한을 아무리 올려도 여기를 넘지 못한다.
    """
    n = 0
    for c in db.list_channels(platform=platform, enabled_only=True):
        if db.is_demo_channel(c):
            continue
        if profiles and c["profile_key"] not in profiles:
            continue
        if db.posts_today(c["id"]) < config.CHANNEL_DAILY_LIMIT:
            n += 1
    return n


def remaining_today(platform: str, profiles=None) -> int:
    """오늘 그 플랫폼에 더 내보낼 수 있는 건수.

    ⚠ 상한은 **계정별**이므로 계정마다 따로 세어 합친다. 플랫폼 전체로 한 번만
      세면 계정을 늘려도 여유가 늘지 않아, 두 번째 계정이 첫 계정 발행 때문에
      소재조차 만들어지지 않는다.
    """
    cap = config.daily_limit(platform)
    return sum(max(0, cap - db.posts_today(platform=platform, account=acc))
               for acc in accounts_of(platform, profiles))


def pending_count(platform: str = None) -> int:
    """승인 대기 중이면서 **실제로 발행 가능한** 건수.
    꺼진 채널·데모 채널 건은 영원히 안 나가므로 세지 않는다."""
    with db.get_conn() as con:
        rows = con.execute(
            "SELECT ch.platform, ch.id FROM approvals a "
            "JOIN creatives cr ON cr.id = a.creative_id "
            "JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE a.state = 'pending' AND ch.enabled = 1").fetchall()
    live = {c["id"]: c for c in db.list_channels()}
    n = 0
    for r in rows:
        if platform and r["platform"] != platform:
            continue
        ch = live.get(r["id"])
        if ch and not db.is_demo_channel(ch):
            n += 1
    return n


def pending_by_account():
    """발행 대기건을 **계정+플랫폼별로** 묶는다. {(계정, 플랫폼): [캠페인번호...]}

    병렬 발행의 단위다. 겹치지 않는 근거는 두 가지고, 둘 다 DB 구조에서 나온다.
      · 한 채널은 한 계정에 속한다  → 계정이 다르면 대상이 겹치지 않는다
      · 한 채널은 한 플랫폼에 속한다 → 플랫폼이 다르면 대상이 겹치지 않는다
    그러므로 같은 방에 두 번 올라갈 수 없다.

    ⚠ 계정만으로 나누면 한 계정 안에서 밴드와 페이스북이 한 프로세스에 묶여
      순서를 기다린다(2026-08-13 실측: headjimkss 가 밴드 137 + 페이스북 187 =
      324채널을 혼자 순차 처리하고 headjim100 은 밴드 47채널만 맡아, 8:2 로
      기울어 있었다. 페이스북은 계정이 하나뿐이라 병렬이 전혀 아니었다).

    ⚠ 플랫폼으로 나눠도 안전한 근거 — 세션이 섞이지 않는다. 쿠키 파일이
      플랫폼마다 다른 프로젝트, 다른 이름이다(밴드 '{계정}.json',
      페북 'fb_{계정}.json'). 크롬 프로필도 셀레니움이 실행마다 임시로 새로
      만든다. 밴드 로그인이 쓰는 클립보드는 crosslock 이 그대로 감싼다.
    """
    with db.get_conn() as con:
        rows = con.execute(
            "SELECT DISTINCT COALESCE(ch.account,'') acct, ch.platform plat, "
            "       cr.campaign_id "
            "FROM approvals a "
            "JOIN creatives cr ON cr.id = a.creative_id "
            "JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE a.state = 'pending' AND ch.enabled = 1 "
            f"AND {db.not_fallback_sql('cr')} "
            "ORDER BY acct, plat, cr.campaign_id").fetchall()
    out = {}
    for acct, plat, cid in rows:
        out.setdefault((acct, plat), []).append(cid)
    return out


def pending_campaigns():
    """발행 가능한 대기건이 있는 캠페인 번호.

    ⚠ 폴백 문구는 세지 않는다. 여기서 안 빼면 '대기 3건'이라고 찍어 놓고
      자식 프로세스는 0건을 발행한다 — 로그와 실제가 어긋나 원인을 못 찾는다.
    """
    with db.get_conn() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT cr.campaign_id FROM approvals a "
            "JOIN creatives cr ON cr.id = a.creative_id "
            "JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE a.state = 'pending' AND ch.enabled = 1 "
            f"AND {db.not_fallback_sql('cr')} "
            "ORDER BY cr.campaign_id").fetchall()]


def hours_ok_now() -> tuple:
    """지금이 발행 허용 시간대인가(채널별 예외는 발행 시점에 또 걸린다)."""
    return O.hours_ok({})


# ── 한 주기 ─────────────────────────────────────────────

def held_fallback_count() -> int:
    """폴백이라 발행을 보류한 대기건 수."""
    if not db.block_fallback_publish():
        return 0
    with db.get_conn() as con:
        return con.execute(
            "SELECT COUNT(*) FROM approvals a "
            "JOIN creatives cr ON cr.id = a.creative_id "
            "JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE a.state = 'pending' AND ch.enabled = 1 "
            "  AND COALESCE(cr.copy_json,'') LIKE '%\"_fallback\"%'").fetchone()[0]


def do_publish(dry=False) -> tuple:
    """대기건 발행. 반환 (발행성공수, 로그인실패여부)."""
    camps = pending_campaigns()
    # ⚠ 보류 건수를 **반드시 찍는다**. 이 사고의 본질은 '조용함'이었다 —
    #   문구 생성이 전량 폴백이 됐는데 로그가 멀쩡해 보여 아무도 몰랐다.
    #   여기서 침묵하면 '대기건 없음'만 반복돼 같은 실수를 되풀이한다.
    held = held_fallback_count()
    if held:
        log(f"  ⚠ 폴백 문구 {held}건 발행 보류 — 업종마다 고정 문장이라 "
            f"같은 방에 같은 글이 반복됩니다")
        log(f"    카피 API 를 복구하면 그때부터 정상 문구가 자동으로 나갑니다 "
            f"(해제: .env 에 BLOCK_FALLBACK_PUBLISH=0)")
    if not camps:
        log("  발행할 대기건 없음" + (f" (보류 {held}건 제외)" if held else ""))
        return 0, False
    done, login_failed = 0, False
    log(f"  캠페인 {', '.join('#'+str(c) for c in camps)} 발행 시도")
    if dry:
        log("    (dry-run — 실제 발행 안 함)")
        return 0, False

    # ⚠ 캠페인마다 프로세스를 띄우면 **그때마다 로그인**한다.
    #   밴드는 band_session 이 세션 전용 쿠키라 저장한 쿠키로 복원되지 않고
    #   매번 아이디·비밀번호 로그인을 새로 한다(실측 2026-08-10).
    #   20분 주기 × 캠페인 수만큼 로그인하면 그 자체가 비정상 접속으로 보인다.
    #   publish_campaign.py 는 --campaign 에 쉼표 목록을 받아 한 프로세스에서
    #   처리하므로, 로그인은 주기당 한 번이면 된다.
    #   → 병렬(PARALLEL_PUBLISH=1)에서도 이 원칙은 지킨다:
    #     프로세스는 **계정+플랫폼당 하나**뿐이라 로그인도 그 조합당 한 번이다.
    #     계정당 프로세스였을 때와 로그인 총횟수는 같다 — 한 프로세스가 밴드·페북
    #     양쪽을 맡던 시절에도 로그인은 플랫폼마다 따로 했기 때문이다(아래 145행
    #     "로그인은 플랫폼마다 따로 본다"). 나눈다고 접속이 늘지 않는다.
    groups = pending_by_account() if PARALLEL_PUBLISH else {}
    if PARALLEL_PUBLISH and len(groups) > 1:
        return _publish_parallel(groups)

    ok, out = run(["tools/publish_campaign.py",
                   "--campaign", ",".join(str(c) for c in camps), "--yes"],
                  env={"GLOBAL_DRY_RUN": "0"})
    return _tally(out, "")


def _tally(out: str, tag: str) -> tuple:
    """publish_campaign 출력에서 (발행수, 로그인실패여부)를 뽑고 요약을 찍는다."""
    done, login_failed = 0, False
    for line in out.splitlines():
        if line.startswith(("  [", " 발행 ", "[login]")) or "로그인 실패" in line:
            log(f"    {tag}{line.strip()}")
    if "로그인 실패" in out or "모든 플랫폼 로그인 실패" in out:
        login_failed = True             # 더 시도해도 같다. 계정 보호가 우선.
    for line in out.splitlines():
        if line.strip().startswith("발행 ") and "·" in line:
            try:
                done += int(line.split("발행")[1].split("·")[0].strip())
            except (ValueError, IndexError):
                pass
    return done, login_failed


def _label(key):
    """진행 로그에 쓸 이름. ('a@b.com','band') → 'a@b/band'"""
    acct, plat = key
    return f"{(acct or '기본').split('@')[0][:14]}/{plat}"


def _publish_parallel(groups: dict) -> tuple:
    """**계정+플랫폼**마다 프로세스를 하나씩 띄워 동시에 발행한다.

    왜 되는가 — 발행 구간이 더 이상 클립보드를 쓰지 않는다(2026-08-11,
    band/facebook 양쪽 CDP Input.insertText 로 전환). 클립보드가 머신에 하나뿐이라
    직렬로 묶여 있던 것이 풀렸다.

    ⚠ 아직 직렬인 곳이 남아 있고, 그건 그대로 둔다:
      · **로그인** — 밴드 로그인이 비밀번호를 클립보드에 복사한다. orchestrator 가
        crosslock 으로 감싸고 있어, 여기서 프로세스를 여러 개 띄워도 로그인
        구간만은 한 번에 하나씩 지나간다.
      · **한 프로세스 안** — _PUBLISH_LOCK 과 발행 간격(90~300초)은 그대로다.
        한 계정이 같은 플랫폼의 여러 방에 동시에 올리면 그 자체가 탐지 신호다.

    ⚠ 계정+플랫폼으로 나누는 이유 — 한 채널은 한 계정, 한 플랫폼에만 속하므로
      둘 중 하나만 달라도 대상 채널이 겹치지 않는다. 자식 프로세스에
      --account 와 --platform 을 **둘 다** 못 박아 DB 질의에서도 강제한다.

    ⚠ 같은 계정을 두 창에 띄우게 된다(밴드 1 + 페이스북 1). 서로 다른 서비스라
      세션이 섞이지 않는다 — 쿠키 파일이 다른 프로젝트에 다른 이름으로 있고
      (밴드 '{계정}.json', 페북 'fb_{계정}.json'), 크롬 프로필은 셀레니움이
      실행마다 임시로 새로 만든다.
    """
    from concurrent.futures import ThreadPoolExecutor

    log(f"  {len(groups)}갈래 병렬 발행: "
        + ", ".join(f"{_label(k)}({len(v)}캠페인)" for k, v in sorted(groups.items())))

    def one(key, cids):
        acct, plat = key
        cmd = ["tools/publish_campaign.py",
               "--campaign", ",".join(str(c) for c in cids), "--yes"]
        if acct:
            cmd += ["--account", acct]
        if plat:
            cmd += ["--platform", plat]
        return run(cmd, env={"GLOBAL_DRY_RUN": "0"})

    done, login_failed = 0, False
    with ThreadPoolExecutor(max_workers=len(groups)) as ex:
        futs = {ex.submit(one, k, v): k for k, v in sorted(groups.items())}
        for f, key in futs.items():
            try:
                _ok, out = f.result()
            except Exception as e:
                log(f"    [{_label(key)}] 발행 프로세스 오류: {type(e).__name__}: {e}")
                continue
            d, lf = _tally(out, f"[{_label(key)}] ")
            done += d
            login_failed = login_failed or lf
    return done, login_failed


def enabled_channel_count(profile: str, platform: str) -> int:
    """그 업종의 **그 플랫폼** 활성 채널 수(데모 제외). 테스트에서 갈아끼우는 이음매다.

    ⚠ platform 을 받는다 — 그림 재고가 파일명에 플랫폼을 담아 나뉘어 있다
      (showcase_{profile}_{platform}_v{n}.png, stock_count 참고). 업종
      전체로 한 번만 세면 재고가 몰린 플랫폼이 재고 없는 플랫폼의 채널
      수요를 가린다.
    """
    return sum(1 for c in db.list_channels(platform=platform, enabled_only=True)
               if c["profile_key"] == profile and not db.is_demo_channel(c))


def stock_count(profile: str, platform: str) -> int:
    """그 업종의 **그 플랫폼**이 지금 갖고 있는 쓸 수 있는 그림 수(디스크 기준).

    ⚠ platform 을 받는다 — showcase_{profile}_{platform}_v{n}.png ·
      doc_{profile}_{platform}_v{n}.png 처럼 파일명이 이미 플랫폼을 담고
      있다. 업종 전체로 세면(2026-09-08 이전 버전) 재고가 몰린 플랫폼이
      재고 없는 플랫폼을 가려 '충족'으로 오판한다 — 실측: printcraft 는
      전체 53장/목표 42장으로 '충족' 판정났지만 그 53장은 전부 facebook
      것이고 band(채널 10개)는 0장이라 아무것도 못 받고 있었다.
    """
    import re
    d = config.CREATIVES_DIR
    if not d.is_dir():
        return 0
    pat = re.compile(rf"^(showcase|doc)_{re.escape(profile)}_{re.escape(platform)}_")
    return sum(1 for p in d.iterdir()
               if p.suffix.lower() == ".png" and pat.match(p.name))


def images_per_round(profile: str, platform: str) -> int:
    """한 바퀴에 그 업종·그 플랫폼이 쓸 그림 수. 채널이 많을수록 여러 장으로 나눈다.

    ⚠ platform 별로 나눈다 — enabled_channel_count·stock_count 주석 참고.

    ⚠ orchestrator.run_campaign 의 n_imgs_by_platform 이 **같은 ceil 식**을
      다시 쓴다. 다만 **입력이 다르다** — 이 함수는 그 플랫폼의 활성 채널
      전부를 세고, 저쪽은 그 호출이 넘겨받은 channels 목록만 센다
      (run_by_profile 이 --limit 으로 잘라 보낸다). 두 값은 일상적으로
      다르며 서로 대체할 수 없다. 같이 봐야 하는 것은 상한
      (IMAGE_FANOUT_MAX) 계산식뿐이다(orchestrator 가 이 함수를 가져다
      쓰면 순환 import 가 되므로 각자 계산한다).
    """
    n = enabled_channel_count(profile, platform)
    if n <= 0:
        return 0
    cap = max(1, config.IMAGE_FANOUT_MAX)
    return -(-n // cap)          # ceil


def stock_target(profile: str, platform: str) -> int:
    """그 업종의 그 플랫폼이 무한 순환하려면 필요한 재고.

    한 그림은 한 방에 나가면 쿨다운 일수만큼 쉰다. 하루 한 바퀴를 돌리려면
    '라운드당 그림 수 x 쿨다운 일수' 만큼 있어야 돌아간다.

    ⚠ platform 별로 나눈다 — enabled_channel_count·stock_count 주석 참고.

    ⚠ orchestrator.py 는 이 계산을 그대로 다시 한다(auto_loop 이 orchestrator 를
      import 하므로 반대 방향 import 는 순환이 된다) — 고칠 때 둘 다 봐야 한다.
    """
    return images_per_round(profile, platform) * max(1, config.CREATIVE_COOLDOWN_DAYS)


def remaining_image_budget() -> int:
    """오늘 더 만들 수 있는 **이미지** 수. 예산은 천장일 뿐 — 실제로 멈추는 건
    stock_target/stock_count 의 재고 충족 판정이다(do_generate 참고).

    ⚠ 분모는 소재(creatives) 수가 아니라 실제 생성 횟수다. 재고를 재사용한
      소재와 loan 의 로컬 합성 전단은 돈도 GPU 도 쓰지 않으므로 예산을 쓰지
      않는다(db.images_generated_today 주석 참고)."""
    return max(0, config.image_daily_budget() - db.images_generated_today())


def image_budget_binds() -> bool:
    """이번 주기의 소재 수를 이미지 예산으로 조여야 하는가.

    예산의 단위는 '이미지 생성 횟수' 이고 need 의 단위는 '소재 건수' 다. 둘을
    비교해도 되는 건 소재 한 건이 그림 한 장을 부를 때뿐이다.
    IMAGE_GEN_LOCKED 가 켜져 있으면 showcase._gen_one·pamphlet.brief_from_doc
    이 호출 즉시 막히므로 이번 주기는 **한 장도** 만들 수 없다 — 전량 재고
    재사용이고 비용이 0 이다. 그런 주기까지 이 천장으로 묶으면, 고쳐 놓은
    분모가 0 에 머무는 바람에 제미나이 기본 천장 2 가 그대로 '플랫폼당 주기당
    소재 2건' 이 되어 C1 이 자리만 옮겨 되살아난다(2026-08-14 운영자 지시로
    IMAGE_GEN_LOCKED=1 이 켜져 있는 것이 현재의 정상 운영 상태다).
    """
    return not getattr(config, "IMAGE_GEN_LOCKED", False)


def free_images(prof: str, platform: str):
    """이 업종이 지금 **더 쓸 수 있는 서로 다른 그림 수**. 제한이 없으면 None.

    왜 필요한가 — 발행 게이트는 같은 **그림**을 CREATIVE_COOLDOWN_DAYS 안에 다시
    쓰지 못하게 막는다(db.image_cooldown_left: "플랫폼이 보는 건 '같은 그림'이지
    DB 행이 아니다"). 그런데 소재 생성은 '오늘 안 올린 채널 수'만 보고 만든다.

    기성 전단을 재사용하는 업종(loan)은 그림이 전단 수만큼뿐이다. 채널이 171곳이라도
    14일 동안 나갈 수 있는 건 전단 수만큼이다. 그 이상 만들면 전부 쿨다운에 막힌다.
      실측(2026-08-12): loan 미발행 소재 **62건 전부**가 쿨다운으로 막혀 있었고,
      그 62건이 쓰는 서로 다른 그림은 6개뿐이었다(29건이 한 파일을 공유).
      대기열만 쓰레기로 차고 발행 로그가 blocked 로 도배됐다.

    ⚠ 파일명을 갈라 쿨다운을 피하면 안 된다. 그림이 진짜 같은데 이름만 다르면
      같은 전단이 짧은 기간에 여러 방으로 도배된다 - 쿨다운이 막으려는 바로 그것이다.

    ⚠ 매번 새로 그리는 업종(content.source=docs, 예: inkcraft)은 그림 수에 제한이
      없다. None 을 돌려 기존 계산을 그대로 쓴다(무회귀).
    """
    try:
        import profiles as P
        prof_data = P.load(prof)
    except Exception:
        return None
    content = (prof_data.get("content") or {})
    if str(content.get("source") or "").strip() != "flyers":
        return None                      # 새로 생성하는 업종 - 그림 수 제한 없음

    d = P.resolve_dir(content.get("flyers_dir") or "")
    if not d or not d.is_dir():
        return None
    universe = len([p for p in d.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
    if not universe:
        return None

    # 이 업종이 쓴 그림 중 (a) 쿨다운 중이거나 (b) 아직 안 나간 소재가 잡고 있는 것
    with db.get_conn() as con:
        rows = con.execute(
            "SELECT DISTINCT cr.image_path, "
            "  (cr.id IN (SELECT creative_id FROM posts "
            "             WHERE status='posted' AND creative_id IS NOT NULL)) posted "
            "FROM creatives cr JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE ch.profile_key = ? AND ch.platform = ? "
            "  AND cr.image_path IS NOT NULL AND cr.image_path != ''",
            (prof, platform)).fetchall()
    taken = set()
    for path, posted in rows:
        if not posted:
            taken.add(path)              # 아직 안 나간 소재가 이미 잡고 있다
        elif db.image_cooldown_left(path, config.CREATIVE_COOLDOWN_DAYS):
            taken.add(path)              # 최근에 나가 쿨다운 중이다
    return max(0, universe - len(taken))


def do_generate(profiles, dry=False) -> int:
    """부족한 만큼만 소재를 만든다. 반환: 생성 요청한 건수."""
    made = 0
    for platform, profs in sorted(platforms_in_use(profiles).items()):
        room = remaining_today(platform, profiles)
        have = pending_count(platform)
        # ⚠ 진짜 천장은 상한이 아니라 **오늘 아직 안 올린 채널 수**다.
        #   CHANNEL_DAILY_LIMIT 이 1이라 한 방에 하루 한 건뿐이다. 채널이 45곳인데
        #   상한이 50이면 5건은 만들어도 갈 곳이 없다 — 이미지 비용만 버려진다.
        free_ch = free_channels(platform, profiles)
        # 여러 업종이 같은 플랫폼을 쓰면 남은 자리를 나눠 갖는다.
        # ⚠ 개수를 먼저 확정해야 per_cycle_cap 에 바닥값으로 넘길 수 있다.
        profs = sorted(p for p in profs if p)
        # ⚠ 하루치를 한 주기에 몰아 만들지 않는다.
        #   병목은 생성이 아니라 발행이다(건당 간격 90~300초 + 게시 ~30초).
        #   상한을 올리면 '만들 것'이 수백 건이 되는데, 그걸 다 만들면
        #     · 이미지 비용이 하루치 통째로 선지출되고
        #     · 생성에만 몇 시간이 걸려 주기가 무너지며
        #     · 중간에 로그인·차단으로 멈추면 만든 소재가 그대로 버려진다.
        #   한 주기에 내보낼 수 있는 만큼 + 약간의 여유만 만든다.
        #   단, 활성 업종 수 밑으로는 안 내려간다(per_cycle_cap 주석 참고 —
        #   안 그러면 짧은 주기에서 뒤쪽 업종이 영영 소재를 못 받는다).
        # ⚠ 변수명을 cap 으로 하지 않는다 — 아래 루프의 free_images() 결과가
        #   같은 이름을 쓰는데, 지금은 이 값을 쓰고 나서 재할당하니 안전하지만
        #   헷갈려서 나중에 순서를 바꾸면 조용히 틀린 값을 읽을 수 있다.
        plat_cap = per_cycle_cap(len(profs))
        # ⚠ 예산은 '목표' 가 아니라 '천장' 이다. 실제 **생성량**을 정하는 건
        #   아래 재고 목표 체크다 — 재고가 차면 그 업종은 새 그림 없이 재고만
        #   돌린다(소재는 계속 나온다).
        #   이 min() 은 설정 실수(잘못된 상한)로 무한정 만들어지는 것만 막는다.
        #   ⚠ 단위가 다르다 — 예산은 '이미지 생성 횟수', need 는 '소재 건수'.
        #     그림을 한 장도 만들 수 없는 주기(생성 잠금)에는 천장을 적용하지
        #     않는다(image_budget_binds 주석 참고).
        budget = remaining_image_budget()
        binds = image_budget_binds()
        need = min([room, free_ch, plat_cap] + ([budget] if binds else [])) - have
        log(f"  [{platform}] 여유 {room} · 남은 채널 {free_ch} · 대기 {have}"
            f" · 주기당 {plat_cap} · 오늘 예산 {budget}"
            f"{'' if binds else '(재사용만 — 미적용)'} → 만들 것 {max(0, need)}")
        if need <= 0:
            continue
        for i, prof in enumerate(profs):
            share = need // len(profs) + (1 if i < need % len(profs) else 0)
            if share <= 0:
                continue
            # 재고가 목표에 닿았으면 **새 그림을** 더 만들지 않는다. 이게
            # 생성이 0 으로 수렴하는 지점이다 — 예산은 천장이고, 멈추는 건
            # 이 조건이다.
            # ⚠ 여기서 continue 로 run_by_profile 을 통째로 건너뛰면 안 된다.
            #   재고를 순환시키는 코드(_round_pool·pick_for_channel)가
            #   run_campaign **안에** 있어서, 부르지 않으면 소재가 한 건도
            #   안 생기고 발행할 것도 사라진다. 기본값 그대로 머지했다면
            #   활성 채널 134곳이 그날로 조용해졌을 자리다(2026-09-08 전수
            #   리뷰 C2). 멈춰야 하는 건 '생성' 이지 '주기' 가 아니다.
            # ⚠ profile 만이 아니라 platform 도 함께 본다(stock_target·
            #   stock_count 주석 참고) — 업종 전체로 보면 재고가 몰린
            #   플랫폼이 재고 없는 플랫폼의 부족을 가린다.
            tgt = stock_target(prof, platform)
            reuse_only = bool(tgt and stock_count(prof, platform) >= tgt)
            if reuse_only:
                # 운영자는 '이 업종은 이제 재고로만 돈다' 를 계속 볼 수 있어야 한다.
                log(f"    {prof}: 재고 목표 {tgt}장 충족 → 재사용만(새 그림 없음)")
            # ★ 쓸 수 있는 그림이 남은 만큼만 만든다(free_images 주석 참고).
            #   전단 재사용 업종은 그림 수가 천장이라, 이걸 안 보면 만든 소재가
            #   전부 쿨다운에 막힌 채 대기열에만 쌓인다.
            cap = free_images(prof, platform)
            if cap is not None and share > cap:
                log(f"    {prof}: 쓸 수 있는 전단 {cap}장뿐 → {share}건 중 {cap}건만 생성")
                share = cap
            if share <= 0:
                log(f"    {prof}: 쓸 수 있는 전단 없음(전부 쿨다운/사용 중) → 건너뜀")
                continue
            log(f"    {prof}: {share}건 생성"
                + ("(재고 재사용)" if reuse_only else ""))
            if dry:
                continue
            cmd = ["tools/run_by_profile.py", "--profile", prof,
                   "--limit", str(share)]
            if reuse_only:
                cmd.append("--reuse-only")
            ok, out = run(cmd, env={"AUTOAD_PROFILE": prof})
            if not ok:
                log(f"      ✗ 실패 — {out.strip().splitlines()[-1][:120] if out.strip() else ''}")
                continue
            made += share
    return made


def main():
    ap = argparse.ArgumentParser()
    # ⚠ 생략하면 OPT_IN_ONLY 를 뺀 전부다. 지금 OPT_IN_ONLY 는 비어 있으므로
    #   loan 도 포함된다(2026-08-10 운영자 지시, 위 OPT_IN_ONLY 주석 참고).
    ap.add_argument("--profiles",
                    help="쉼표로 구분한 업종(생략하면 활성 채널이 있는 전부)")
    ap.add_argument("--interval", type=int, default=1200,
                    help="주기(초). 기본 1200=20분")
    ap.add_argument("--dry-run", action="store_true",
                    help="무엇을 할지만 보여주고 아무것도 바꾸지 않는다")
    ap.add_argument("--once", action="store_true", help="한 주기만 돌고 끝낸다")
    a = ap.parse_args()

    # ── 이중 실행 차단 ────────────────────────────────────────
    # 창을 두 번 열면 두 루프가 같은 대기 캠페인을 각자 집어 같은 방에 두 번
    # 올린다. ⚠ 실제로 2026-08-10 에 창 2개가 아무 저항 없이 동시에 떴다.
    # 그날 중복 발행까지 가지 않은 건 순전히 채널별 일일 상한(1건)에 이미
    # 걸려 있었기 때문이다 — 상한에 여유가 있는 아침이었다면 그대로 나갔다.
    #
    # dry-run 은 아무것도 내보내지 않으므로 잠금에서 뺀다. 실 루프가 도는
    # 중에도 무엇을 할지 들여다볼 수 있어야 한다(막으면 점검 자체가 막힌다).
    if not a.dry_run:
        try:
            singleton.acquire("auto_loop")
        except singleton.AlreadyRunning as e:
            log(f"⚠ {e}")
            log("  이미 자동광고 루프가 돌고 있습니다 — 이 창은 닫으세요.")
            log("  (무엇을 할지만 보려면 --dry-run 을 붙이세요. 잠금 없이 돕니다)")
            return EXIT_ALREADY_RUNNING

    db.init_db()
    profiles = None
    if a.profiles:
        profiles = {p.strip() for p in a.profiles.split(",") if p.strip()}
    else:
        profiles = {c["profile_key"] for c in db.list_channels(enabled_only=True)
                    if c["profile_key"]} - OPT_IN_ONLY

    _INTERVAL[0] = a.interval
    log(f"자동 루프 시작 · 주기 {a.interval}초 · 업종 {sorted(profiles)}")
    hrs = (f"{config.POST_HOURS_START}~{config.POST_HOURS_END}시"
           if config.POST_HOURS_START != config.POST_HOURS_END else "종일")
    caps = " · ".join(f"{p} {config.daily_limit(p)}"
                      for p in sorted(platforms_in_use(profiles)))
    log(f"발행 허용 {hrs} · 계정당 하루 [{caps}]건 · 주기당 소재 {per_cycle_cap()}건")
    if OPT_IN_ONLY - profiles:
        log(f"제외된 업종: {sorted(OPT_IN_ONLY - profiles)} "
            f"(넣으려면 --profiles 에 명시)")
    if a.dry_run:
        log("*** DRY-RUN — 아무것도 발행/생성하지 않습니다 ***")

    backoff = 0          # 로그인 실패 연속 횟수
    n = 0
    while True:
        n += 1
        log()
        log(f"── 주기 #{n} ──────────────────────────────")

        ok_now, why = hours_ok_now()
        if not ok_now:
            log(f"  쉬는 시간: {why}")
        else:
            # ⚠ 한 주기의 예외로 루프 전체가 죽으면 안 된다. 예전에는 예외가
            #   그대로 올라가 프로세스가 끝났고, '자동광고 실행.bat' 이 60초 뒤
            #   다시 띄우기는 하지만 그 사이 원인이 콘솔과 함께 사라졌다.
            #   여기서 잡아 로그로 남기고 다음 주기로 넘어간다.
            try:
                done, login_failed = do_publish(a.dry_run)
            except Exception as e:
                import traceback
                log(f"  ⚠ 발행 단계 오류: {type(e).__name__}: {e}")
                for ln in traceback.format_exc().splitlines():
                    log(f"      {ln}")
                done, login_failed = 0, False
            log(f"  발행 {done}건")

            if login_failed:
                backoff += 1
                wait = min(a.interval * (2 ** backoff), 6 * 3600)
                plats = ", ".join(sorted(platforms_in_use(profiles)))
                log(f"  ⚠ 로그인 실패({backoff}회 연속). 캡차·2단계 인증은 "
                    f"사람이 풀어야 합니다.")
                log(f"    {LOGIN_HINT.format(platform=plats)}")
                log(f"    {wait//60}분 뒤에 다시 봅니다(계정 잠김 방지).")
                if a.once:
                    return 1
                time.sleep(wait)
                continue
            backoff = 0

            try:
                made = do_generate(profiles, a.dry_run)
            except Exception as e:
                import traceback
                log(f"  ⚠ 소재 생성 오류: {type(e).__name__}: {e}")
                for ln in traceback.format_exc().splitlines():
                    log(f"      {ln}")
                made = 0
            log(f"  소재 {made}건 생성")

        if a.once:
            return 0
        log(f"  다음 주기까지 {a.interval//60}분 대기")
        time.sleep(a.interval)


if __name__ == "__main__":
    _utf8_stdout()
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        log("중단됨")
        sys.exit(0)
