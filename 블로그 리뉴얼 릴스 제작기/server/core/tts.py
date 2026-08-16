"""Edge-TTS 나레이션 합성 (spec §9). 씬별 병렬(동시 4)·파일 캐시·실패 무음.
네트워크 실패나 개별 씬 실패는 해당 씬을 결과에서 빼는 것으로 처리한다 —
렌더는 무음으로 계속된다 (spec §10)."""
import asyncio
import hashlib
import os
import pathlib

import edge_tts

from .config import settings

_CONCURRENCY = 4


def tts_dir() -> pathlib.Path:
    p = os.environ.get("APP_TTS_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(text: str, voice: str) -> pathlib.Path:
    key = hashlib.sha256(f"{text}|{voice}".encode()).hexdigest()[:32]
    return tts_dir() / f"{key}.mp3"


async def _synth_one(text: str, voice: str, out: pathlib.Path) -> bool:
    tmp = out.parent / (out.name + ".tmp")
    try:
        await edge_tts.Communicate(text, voice).save(str(tmp))
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return True
        tmp.unlink(missing_ok=True)
        return False
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def synth_scenes(scenes: list[dict], voice: str | None = None,
                 on_done=None) -> dict:
    v = voice or settings.tts_voice
    todo = [(s["idx"], s["narration"]) for s in scenes
            if (s.get("narration") or "").strip()]
    results: dict = {}
    # 같은 텍스트는 한 번만 합성 — 고정 tmp 경로 동시 쓰기(Windows PermissionError
    # 연쇄→전체 무음)와 중복 합성 낭비를 함께 제거
    by_text: dict[str, list[int]] = {}
    for idx, text in todo:
        by_text.setdefault(text, []).append(idx)

    async def _run_all():
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def one(text: str, idxs: list[int]):
            out = _cache_path(text, v)
            try:
                if out.exists() and out.stat().st_size > 0:
                    for i in idxs:
                        results[i] = out
                    return
                async with sem:
                    if await _synth_one(text, v, out):
                        for i in idxs:
                            results[i] = out
            finally:
                if on_done:
                    for _ in idxs:
                        on_done()

        await asyncio.gather(*(one(t, idxs) for t, idxs in by_text.items()))

    asyncio.run(_run_all())
    return results
