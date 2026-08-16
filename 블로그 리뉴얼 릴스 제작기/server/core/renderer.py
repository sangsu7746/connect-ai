"""ffmpeg 렌더러 (spec §9 — EstateReels ffmpegService 2단계 구조 이식).
① 씬 클립: 이미지 1.25배 스케일→zoompan(줌인)→자막 PNG overlay→무음 트랙
② concat -c copy(자막이 구워져 재인코딩 불필요) → 실패 시 재인코딩 폴백
③ BGM 먹싱(volume 0.28, 루프, -shortest). 양쪽 모두 길이 클램프."""
import pathlib
import shutil
import subprocess

from . import captions, image_gen, style_packs

SIZE = {"reels": (1080, 1920), "long": (1920, 1080)}
FPS = 25


class RenderError(RuntimeError):
    pass


def _run(cmd: list, timeout: int = 600) -> None:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise RenderError(f"ffmpeg 시간 초과({timeout}s)")
    except Exception as e:
        raise RenderError(f"ffmpeg 실행 실패: {type(e).__name__}")
    if r.returncode != 0:
        tail = (r.stderr or "").strip()[-300:]
        raise RenderError(f"ffmpeg 실패 (exit {r.returncode}) — {tail}")


def _scene_image(scene: dict, category: str, fmt: str,
                 workdir: pathlib.Path) -> pathlib.Path:
    f = scene.get("image_file") or ""
    p = image_gen.images_dir() / f if f else None
    if p and p.exists():
        return p
    style = style_packs.load().get(
        style_packs.pick(scene["role"], category), {"color": "#4b5563"})
    w, h = image_gen.SIZE[fmt]
    out = workdir / f"grad_{scene['idx']}.png"
    out.write_bytes(image_gen.gradient_card(style["color"], w, h))
    return out


def _scene_clip(scene: dict, img: pathlib.Path, cap_png: pathlib.Path,
                fmt: str, workdir: pathlib.Path) -> pathlib.Path:
    w, h = SIZE[fmt]
    dur = max(float(scene["sec"]), 0.5)
    frames = max(round(dur * FPS), 1)
    out = workdir / f"clip_{scene['idx']:03d}.mp4"
    vf = (f"[0:v]scale={int(w * 1.25)}:{int(h * 1.25)},"
          f"zoompan=z='min(zoom+0.0011,1.16)':"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
          f"d={frames}:s={w}x{h}:fps={FPS}[bg];"
          f"[bg][1:v]overlay=0:0[v]")
    _run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", cap_png,
          "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
          "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
          "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out])
    return out


def _concat(clips: list[pathlib.Path], total_sec: float, out: pathlib.Path,
            workdir: pathlib.Path) -> None:
    lst = workdir / "concat.txt"
    lst.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips),
                   encoding="utf-8")
    base = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
            "-t", f"{total_sec:.2f}"]
    try:
        _run(base + ["-c", "copy", out], timeout=1800)
    except RenderError:
        _run(base + ["-c:v", "libx264", "-preset", "veryfast",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", out], timeout=1800)


def _mux_bgm(video: pathlib.Path, bgm_path: pathlib.Path, total_sec: float,
             out: pathlib.Path) -> None:
    _run(["ffmpeg", "-y", "-i", video, "-stream_loop", "-1", "-i", bgm_path,
          "-filter_complex", "[1:a]volume=0.28[b]",
          "-map", "0:v", "-map", "[b]", "-c:v", "copy", "-c:a", "aac",
          "-t", f"{total_sec:.2f}", "-shortest", out], timeout=1800)


def render_script(scenes: list[dict], fmt: str, category: str,
                  bgm_path: pathlib.Path | None, out_path: pathlib.Path,
                  workdir: pathlib.Path, on_scene=None) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = SIZE[fmt]
    total = sum(float(s["sec"]) for s in scenes)
    clips = []
    for scene in scenes:
        img = _scene_image(scene, category, fmt, workdir)
        cap = workdir / f"cap_{scene['idx']:03d}.png"
        cap.write_bytes(captions.render_caption(
            scene.get("caption") or "", scene.get("sub") or "",
            scene["role"], w, h))
        clips.append(_scene_clip(scene, img, cap, fmt, workdir))
        if on_scene:
            on_scene()
    if bgm_path:
        tmp = workdir / "noaudio.mp4"
        _concat(clips, total, tmp, workdir)
        try:
            _mux_bgm(tmp, bgm_path, total, out_path)
        except RenderError:
            # Path.replace는 크로스 드라이브(예: C: temp → D: videos)에서
            # OSError(WinError 17)를 낸다 — shutil.move로 대체 (BGM 실패 → 무음 진행)
            shutil.move(str(tmp), str(out_path))
    else:
        _concat(clips, total, out_path, workdir)
