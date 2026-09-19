# -*- coding: utf-8 -*-
"""auto_loop.run() 이 손자 프로세스 때문에 멈추지 않는지.

2026-08-13 실제 사고: 발행 주기가 6시간 24분 멈춰 그동안 발행이 0건이었다.
timeout=1800 은 제때 발동했는데도 멈췄다 — subprocess.run 이 타임아웃 뒤
파이프를 비우려고 다시 기다리는데, 손자(chromedriver·chrome)가 그 파이프의
쓰기 핸들을 물고 살아 있어 EOF 가 오지 않았기 때문이다.

publish_campaign 은 항상 chromedriver 를 띄우고 chromedriver 는 chrome 을
띄운다. 손자가 생기는 건 예외가 아니라 정상 동작이다.
"""
import sys
import time
import textwrap
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import auto_loop as A


def _script(tmp_path, body):
    p = tmp_path / "child.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def test_child_output_is_captured(tmp_path):
    """평범한 경우 — 출력이 그대로 돌아와야 한다."""
    s = _script(tmp_path, """
        print("안녕 stdout")
        import sys; print("안녕 stderr", file=sys.stderr)
    """)
    ok, out = A.run([s], timeout=60)
    assert ok
    assert "안녕 stdout" in out
    assert "안녕 stderr" in out, "stderr 도 합쳐서 돌려줘야 한다"


def test_failure_is_reported(tmp_path):
    s = _script(tmp_path, """
        import sys
        print("망함")
        sys.exit(1)
    """)
    ok, out = A.run([s], timeout=60)
    assert not ok
    assert "망함" in out, "실패해도 출력은 살아 있어야 원인을 본다"


def test_does_not_hang_when_grandchild_holds_the_pipe(tmp_path):
    """이 사고의 핵심.

    자식은 곧바로 끝나지만 손자가 stdout 을 물고 오래 산다.
    파이프로 받으면 부모는 손자가 죽을 때까지 못 빠져나온다.
    """
    grand = _script(tmp_path, """
        import time
        time.sleep(90)
    """)
    s = tmp_path / "parent.py"
    s.write_text(textwrap.dedent(f"""
        import subprocess, sys
        # stdout 을 물려준 채 손자를 띄우고 자식은 즉시 끝난다
        subprocess.Popen([sys.executable, r"{grand}"])
        print("자식 끝")
    """), encoding="utf-8")

    t0 = time.time()
    ok, out = A.run([str(s)], timeout=120)
    took = time.time() - t0

    assert took < 30, (
        f"손자가 살아 있다고 {took:.0f}초나 붙들렸다 — 파이프 교착이 되살아났다")
    assert ok
    assert "자식 끝" in out


def test_timeout_kills_the_whole_tree(tmp_path):
    """타임아웃 때 손자까지 죽여야 한다. 자식만 죽이면 고아가 쌓인다."""
    marker = tmp_path / "grandchild_alive.txt"
    grand = _script(tmp_path, f"""
        import time
        for _ in range(60):
            open(r"{marker}", "w").write("살아있음")
            time.sleep(1)
    """)
    s = tmp_path / "parent.py"
    s.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, r"{grand}"])
        time.sleep(60)
    """), encoding="utf-8")

    ok, out = A.run([str(s)], timeout=5)
    assert not ok
    assert "타임아웃" in out

    time.sleep(3)
    marker.unlink(missing_ok=True)
    time.sleep(3)
    assert not marker.exists(), "손자가 아직 살아서 파일을 다시 쓰고 있다"


def test_kill_tree_survives_dead_pid():
    """이미 죽은 pid 에 대고 불러도 예외로 루프를 멈추면 안 된다."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    A._kill_tree(p.pid)          # 예외가 나면 실패
