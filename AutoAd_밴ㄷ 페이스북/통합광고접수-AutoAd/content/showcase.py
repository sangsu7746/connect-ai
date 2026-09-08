# -*- coding: utf-8 -*-
"""showcase.py — 콘텐츠형 소재: 제품이 실제로 만들어낸 결과물을 보여준다

왜 필요한가:
  브랜드 카드(배너)는 어느 모임에서나 '광고'로 읽힌다. 주제 중심 모임에서는
  그 자체로 규칙 위반이 되거나 승인 대기에 걸린다(실측).
  반대로 **제품이 만든 결과물**은 그 모임의 주제에 맞는 내용이라 환영받는다.

무엇을 만드는가:
  실제 생성 결과 4장을 한 장의 격자 이미지로 묶는다. 브랜드 배너가 아니다.
  출처(도구 이름·주소)는 하단에 작게 밝힌다 — 숨기지 않는다.
  ⚠ 만든 사람이 누구인지 감추면 안 된다. 걸리면 계정이 날아가고, 그게 맞다.

사용:
  from content import showcase
  showcase.make(profile_key="inkcraft", channel="facebook")
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

# 업종별 '무엇을 보여줄 것인가'. 결과물 자체를 보여주는 게 핵심이다.
SPECS = {
    "inkcraft": {
        "label": "타투 도안",
        # 기법(스타일)과 소재(모티프)를 분리한다.
        # ⚠ 소재를 프롬프트에 박아두면 몇 번을 돌려도 같은 늑대·제비가 나온다.
        #   같은 그림을 여러 그룹에 뿌리면 사람도 플랫폼도 '같은 글'로 본다.
        "styles": [
            ("블랙워크", "bold blackwork tattoo design of {subject}, heavy black ink, "
                       "high contrast, clean white background, flash sheet style"),
            ("라인워크", "fine single-line minimal tattoo design of {subject}, "
                       "thin delicate lines, clean white background"),
            ("올드스쿨", "traditional american old school tattoo design of {subject}, "
                       "bold outlines, limited flat colors, clean white background"),
            ("도트워크", "dotwork stippling tattoo design of {subject}, "
                       "black dots shading only, clean white background"),
        ],
        "motifs": [
            "a wolf head with a geometric moon",
            "a crescent moon with small wildflowers",
            "a swallow and a rose",
            "a mountain range inside a circle",
            "a koi fish among curling waves",
            "a snake coiled around a dagger",
            "an owl perched on a bare branch",
            "a lighthouse with crashing waves",
            "a hummingbird and a trumpet flower",
            "a compass rose with a sailing ship",
            "a stag head with antlers and pine branches",
            "a butterfly with stained-glass wing patterns",
            "a phoenix rising from flames",
            "a hand holding a blooming lotus",
            "a whale breaching under a starry sky",
            "a fox curled among fern leaves",
        ],
    },
    "weddingstudio": {
        "label": "웨딩 화보",
        # ⚠ 실존 인물이 아닌 **일반 커플**만 그린다. 이 서비스는 이용자가 올린
        #   얼굴로 결과물을 만드는데, 광고에 특정인처럼 보이는 사진을 쓰면
        #   '남의 사진을 쓴다'는 오해와 초상권 문제를 부른다.
        #   그래서 얼굴이 크게 드러나지 않는 구도(뒷모습·원경·실루엣)를 섞는다.
        "styles": [
            ("스튜디오", "elegant studio wedding portrait of an anonymous asian "
                       "couple in wedding attire, {subject}, soft diffused light, "
                       "clean seamless backdrop, editorial bridal photography"),
            ("야외", "outdoor wedding photo of an anonymous asian couple, "
                    "{subject}, natural golden hour light, shallow depth of field, "
                    "photojournalistic wedding photography"),
            ("한복", "traditional korean hanbok wedding portrait of an anonymous "
                    "couple, {subject}, warm hanok interior, refined and calm"),
            ("필름", "film-grain wedding photograph of an anonymous asian couple, "
                    "{subject}, muted tones, candid moment, analog look"),
        ],
        # 얼굴 정면 클로즈업을 피하는 장면 위주로 고른다.
        "motifs": [
            "seen from behind walking down a petal-strewn aisle",
            "silhouetted against a large window at dusk",
            "holding hands, framed on the joined hands only",
            "in a wide garden scene, figures small in the frame",
            "under a veil lifted by the wind, faces turned away",
            "a quiet moment on a staircase, viewed from a distance",
            "standing among tall grass at sunset, backlit",
            "beneath an old tree, seen from far away",
            "walking under paper lanterns at night",
            "a wide shot in an empty chapel",
            "on a stone path in a traditional courtyard",
            "framed through an open doorway, figures in the distance",
        ],
    },
    "lifealbum": {
        "label": "인생사진",
        # ⚠ weddingstudio 와 같은 원칙 - 이용자가 올린 얼굴로 만드는 서비스라
        #   광고에 특정인처럼 보이는 얼굴을 쓰면 오해와 초상권 문제를 부른다.
        #   얼굴이 크게 드러나지 않는 구도를 고른다.
        # ⚠ 고인·영정 등 추모를 연상시키는 장면은 넣지 않는다(프로필 note 참고).
        "styles": [
            ("필름", "film photograph, {subject}, muted natural tones, "
                    "grain, candid documentary feel, anonymous people"),
            ("스튜디오", "clean studio portrait scene, {subject}, soft even light, "
                       "seamless backdrop, editorial look, anonymous people"),
            ("여행", "travel photograph, {subject}, natural light, sense of place, "
                    "anonymous people, wide framing"),
            ("흑백", "black and white photograph, {subject}, gentle contrast, "
                    "timeless mood, anonymous people"),
        ],
        "motifs": [
            "a family walking together on a beach at sunset, seen from behind",
            "an elderly couple holding hands on a park bench, viewed from afar",
            "friends laughing around a table, shot over the shoulder",
            "a person standing at a train window, reflection only",
            "siblings running through a field, far from camera",
            "a couple under an umbrella in the rain, backs turned",
            "a family portrait silhouetted in a doorway",
            "someone reading by a large window, seen in profile",
            "a group on a hilltop at dawn, small in a wide landscape",
            "hands passing a cup of coffee, close on the hands",
            "a quiet street at night, a lone figure walking away",
            "a picnic scene from above, faces not visible",
        ],
    },
    "printcraft": {
        "label": "POD 디자인",
        "styles": [
            ("타이포", "minimal typographic poster design featuring {subject}, "
                      "bold geometric shapes, limited flat color palette"),
            ("라인아트", "single-line continuous line art of {subject}, "
                       "thin elegant strokes, lots of empty space"),
            ("빈티지", "vintage screen-print style illustration of {subject}, "
                     "muted retro palette, subtle paper texture in the artwork"),
            ("플랫", "flat vector illustration of {subject}, bold outlines, "
                    "cheerful saturated colors"),
        ],
        "motifs": [
            "a mountain range at sunrise", "a coffee cup with steam swirls",
            "a sailboat on calm waves", "a houseplant in a clay pot",
            "a bicycle with a basket of flowers", "a crescent moon over pine trees",
        ],
    },
    "mirizip": {
        "label": "인테리어 미리보기",
        "styles": [
            ("북유럽", "scandinavian interior of {subject}, light oak floor, "
                     "white walls, soft daylight, minimal furniture"),
            ("모던", "modern interior of {subject}, clean lines, neutral palette, "
                    "indirect lighting, uncluttered"),
            ("우드", "warm wood-toned interior of {subject}, natural textures, "
                    "cozy afternoon light"),
            ("미니멀", "minimalist interior of {subject}, muted tones, "
                     "very few objects, calm atmosphere"),
        ],
        "motifs": [
            "a small living room", "a bedroom with a low bed",
            "a kitchen with an island", "a home office nook",
            "a studio apartment", "a dining area by a window",
        ],
    },
    "proheadshot": {
        "label": "프로필 헤드샷 배경",
        # ⚠ 인물 자체는 만들지 않는다. sd_backend.NEG_FORCE 가 사람을 막고,
        #   이 업종은 '배경·조명 스타일' 을 보여준다.
        "styles": [
            ("스튜디오", "empty professional studio backdrop, {subject}, "
                       "soft key light, seamless paper background"),
            ("그라디언트", "smooth studio gradient backdrop, {subject}, "
                        "even soft lighting"),
            ("오피스", "softly blurred modern office background, {subject}, "
                     "shallow depth of field"),
            ("아웃도어", "softly blurred outdoor background, {subject}, "
                      "warm natural light, bokeh"),
        ],
        "motifs": [
            "cool grey tones", "warm beige tones", "deep navy tones",
            "soft charcoal tones", "muted sage tones", "clean white tones",
        ],
    },
    "colorcraft": {
        "label": "컬러링 도안",
        "styles": [
            ("굵은선", "coloring book page of {subject}, thick clean black outlines, "
                     "no shading, large simple areas to color"),
            ("가는선", "detailed coloring book page of {subject}, fine black line art, "
                     "intricate patterns, no shading"),
            ("만다라", "mandala-style coloring page incorporating {subject}, "
                     "symmetric radial pattern, black line art only"),
            ("장면", "coloring book scene featuring {subject}, simple background, "
                    "clear black outlines, no shading"),
        ],
        "motifs": [
            "a friendly dinosaur", "a hot air balloon over hills",
            "a cat napping on books", "a rocket and planets",
            "a garden with butterflies", "a castle on a hill",
        ],
    },
    "petportrait": {
        "label": "반려동물 초상화",
        # ⚠ 'portrait' 를 쓰면 안 된다 — sd_backend.NEG_FORCE 에 있는 그대로의
        #   토큰이라 긍정/부정 프롬프트가 스스로 싸운다(리뷰 Finding 1,
        #   proheadshot 과 같은 함정인데 여기만 놓쳤었다). 구도 의도는
        #   'close framed composition' 로 옮겨 대체한다.
        "styles": [
            ("유화", "oil painting of {subject}, close framed composition, "
                    "visible brush strokes, rich warm palette"),
            ("수채", "watercolor illustration of {subject}, close framed composition, "
                    "soft washes, delicate edges"),
            ("펜화", "ink pen illustration of {subject}, close framed composition, "
                    "fine cross-hatching, monochrome"),
            ("파스텔", "soft pastel illustration of {subject}, close framed composition, "
                     "gentle colors, smooth blended shading"),
        ],
        "motifs": [
            "a golden retriever", "a grey tabby cat", "a corgi in profile",
            "a beagle looking up", "a white rabbit", "a shiba inu smiling",
        ],
    },
    "wallpreview": {
        "label": "월아트 미리보기",
        "styles": [
            ("추상", "abstract wall art print of {subject}, organic shapes, "
                    "muted contemporary palette"),
            ("보태니컬", "botanical wall art print of {subject}, delicate linework, "
                       "soft natural tones"),
            ("기하", "geometric wall art print of {subject}, clean shapes, "
                    "balanced composition"),
            ("풍경", "minimal landscape wall art print of {subject}, "
                    "simplified forms, calm palette"),
        ],
        "motifs": [
            "rolling hills at dusk", "a single leaf study", "layered arches",
            "a calm sea horizon", "desert dunes", "a pale winter forest",
        ],
    },
    "nailpreview": {
        "label": "네일 디자인",
        # ⚠ 손·피부가 나오면 안 된다(NEG_FORCE). 네일 팁만 보여준다.
        "styles": [
            ("글리터", "set of press-on nail tips with {subject}, glitter finish, "
                     "arranged in a row, product photography on white"),
            ("젤", "set of press-on nail tips with {subject}, glossy gel finish, "
                  "arranged in a row, product photography on white"),
            ("무광", "set of press-on nail tips with {subject}, soft matte finish, "
                   "arranged in a row, product photography on white"),
            ("프렌치", "set of press-on nail tips with a french tip variation of "
                     "{subject}, arranged in a row, product photography on white"),
        ],
        "motifs": [
            "soft pink ombre", "milky white with tiny pearls",
            "sage green marble", "lavender with silver flecks",
            "warm nude with gold line", "sheer peach with fine glitter",
        ],
    },
}


def _font(size: int):
    for name in ("malgunbd.ttf", "malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_tile(img: Image.Image, size: int, margin: float = 0.07) -> Image.Image:
    """도안을 **자르지 않고** 칸에 맞춘다. 칸마다 크기도 고르게.

    ⚠ 예전에는 정중앙 정사각으로 crop 했다(min(w,h) 기준). 모델이 돌려주는
      그림은 비율이 제각각이라 두 가지가 동시에 망가졌다 — 실측 2026-08-12
      showcase_inkcraft_facebook_v20:
        · 가로로 긴 잉어 도안은 **좌우가 잘려** 지느러미가 사라졌다
        · 여백이 넓게 그려진 단검 도안은 여백째 축소돼 **깨알같이** 작았다
      한 격자 안에서 하나는 잘리고 하나는 파묻히니 '품질이 떨어진다'로 보인다.

    그래서 (1) 잉크가 있는 영역만 남기고 (2) 잘리지 않게 **축소해서** 넣는다.
    여백을 일정하게 두므로 칸마다 도안 크기가 비슷해진다.
    """
    im = img.convert("RGB")
    # 흰 배경 위의 잉크 영역 = 240 보다 어두운 픽셀. 종이 질감·미세한 회색은
    # 배경으로 본다(임계를 255 로 두면 아무것도 못 자른다).
    mask = im.convert("L").point(lambda v: 255 if v < 240 else 0)
    box = mask.getbbox()
    if box:
        im = im.crop(box)

    inner = max(1, int(size * (1 - margin * 2)))
    w, h = im.size
    if w and h:
        s = min(inner / w, inner / h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)

    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def tiles_for(platform: str) -> int:
    """칸 수는 채널 규격이 정한다.

    ⚠ 고정값(SHOWCASE_TILES) 하나로 둘 수 없다. 격자가 cols = min(n, 2) 라서
      칸 수가 곧 비율이다 — 2장이면 가로로 길고 4장이면 정사각이다.
      facebook(1200x630)에 4장을 쓰면 세로로 길어져 잘리고,
      band(1080x1080)에 2장을 쓰면 가로로 퍼져 여백이 남는다.
    """
    w, h = config.CHANNEL_SPECS.get(platform, (1080, 1080))
    return 2 if (h and w / h >= 1.5) else 4


def tiles_in_image(path) -> int:
    """이미 만들어진 격자 이미지가 **실제로** 몇 칸인지 치수로 되짚는다.

    ⚠ 채널 규격(tiles_for)으로 역산하면 안 된다 — 채널 선호와 기존 재고의
      실제 모양이 어긋날 수 있다. 실측(2026-09-08): 재고 75장 중 26장이
      "band=2칸, facebook=4칸"으로 이미 만들어져 있어 tiles_for(channel) 로
      계산하면 그림에 없는 스타일을 캡션이 말하거나 있는 스타일을 빠뜨린다.
      격자가 cols=min(n,2) 라서 4칸은 세로가 더 길고 2칸은 가로가 더 길다 —
      이 비율은 그림 자체에 이미 박혀 있으므로 그걸 그대로 읽는다.
    """
    with Image.open(path) as im:
        w, h = im.size
    return 4 if h > w else 2


def _gen_one(prompt: str, model: str = None) -> bytes:
    # ⚠ 잠금은 호출 **직전**에 본다. 여기가 실제로 돈이 나가는 지점이라,
    #   위쪽 어디를 고쳐도 이 한 줄을 지나지 않고는 과금되지 않는다.
    #   엔진을 나누는 아래 분기보다도 먼저다 — 어느 엔진으로 가든 잠금은
    #   똑같이 막아야 한다(2026-08-14 운영자 지시).
    if getattr(config, "IMAGE_GEN_LOCKED", False):
        raise RuntimeError(
            "이미지 생성이 잠겨 있습니다(IMAGE_GEN_LOCKED=1). "
            "풀려면 .env 에서 IMAGE_GEN_LOCKED=0 으로 바꾸세요.")
    if getattr(config, "CARD_ENGINE", "gemini") == "sd":
        # SD 는 글자를 못 그린다. 배경·도안만 맡기고 한글은 호출부가 찍는다.
        from content import sd_backend
        img = sd_backend.gen_tile(prompt)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    # ⚠ 배경·구도를 여기서 못 박는다. 실측(2026-08-12): "clean white background"
    #   만으로는 모델이 어두운 비네트·검은 모서리를 넣는다. 그러면 _fit_tile 의
    #   잉크 탐지가 그 모서리까지 도안으로 잡아 격자에 검은 삼각형이 남는다.
    #   정사각 구도도 함께 요구한다 - 가로로 길게 나오면 칸에 넣을 때 위아래가
    #   비어 도안이 작아 보인다.
    r = client.models.generate_content(
        model=model or config.CARD_MODEL,
        contents=[prompt + (
            "\n\nNo text, no letters, no watermark. Design only."
            "\nSquare 1:1 composition, the design centered and filling the frame."
            "\nPure white #FFFFFF background. No vignette, no dark corners,"
            " no border, no frame, no shadow, no paper texture.")])
    for cand in (r.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    raise RuntimeError("이미지가 반환되지 않음")


def styles_for(profile_key: str, variant: int, tiles_n: int = None) -> list:
    """이미 만들어둔 이미지에 **무엇이 그려져 있는지**를 되살린다.

    make() 는 variant 로부터 스타일을 결정론적으로 고른다
    (styles[(variant*n+i) % len(styles)]). 그래서 파일명의 v{n} 만 알면
    생성 없이도 같은 목록을 그대로 계산할 수 있다.

    ⚠ 왜 필요한가 — 콘텐츠형 프롬프트는 '스타일: {styles}' 한 줄로 그림 내용을
      LLM 에게 알려준다. 기존 이미지를 재사용하면서 이걸 비우면, 프롬프트가
      요구하는 '구체적인 하나'를 쓸 수 없어 문구가 그림과 겉돈다.

    ⚠ make() 의 인덱스 계산식과 **반드시 같아야 한다**. 한쪽만 고치면
      그림에 없는 스타일을 문구가 말하게 된다.

    ⚠ tiles_n 을 넘기지 않을 때의 기본값은 tiles_for(channel) 로 바꾸면 안
      된다 — 여기는 channel 을 모른다(인자로 안 받는다). 호출부가 채널로
      계산해서 넘기거나, 재사용 시엔 tiles_in_image(path) 로 넘겨야 한다
      (재고와 채널 규격이 어긋날 수 있어서다 — tiles_in_image 주석 참고).
      호출부가 tiles_n 을 안 주는 상황(기존 테스트)에서는 SHOWCASE_TILES 가
      유일하게 옳은 기본값이다.
    """
    spec = SPECS.get(profile_key)
    if not spec:
        return []
    styles = spec["styles"]
    n = max(1, min(int(tiles_n or config.SHOWCASE_TILES), len(styles)))
    return [styles[(variant * n + i) % len(styles)][0] for i in range(n)]


def make(profile_key: str = None, channel: str = "facebook",
         out_path: str = None, model: str = None, variant: int = 0,
         tiles_n: int = None) -> dict:
    """결과물 격자 이미지 1장을 만든다. 반환 {path, styles}

    variant: 채널마다 다른 그림을 뽑기 위한 번호.
      같은 이미지를 여러 그룹에 올리면 발행 게이트(이미지 쿨다운)가 막고,
      막지 않더라도 플랫폼이 가장 빨리 잡는 패턴이다."""
    key = profile_key or config.PROFILE_KEY
    spec = SPECS.get(key)
    if not spec:
        raise ValueError(f"{key} 업종은 아직 콘텐츠형 소재를 지원하지 않습니다")

    size = 620                       # 각 칸 크기
    pad = 14
    tiles, names = [], []
    motifs = spec.get("motifs") or [""]
    styles = spec["styles"]
    # 칸 수 = 이미지 생성 횟수. 비용이 여기에 정비례한다.
    # ⚠ 기본값은 tiles_for(channel) 이다 — make() 는 channel 을 항상 알고
    #   있으니(인자로 받는다) 채널 규격에서 바로 칸 수를 유도할 수 있다.
    #   고정값(SHOWCASE_TILES)을 쓰면 facebook 에 정사각 4칸을 억지로 넣거나
    #   band 에 가로 2칸을 억지로 넣어 tiles_for 상단 주석의 문제가 재현된다.
    n = max(1, min(int(tiles_n or tiles_for(channel)), len(styles)))
    for i in range(n):
        # 변형마다 (기법, 소재) 조합이 겹치지 않게 건너뛴다.
        # ⚠ 스타일 수의 배수로 건너뛰면 variant 가 한 바퀴 돌 때 조합이
        #   통째로 반복된다. 5는 16과 서로소라 8개 변형까지 전부 다르다.
        # ⚠ 칸을 줄이면 한 변형이 쓰는 기법도 줄어든다. 그래서 기법도
        #   variant 에 따라 돌려, 채널마다 다른 기법 조합이 보이게 한다.
        label, prompt = styles[(variant * n + i) % len(styles)]
        subject = motifs[(variant * 5 + i) % len(motifs)]
        p = prompt.replace("{subject}", subject) if subject else prompt
        print(f"[showcase] {label} · {subject or '기본'} 생성 중...")
        img = Image.open(io.BytesIO(_gen_one(p, model))).convert("RGB")
        # 잘라내지 않고 맞춘다(_fit_tile 주석 참고 - 예전 crop 방식은 도안을
        # 잘라먹거나 여백째 축소해 격자 품질을 떨어뜨렸다).
        tiles.append(_fit_tile(img, size))
        names.append(label)

    # 칸 수에 맞춰 격자를 잡는다(2장이면 가로 2×세로 1, 4장이면 2×2).
    cols = min(len(tiles), 2)
    rows = -(-len(tiles) // cols)
    grid_w = size * cols + pad * (cols + 1)
    foot = 92
    canvas = Image.new("RGB", (grid_w, size * rows + pad * (rows + 1) + foot),
                       (255, 255, 255))
    for i, t in enumerate(tiles):
        x = pad + (i % cols) * (size + pad)
        y = pad + (i // cols) * (size + pad)
        canvas.paste(t, (x, y))

    d = ImageDraw.Draw(canvas)
    # 각 칸에 스타일 이름만 작게 (제품 문구가 아니라 '무엇인지' 설명)
    f_tag = _font(30)
    for i, nm in enumerate(names):
        x = pad + (i % cols) * (size + pad) + 12
        y = pad + (i // cols) * (size + pad) + size - 46
        d.rectangle([x - 8, y - 6, x + f_tag.getlength(nm) + 12, y + 40],
                    fill=(255, 255, 255))
        d.text((x, y), nm, font=f_tag, fill=(30, 30, 35))

    # 출처 표기 — 작게, 그러나 분명히. 숨기지 않는다.
    fy = size * rows + pad * (rows + 1)
    d.rectangle([0, fy, grid_w, canvas.height], fill=(246, 246, 248))
    site = (config.BRAND_SITE or "").strip()
    d.text((pad + 6, fy + 16),
           f"AI로 생성한 {spec['label']} 예시 · {site}",
           font=_font(30), fill=(70, 70, 78))
    dis = (config.DISCLAIMER or "").strip()
    if dis:
        d.text((pad + 6, fy + 56), dis[:70], font=_font(22), fill=(120, 120, 128))

    out = Path(out_path) if out_path else (
        config.CREATIVES_DIR / f"showcase_{key}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=94)
    print(f"[showcase] 완성: {out.name} ({canvas.width}x{canvas.height})")
    return {"path": str(out), "styles": names}
