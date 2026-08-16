"""이미지 생성·캐시·폴백 (spec §8). 캐시 키 = sha256(prompt|negative|style|WxH).
폴백(그라디언트 카드)은 캐시에 넣지 않는다 — SD 복구 후 같은 키로 재생성돼야 한다."""
import datetime
import hashlib
import io
import os
import pathlib

from PIL import Image

from . import sd_webui, style_packs

SIZE = {"reels": (576, 1024), "long": (1024, 576)}


def images_dir() -> pathlib.Path:
    p = os.environ.get("APP_IMAGES_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient_card(color_hex: str, width: int, height: int) -> bytes:
    r, g, b = _hex_rgb(color_hex)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        row = (int(r * (0.35 + 0.5 * t)), int(g * (0.35 + 0.5 * t)),
               int(b * (0.35 + 0.5 * t)))
        for x in range(width):
            px[x, y] = row
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate(conn, image_prompt: str, style_id: str, fmt: str) -> dict:
    packs = style_packs.load()
    pack = packs.get(style_id) or packs["flat_vector"]
    width, height = SIZE[fmt]
    prompt = f"{pack['prefix']}, {image_prompt}" if image_prompt else pack["prefix"]
    negative = f"{style_packs.COMMON_NEGATIVE}, {pack['negative']}".strip(", ")
    key = hashlib.sha256(
        f"{prompt}|{negative}|{style_id}|{width}x{height}".encode()).hexdigest()[:32]

    row = conn.execute("SELECT file FROM images WHERE hash=?", (key,)).fetchone()
    if row and (images_dir() / row["file"]).exists():
        return {"file": row["file"], "cached": True, "fallback": False}

    fname = f"{key}.png"
    try:
        data = sd_webui.txt2img(prompt, negative, width, height)
    except sd_webui.SDError:
        data = gradient_card(pack["color"], width, height)
        fb = f"fb_{key}.png"
        (images_dir() / fb).write_bytes(data)
        return {"file": fb, "cached": False, "fallback": True}

    (images_dir() / fname).write_bytes(data)
    conn.execute("""INSERT OR REPLACE INTO images(hash, style_id, prompt, width,
                    height, file, created_at) VALUES(?,?,?,?,?,?,?)""",
                 (key, style_id, prompt, width, height, fname,
                  datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return {"file": fname, "cached": False, "fallback": False}
