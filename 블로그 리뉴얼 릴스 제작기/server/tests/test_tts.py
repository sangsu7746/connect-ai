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

def test_interrupted_write_leaves_no_final_file(monkeypatch, tmp_path):
    """save()가 경로에 부분 바이트를 쓴 뒤 죽는 경우 — 예외 경로에서 tmp가 정리되고 최종 캐시 경로가 오염되지 않음을 검증한다. (원자화의 본질 보호 대상은 프로세스 급사 시 최종 경로 무오염 — 인프로세스로는 재현 불가)"""
    _setup(monkeypatch, tmp_path)
    class PartialCommunicate:
        def __init__(self, text, voice, **kw):
            self.text = text
        async def save(self, path):
            pathlib.Path(path).write_bytes(b"partial")   # 대상 경로에 쓰다가
            raise RuntimeError("connection dropped")      # 중단
    monkeypatch.setattr(tts.edge_tts, "Communicate", PartialCommunicate)
    out = tts.synth_scenes(SCENES[:1])
    assert out == {}                                      # 실패로 처리
    d = pathlib.Path(str(tmp_path / "tts"))
    assert list(d.glob("*.mp3")) == []                    # 최종 경로 무오염
    assert list(d.glob("*.tmp")) == []                    # 임시 잔재도 정리

def test_duplicate_narration_synthesized_once(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    scenes = [{"idx": 0, "role": "point", "narration": "같은 문장"},
              {"idx": 1, "role": "cta", "narration": "같은 문장"}]
    ticks = []
    out = tts.synth_scenes(scenes, on_done=lambda: ticks.append(1))
    assert set(out.keys()) == {0, 1} and out[0] == out[1]
    assert len([c for c in FakeCommunicate.calls
                if c[0] == "같은 문장"]) == 1        # 1회만 합성
    assert len(ticks) == 2                            # tick 계약 유지
