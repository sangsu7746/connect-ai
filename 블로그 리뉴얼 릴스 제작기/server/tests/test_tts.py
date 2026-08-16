import asyncio
import pathlib
from core import tts

SCENES = [
    {"idx": 0, "role": "hook", "narration": "첫 나레이션"},
    {"idx": 1, "role": "point", "narration": "둘째 나레이션"},
    {"idx": 2, "role": "chapter", "narration": ""},          # 빈 나레이션 — 제외
]

class FakeCommunicate:
    calls: list = []
    fail_texts: set = set()

    def __init__(self, text, voice, **kw):
        self.text = text
        self.voice = voice

    async def save(self, path):
        FakeCommunicate.calls.append((self.text, self.voice))
        if self.text in FakeCommunicate.fail_texts:
            raise RuntimeError("tts down")
        pathlib.Path(path).write_bytes(b"mp3" + self.text.encode())

def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_TTS_DIR", str(tmp_path / "tts"))
    FakeCommunicate.calls = []
    FakeCommunicate.fail_texts = set()
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)

def test_synth_scenes_parallel_and_skip_empty(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    ticks = []
    out = tts.synth_scenes(SCENES, on_done=lambda: ticks.append(1))
    assert set(out.keys()) == {0, 1}
    assert all(p.exists() for p in out.values())
    assert len(ticks) == 2                      # narration 있는 씬 수만큼
    assert all(v == "ko-KR-SunHiNeural" for _, v in FakeCommunicate.calls)

def test_cache_hit_no_recall(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    tts.synth_scenes(SCENES)
    n = len(FakeCommunicate.calls)
    tts.synth_scenes(SCENES)                    # 같은 텍스트·보이스 → 캐시
    assert len(FakeCommunicate.calls) == n

def test_failure_excluded_not_raised(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    FakeCommunicate.fail_texts = {"첫 나레이션"}
    out = tts.synth_scenes(SCENES)
    assert set(out.keys()) == {1}               # 실패 씬 제외, 예외 없음

def test_voice_override_changes_cache_key(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = tts.synth_scenes(SCENES[:1])
    b = tts.synth_scenes(SCENES[:1], voice="ko-KR-InJoonNeural")
    assert a[0] != b[0]                         # 보이스별 캐시 분리
