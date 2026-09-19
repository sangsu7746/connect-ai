"""씬 테이블과 길이 배분 (spec §9). EstateReels-v2 storyboard.ts의 이식.
구조는 항상 hook → summary → (chapter → point*)* → twist → cta."""

PLAN = {("reels", 30): 7, ("reels", 60): 13,
        ("long", 60): 10, ("long", 180): 24,
        ("long", 300): 38, ("long", 600): 72}

CHAPTERS = {("long", 60): 2, ("long", 180): 3,
            ("long", 300): 4, ("long", 600): 6}

_WEIGHT = {"hook": 1.35, "cta": 1.45, "summary": 1.2, "chapter": 0.6,
           "point": 1.0, "twist": 1.0}
_MIN_SEC = 2.2


def _distribute(roles: list[str], total: int) -> list[float]:
    weights = [_WEIGHT[r] for r in roles]
    scale = total / sum(weights)
    secs = [max(_MIN_SEC, round(w * scale, 1)) for w in weights]
    secs[-1] = round(secs[-1] + (total - sum(secs)), 1)   # 오차는 cta가 흡수
    return secs


def build_scenes(fmt: str, duration: int, chapter_titles: list[str]) -> list[dict]:
    total = PLAN[(fmt, duration)]                          # 미지원 조합은 KeyError
    n_ch = CHAPTERS.get((fmt, duration), 0)
    titles = list(chapter_titles[:n_ch])
    while len(titles) < n_ch:
        titles.append(f"포인트 {len(titles) + 1}")

    roles: list[tuple[str, str]] = [("hook", ""), ("summary", "")]
    n_points = total - 4 - n_ch                            # hook+summary+twist+cta=4
    if n_ch:
        base, extra = divmod(n_points, n_ch)
        for i, t in enumerate(titles):
            roles.append(("chapter", t))
            for _ in range(base + (1 if i < extra else 0)):
                roles.append(("point", t))
    else:
        roles += [("point", "")] * n_points
    roles += [("twist", ""), ("cta", "")]

    secs = _distribute([r for r, _ in roles], duration)
    return [{"idx": i, "role": r, "sec": secs[i], "chapter": ch,
             "caption": (ch if r == "chapter" else ""), "sub": "",
             "narration": "", "image_prompt": ""}
            for i, (r, ch) in enumerate(roles)]
