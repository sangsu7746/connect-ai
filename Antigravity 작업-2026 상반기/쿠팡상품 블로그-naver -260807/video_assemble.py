"""
PIL 프레임 + 음성 → MP4. ffmpeg 를 직접 부른다.

## 왜 moviepy 를 안 쓰는가
moviepy 2.2.1 은 `pillow<12.0` 을 요구한다. 그런데 이 PC 의 rembg 는 `pillow>=12.1`,
pdfplumber 는 `pillow>=12.2` 를 요구한다. 셋이 함께 설치될 수 없다.
moviepy 를 넣으면 Pillow 가 11.3 으로 내려가면서 PhotoMagic(rembg) 쪽이 깨진다.
그래서 moviepy 를 빼고 ffmpeg 를 직접 부른다. ffmpeg 는 이미 깔려 있고(8.1.2),
하는 일도 프레임 잇기와 오디오 얹기뿐이라 중간 라이브러리가 필요 없다.

reels_generator 는 moviepy 가 없으면 조용히 빈 영상 경로를 반환했다. 여기서는
ffmpeg 가 실패하면 예외를 던진다 — 없는 파일의 경로를 성공처럼 돌려주지 않는다.
"""
import os
import shutil
import subprocess
import tempfile

#: 프레임을 파이프로 넣을 때 쓰는 원본 화면비. 릴스 세로 규격.
WIDTH, HEIGHT = 1080, 1920
FPS = 30
BITRATE = "6M"


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "ffmpeg 를 찾을 수 없습니다. https://www.gyan.dev/ffmpeg/builds/ 에서 받아 "
            "PATH 에 넣어 주세요.")
    return exe


def _run(args: list) -> None:
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        tail = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("ffmpeg 실패: " + " / ".join(tail[-4:]))


def scene_clip(frames, audio_path: str, out_path: str, fps: int = 15) -> str:
    """
    PIL 이미지 목록 하나를 한 장면 영상으로 만든다.

    프레임은 파이프로 넘긴다. 수백 장을 PNG 로 디스크에 썼다 지우는 것보다 빠르고,
    임시파일이 남지 않는다.
    """
    if not frames:
        raise ValueError("프레임이 비어 있습니다.")

    w, h = frames[0].size
    args = [
        _ffmpeg(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
    ]
    has_audio = audio_path and os.path.exists(audio_path)
    if has_audio:
        args += ["-i", audio_path]

    args += [
        "-c:v", "libx264", "-preset", "medium", "-b:v", BITRATE,
        "-pix_fmt", "yuv420p", "-r", str(FPS),
    ]
    if has_audio:
        # 오디오가 프레임보다 길면 영상 마지막 칸이 잘린다. 짧은 쪽에 맞춘다.
        args += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    args.append(out_path)

    p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for img in frames:
            p.stdin.write(img.convert("RGB").tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            p.stdin.close()
        except Exception:
            pass
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"장면 인코딩 실패: {err.strip()[:300]}")
    return out_path


def concat(clip_paths: list, out_path: str) -> str:
    """장면 영상들을 하나로 잇는다."""
    clips = [c for c in clip_paths if c and os.path.exists(c)]
    if not clips:
        raise ValueError("이을 장면이 없습니다.")
    if len(clips) == 1:
        shutil.copy2(clips[0], out_path)
        return out_path

    # concat demuxer 는 목록 파일을 받는다. 경로에 한글·공백이 있어도
    # 작은따옴표로 감싸면 된다(경로 안의 작은따옴표만 이스케이프).
    fd, listfile = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for c in clips:
                f.write("file '%s'\n" % os.path.abspath(c).replace("'", r"'\''"))
        # 모든 장면을 같은 설정으로 인코딩했으므로 재인코딩 없이 붙인다.
        _run([_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", listfile, "-c", "copy", out_path])
    finally:
        try:
            os.unlink(listfile)
        except Exception:
            pass

    if not os.path.exists(out_path):
        raise RuntimeError("합본 파일이 만들어지지 않았습니다.")
    return out_path


def audio_duration(path: str) -> float:
    """오디오 길이(초). 못 읽으면 0."""
    exe = shutil.which("ffprobe")
    if not exe or not path or not os.path.exists(path):
        return 0.0
    r = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True)
    try:
        return float((r.stdout or b"").decode().strip())
    except Exception:
        return 0.0


def selftest() -> bool:
    from PIL import Image
    tmp = tempfile.mkdtemp()
    try:
        frames = [Image.new("RGB", (216, 384), (i * 8 % 255, 40, 90)) for i in range(15)]
        a = scene_clip(frames, "", os.path.join(tmp, "a.mp4"), fps=15)
        b = scene_clip(frames, "", os.path.join(tmp, "b.mp4"), fps=15)
        out = concat([a, b], os.path.join(tmp, "out.mp4"))
        size = os.path.getsize(out)
        print(f"자체검사 통과 · 합본 {size:,} bytes · 길이 {audio_duration(out):.1f}초")
        return size > 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    selftest()
