"""발행 브릿지 (spec §12-A, B안). 쿠팡 블로그 프로젝트의 publish_generic.py를
subprocess로 호출한다. 이 앱은 크리덴셜을 다루지 않는다 — 세션은 그쪽 프로젝트
소관. handoff/result는 JSON 파일·stdout 마지막 줄."""
import datetime
import json
import pathlib
import subprocess
import sys
import tempfile

from .config import settings

TIMEOUT_S = 600


def _script() -> pathlib.Path | None:
    if not settings.publisher_dir:
        return None
    p = pathlib.Path(settings.publisher_dir) / "publish_generic.py"
    return p if p.exists() else None


def _python() -> str:
    """publish_generic.py 를 실행할 인터프리터를 고른다.

    이 앱의 venv(server/.venv) 에는 selenium 이 없다 — sys.executable 로 그냥
    실행하면 쿠팡 블로그 프로젝트(publisher_dir)의 publish_generic.py 가
    ModuleNotFoundError 로 100% 실패한다. publisher_dir 안에 자체 venv가 있으면
    그 인터프리터를 쓰고, 없으면 sys.executable 로 폴백한다.
    """
    if settings.publisher_dir:
        cand = pathlib.Path(settings.publisher_dir) / ".venv" / "Scripts" / "python.exe"
        if cand.exists():
            return str(cand)
    return sys.executable


def available() -> bool:
    return _script() is not None


def logs_dir() -> pathlib.Path:
    d = pathlib.Path(__file__).resolve().parents[1] / "data" / "publish_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(platform: str, r) -> None:
    """발행 시도의 콘솔 출력을 남긴다. 실패 원인이 브릿지 밖(에디터 자동화)에
    있을 때 여기 말고는 단서가 없다 — 실측에서 네이버 실패를 진단하지 못했다."""
    try:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        (logs_dir() / f"{stamp}_{platform}.log").write_text(
            f"exit={r.returncode}\n\n[stdout]\n{r.stdout or ''}\n"
            f"\n[stderr]\n{r.stderr or ''}\n", encoding="utf-8")
    except OSError:
        pass


def publish(platform: str, title: str, body_md: str, category: str = "") -> dict:
    script = _script()
    if not script:
        return {"ok": False, "url": "",
                "error": "PUBLISHER_DIR 미설정 또는 publish_generic.py 없음"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump({"platform": platform, "title": title,
                   "body_md": body_md, "category": category},
                  f, ensure_ascii=False)
        handoff = f.name
    try:
        r = subprocess.run([_python(), str(script), "--file", handoff],
                           cwd=settings.publisher_dir, capture_output=True,
                           text=True, timeout=TIMEOUT_S, encoding="utf-8",
                           errors="replace")
        _write_log(platform, r)
        for line in reversed((r.stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    out = json.loads(line)
                    return {"ok": bool(out.get("ok")),
                            "url": out.get("url", ""),
                            "error": out.get("error", "")}
                except json.JSONDecodeError:
                    continue
        tail = (r.stderr or "").strip()[-300:]
        return {"ok": False, "url": "",
                "error": f"발행 결과를 파싱하지 못함 (exit {r.returncode})"
                         + (f" — {tail}" if tail else "")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "url": "",
                "error": "발행 타임아웃(10분) — 브라우저 로그인 대기였을 수 있고, "
                         "실제로 발행됐을 수도 있으니 블로그 관리에서 먼저 확인하세요"}
    except Exception as e:
        return {"ok": False, "url": "", "error": f"발행 실행 실패: {type(e).__name__}"}
    finally:
        try:
            pathlib.Path(handoff).unlink(missing_ok=True)
        except OSError:
            pass
