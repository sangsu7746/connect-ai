"""발행 브릿지 (spec §12-A, B안). 쿠팡 블로그 프로젝트의 publish_generic.py를
subprocess로 호출한다. 이 앱은 크리덴셜을 다루지 않는다 — 세션은 그쪽 프로젝트
소관. handoff/result는 JSON 파일·stdout 마지막 줄."""
import json
import pathlib
import subprocess
import sys
import tempfile

from .config import settings

TIMEOUT_S = 300


def _script() -> pathlib.Path | None:
    if not settings.publisher_dir:
        return None
    p = pathlib.Path(settings.publisher_dir) / "publish_generic.py"
    return p if p.exists() else None


def available() -> bool:
    return _script() is not None


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
        r = subprocess.run([sys.executable, str(script), "--file", handoff],
                           cwd=settings.publisher_dir, capture_output=True,
                           text=True, timeout=TIMEOUT_S, encoding="utf-8")
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
        return {"ok": False, "url": "",
                "error": f"발행 결과를 파싱하지 못함 (exit {r.returncode})"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "url": "", "error": "발행 타임아웃(5분) — 브라우저 로그인 대기 중일 수 있음"}
    except Exception as e:
        return {"ok": False, "url": "", "error": f"발행 실행 실패: {type(e).__name__}"}
    finally:
        try:
            pathlib.Path(handoff).unlink(missing_ok=True)
        except OSError:
            pass
