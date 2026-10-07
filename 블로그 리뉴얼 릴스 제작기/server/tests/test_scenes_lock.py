import threading
from core import locks


def test_scenes_lock_exists_and_is_lock():
    assert isinstance(locks.scenes_lock, type(threading.Lock()))


def test_images_and_scripts_use_lock(monkeypatch):
    """소스 검사: 병합-쓰기 구간이 락을 잡는지 (정적 확인 — 동작 경합은 M3 회귀 테스트가 커버)"""
    import inspect
    import api.images as im
    import api.scripts as sc

    assert "scenes_lock" in inspect.getsource(im), "images.py should use scenes_lock"
    assert "scenes_lock" in inspect.getsource(sc._update_scene), "_update_scene should use scenes_lock"


