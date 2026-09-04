"""자막 PNG 렌더 (spec §9 — EstateReels captionCanvas 이식).
hook/cta는 중앙 대형, 나머지는 하단 로어서드 + 스크림 그라디언트.
프레임 크기 투명 PNG로 만들어 ffmpeg overlay 0:0 한 번으로 얹는다."""
import io

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]

_CENTER_ROLES = ("hook", "cta")


def load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_outlined(draw, xy, text, font, fill):
    x, y = xy
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 220))
    draw.text((x, y), text, font=font, fill=fill)


def render_caption(caption: str, sub: str, role: str,
                   width: int, height: int) -> bytes:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if not (caption or sub):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    if role in _CENTER_ROLES:
        font = load_font(max(int(height * 0.048), 20))
        sub_font = load_font(max(int(height * 0.030), 14))
        lines = _wrap(draw, caption, font, int(width * 0.86))
        sub_lines = _wrap(draw, sub, sub_font, int(width * 0.86)) if sub else []
        line_h = int(height * 0.062)
        sub_line_h = int(height * 0.042)
        total = len(lines) * line_h + (len(sub_lines) * sub_line_h if sub else 0)
        y = (height - total) // 2
        for line in lines:
            w = draw.textlength(line, font=font)
            _draw_outlined(draw, ((width - w) // 2, y), line, font,
                           (255, 255, 255, 255))
            y += line_h
        if sub:
            for line in sub_lines:
                w = draw.textlength(line, font=sub_font)
                _draw_outlined(draw, ((width - w) // 2, y), line, sub_font,
                               (255, 224, 130, 255))
                y += sub_line_h
    else:
        # 하단 스크림 그라디언트 (하단 28% 영역)
        scrim_h = int(height * 0.28)
        for i in range(scrim_h):
            a = int(160 * (i / scrim_h))
            draw.line([(0, height - scrim_h + i), (width, height - scrim_h + i)],
                      fill=(0, 0, 0, a))
        font = load_font(max(int(height * 0.036), 16))
        sub_font = load_font(max(int(height * 0.026), 12))
        lines = _wrap(draw, caption, font, int(width * 0.9))
        sub_lines = _wrap(draw, sub, sub_font, int(width * 0.9)) if sub else []
        line_h = int(height * 0.048)
        sub_line_h = int(height * 0.036)
        y = height - int(height * 0.06) - len(lines) * line_h - \
            (len(sub_lines) * sub_line_h if sub else 0)
        for line in lines:
            w = draw.textlength(line, font=font)
            _draw_outlined(draw, ((width - w) // 2, y), line, font,
                           (255, 255, 255, 255))
            y += line_h
        if sub:
            for line in sub_lines:
                w = draw.textlength(line, font=sub_font)
                _draw_outlined(draw, ((width - w) // 2, y), line, sub_font,
                               (200, 200, 210, 255))
                y += sub_line_h

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
