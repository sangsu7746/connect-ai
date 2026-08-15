"""GEO 산출물 — 유튜브 설명란 (spec §7 GEO 3층 중 '설명란 자동 생성').
두괄식 요약 박스(객관 단정문 3줄) + 챕터 타임스탬프(h2 대응) + 원문 출처."""


def _ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def build_description(scenes: list[dict], chapters: list[str],
                      posts: list[dict], summary_lines: list[str]) -> str:
    lines = ["■ 핵심 요약"]
    lines += [f"- {s}" for s in summary_lines[:3]]
    if chapters:
        lines.append("")
        lines.append("⏱ 챕터")
        lines.append("0:00 인트로")            # 유튜브 챕터는 0:00부터 시작해야 인식된다
        t = 0.0
        marks = {}
        for s in scenes:
            if s["role"] == "chapter" and s["chapter"] not in marks:
                marks[s["chapter"]] = t
            t += s["sec"]
        for ch in chapters:
            if ch in marks:
                lines.append(f"{_ts(marks[ch])} {ch}")
    lines.append("")
    lines.append("📚 참고한 글")
    for p in posts:
        lines.append(f"- {p.get('title', '')} {p.get('url', '')}".rstrip())
    return "\n".join(lines)
