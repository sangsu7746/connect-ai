"""
agent_editor.py
편집과장 (Editing Manager Agent)

글작가의 HTML 원고를 두 가지 형태로 가공합니다:
  1. Gemini로 최종 제목·태그·레이아웃 확정
  2. HTML → "서식 세그먼트 목록" 변환
     → 포스터가 네이버 에디터 툴바를 직접 조작하여 Bold/크기/색상을 실제로 적용
"""
import os
import sys
import re
import logging
from html.parser import HTMLParser

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── HTML 태그 → 서식 규칙 매핑 ────────────────────────────────────────────
# 각 항목: (bold, font_size, color, newline_before, newline_after)
# color는 모두 None — 글자색 없음
_TAG_FORMAT = {
    "h1": (True,  "20", None, 1, 1),
    "h2": (True,  "18", None, 1, 1),
    "h3": (True,  "16", None, 1, 1),
    "h4": (True,  "15", None, 1, 1),
    "p":  (False, "14", None, 0, 1),
    "li": (False, "14", None, 0, 1),
    "div":(False, "14", None, 0, 0),
}
# 인라인 강조 태그 — color 없음, bold만 유지
_INLINE_EMPHASIS = {
    "strong": (True,  "14", None),
    "b":      (True,  "14", None),
    "em":     (False, "14", None),
    "i":      (False, "14", None),
    "span":   None,
}

# 확산 채널 CTA 블록 (글 최하단 삽입용)
SPREAD_CTA_BLOCK = """
<hr style="border:none; height:1px; background-color:#ddd; margin:30px 0;">
<div style="background-color:#f0f8ff; border:2px solid #4169e1; padding:20px; border-radius:8px; margin:10px 0; text-align:center; font-size:19px;">
💙 이 정보가 도움이 되셨다면<br>
<strong>이웃 추가</strong>와 <strong>본문 스크랩(공유)</strong>으로<br>
주변 분들에게도 소개해 주세요!<br><br>
궁금한 점은 <strong>댓글</strong>로 남겨주시면 성심껏 답변드리겠습니다 😊
</div>
"""

def _make_image_segment(img: dict, visual_type: str = "") -> dict:
    """이미지 딕셔너리를 세그먼트 형식으로 변환합니다."""
    return {
        "text": "",
        "type": "image",
        "bold": False,
        "size": "14",
        "color": None,
        "newline_before": 1,
        "newline_after": 1,
        "path": img.get("path", ""),
        "section": img.get("section", ""),
        "description": img.get("description", img.get("keyword", "")),
        "source": img.get("source", "crawled"),
        "visual_type": visual_type or img.get("visual_type", ""),
        "visual_label": img.get("visual_label", ""),
    }


class _HtmlSegmentParser(HTMLParser):
    """
    HTML 원고를 파싱하여 서식 세그먼트 목록을 생성합니다.

    세그먼트 형식:
    {
      "text": "출력할 텍스트",
      "type": "normal" | "heading" | "emphasis" | "hr",
      "bold": True/False,
      "size": "14",          # pt 단위 문자열
      "color": "#FF4500",    # None이면 기본색
      "newline_before": 0,   # 앞에 삽입할 빈 줄 수
      "newline_after": 1,    # 뒤에 삽입할 빈 줄 수
    }
    """
    def __init__(self):
        super().__init__()
        self.segments = []

        # 현재 파싱 중인 블록 컨텍스트
        self._block_stack = []    # (tag, bold, size, color, nl_bef, nl_aft)
        self._inline_stack = []   # (tag, bold, size, color)
        self._buf = []            # 현재 텍스트 버퍼
        self._skip_tags = set()   # script/style 등 무시 태그
        self._skip_depth = 0

        # 인용구 박스 컨텍스트
        self._in_quote_box = False
        self._quote_buf    = []

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────
    def _flush(self, nl_before=0, nl_after=0, seg_type="normal"):
        """버퍼를 세그먼트로 확정."""
        text = "".join(self._buf).strip()
        self._buf = []
        if not text:
            return

        # 현재 적용 중인 서식 결정 (인라인 > 블록 > 기본)
        bold, size, color = False, "14", None
        if self._inline_stack:
            _, bold, size, color = self._inline_stack[-1]
        elif self._block_stack:
            _, bold, size, color, _, _ = self._block_stack[-1]

        self.segments.append({
            "text": text,
            "type": seg_type,
            "bold": bold,
            "size": size,
            "color": color,
            "newline_before": nl_before,
            "newline_after": nl_after,
        })

    def _parse_inline_style(self, attrs_dict: dict):
        """style 속성에서 font-weight/font-size 추출. (글자색 추출 완전 차단)"""
        style = attrs_dict.get("style", "")
        bold, size, color = False, "14", None
        for decl in style.split(";"):
            decl = decl.strip()
            if "font-weight" in decl and "bold" in decl:
                bold = True
            # 사용자 요청에 의해 color 파싱 완전히 제거
            # if "color" in decl: ...
            if "font-size" in decl:
                m = re.search(r'font-size\s*:\s*(\d+)', decl)
                if m:
                    size = m.group(1)
        return bold, size, color

    # ── HTMLParser 오버라이드 ──────────────────────────────────────────
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)

        if tag in {"script", "style"}:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        # ── hr (구분선) ────────────────────────────────────────────
        if tag == "hr":
            self._flush()
            self.segments.append({
                "text": "", "type": "hr",
                "bold": False, "size": "14", "color": None,
                "newline_before": 0, "newline_after": 0,
            })
            return

        # ── 인용구 박스 ────────────────────────────────────────────
        if tag == "blockquote":
            self._flush()
            self._in_quote_box = True
            self._quote_buf    = []
            return

        # ── 블록 태그 (h1~h4, p, li, div) ─────────────────────────
        if tag in _TAG_FORMAT:
            self._flush()
            bold, size, color, nl_b, nl_a = _TAG_FORMAT[tag]
            # style 속성이 있으면 오버라이드
            s_bold, s_size, s_color = self._parse_inline_style(attrs_dict)
            if s_bold:   bold  = s_bold
            if s_size != "14": size = s_size
            if s_color:  color = s_color
            self._block_stack.append((tag, bold, size, color, nl_b, nl_a))
            return

        # ── 인라인 강조 태그 ───────────────────────────────────────
        if tag in _INLINE_EMPHASIS:
            self._flush()
            fmt = _INLINE_EMPHASIS[tag]
            if fmt:
                bold, size, color = fmt
            else:  # span — style 분석
                bold, size, color = self._parse_inline_style(attrs_dict)
            self._inline_stack.append((tag, bold, size, color))

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in {"script", "style"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        # ── 인용구 박스 닫기 ───────────────────────────────────────
        if tag == "blockquote":
            text = "".join(self._quote_buf).strip()
            if text:
                self.segments.append({
                    "text": text, "type": "quote_box",
                    "bold": False, "size": "14", "color": None,
                    "newline_before": 1, "newline_after": 1,
                })
            self._in_quote_box = False
            self._quote_buf    = []
            return

        if tag in _TAG_FORMAT:
            # 블록 닫힐 때 버퍼 플러시
            nl_b, nl_a = 0, 1
            seg_type = "heading" if tag in {"h1","h2","h3","h4"} else "normal"
            if self._block_stack and self._block_stack[-1][0] == tag:
                _, _, _, _, nl_b, nl_a = self._block_stack[-1]
                self._block_stack.pop()
            self._flush(nl_before=nl_b, nl_after=nl_a, seg_type=seg_type)

        elif tag in _INLINE_EMPHASIS:
            # 인라인 닫힐 때 버퍼 플러시 (강조 세그먼트)
            self._flush(seg_type="emphasis")
            if self._inline_stack and self._inline_stack[-1][0] == tag:
                self._inline_stack.pop()

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_quote_box:
            self._quote_buf.append(data)
        else:
            self._buf.append(data)

    def handle_entityref(self, name):
        _entities = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}
        self._buf.append(_entities.get(name, ""))

    def handle_charref(self, name):
        try:
            ch = chr(int(name[1:], 16) if name.startswith('x') else int(name))
            self._buf.append(ch)
        except Exception:
            pass

    def result(self):
        self._flush()
        # 빈 텍스트 세그먼트 제거 (hr 제외)
        return [s for s in self.segments
                if s["type"] == "hr" or s["text"].strip()]


class AgentEditor(BaseAgent):
    """
    편집과장 (Editing Manager Agent)

    담당 업무:
    1. Gemini로 최종 제목·태그·레이아웃 확정
    2. HTML 원고 → 서식 세그먼트 목록 변환 (포스터 Rich-text 입력용)
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="편집과장", client=client, model=model, temperature=temperature)

    # ── 이미지 세그먼트 병합 ──────────────────────────────────────────────
    def _merge_images_into_segments(self, segments: list,
                                    images_data: list,
                                    visual_references: dict) -> list:
        """
        이미지대리가 기획한 section_index를 기준으로 단락에 정확히 1:1 배치합니다.

        배치 우선순위:
          1순위 — section_index 기반 정밀 매핑
                  · section_index=0 → 본문 맨 앞 (썸네일)
                  · section_index=N → N번째 헤딩 직후
          2순위 — [이미지N] 마커: ordered_pool에서 순서대로 교체
          3순위 — 섹션명(section) 텍스트 매핑 (section_index 없는 수집 이미지)
          * 매핑 대상이 없는 이미지는 삽입하지 않음 (초과 이미지 버림)
        """
        # ── STEP 1: 이미지 풀 분류 ───────────────────────────────────────
        si_map: dict       = {}   # section_index → img  (정밀 매핑용)
        name_map: dict     = {}   # section_name  → [img] (fallback)
        infographic_imgs   = []
        ordered_pool: list = []   # [이미지N] 마커 교체용 (section_index 오름차순)

        valid_imgs = [
            img for img in (images_data or [])
            if img.get("path") and os.path.exists(img["path"])
        ]
        # section_index 오름차순 정렬 (None은 뒤로)
        valid_imgs.sort(
            key=lambda x: (x.get("section_index") is None, x.get("section_index", 0))
        )

        for img in valid_imgs:
            if img.get("visual_type") == "infographic":
                infographic_imgs.append(img)
                continue

            si = img.get("section_index")
            if si is not None and si not in si_map:
                si_map[si] = img          # 동일 섹션에 첫 번째 이미지만 등록

            sec = img.get("section", "").strip()
            if sec:
                name_map.setdefault(sec, []).append(img)

            # section_index=0(썸네일)은 si_map으로 단독 처리 — ordered_pool에서 제외
            if si != 0:
                ordered_pool.append(img)

        total_available = len(ordered_pool)

        # ── STEP 2: 세그먼트 순회 및 이미지 삽입 ────────────────────────
        _marker_re  = re.compile(r'^\[이미지\d*\]\s*$')
        result: list      = []
        used_paths: set   = set()
        heading_count     = 0    # 헤딩 만날 때마다 +1 → _parse_sections의 section_index와 동기화
        marker_cursor     = [0]  # [이미지N] 마커 순서 카운터

        def _try_insert(img: dict, reason: str) -> bool:
            """중복 없이 이미지를 삽입. 성공 시 True 반환."""
            if img and img["path"] not in used_paths:
                used_paths.add(img["path"])
                result.append(_make_image_segment(img))
                logger.debug(f"[편집과장] 이미지 삽입 ({reason}): {os.path.basename(img['path'])}")
                return True
            return False

        # section_index=0 이미지 → 본문 최상단 (썸네일)
        if 0 in si_map:
            _try_insert(si_map[0], "썸네일 section_index=0")

        for seg in segments:
            seg_type = seg.get("type", "normal")
            text     = seg.get("text", "").strip()

            # ── [이미지N] 마커 → ordered_pool에서 순서대로 1:1 교체 ────
            if seg_type in ("normal", "emphasis") and _marker_re.match(text):
                idx = marker_cursor[0]
                marker_cursor[0] += 1
                if idx < len(ordered_pool):
                    img = ordered_pool[idx]
                    if not _try_insert(img, f"마커 #{idx+1} section_index={img.get('section_index')}"):
                        logger.debug(f"[편집과장] {text} — 이미 사용된 이미지, 건너뜀")
                else:
                    logger.debug(f"[편집과장] {text} — 대응 이미지 없음, 마커 제거")
                continue  # 마커 텍스트 세그먼트는 출력하지 않음

            result.append(seg)

            # ── 헤딩 → section_index 기반 정밀 삽입 ────────────────────
            if seg_type == "heading":
                heading_count += 1  # 1번째 헤딩 = section_index 1

                inserted = False
                # 1순위: section_index 정밀 매핑
                if heading_count in si_map:
                    inserted = _try_insert(
                        si_map[heading_count],
                        f"section_index={heading_count} '{text[:20]}'"
                    )
                # 2순위: 섹션명 텍스트 매핑 (section_index 없는 수집 이미지)
                if not inserted:
                    for fallback_img in name_map.get(text, []):
                        if _try_insert(fallback_img, f"섹션명 매핑 '{text[:20]}'"):
                            break

        assigned  = len(used_paths)
        discarded = total_available - assigned
        logger.info(
            f"[편집과장] 이미지 배치 완료 — "
            f"전체 {total_available}컷 중 {assigned}컷 삽입, {discarded}컷 미사용"
        )

        # ── STEP 3: 시각 참고자료 전용 섹션 추가 ────────────────────────
        visual_order = [
            ("business_model",     "비즈니스 모델 피규어"),
            ("system_architecture","시스템 아키텍처 다이어그램"),
            ("service_blueprint",  "서비스 블루프린트"),
        ]
        for key, label in visual_order:
            imgs = (visual_references or {}).get(key, [])
            valid = [img for img in imgs
                     if img.get("path") and os.path.exists(img["path"])
                     and img["path"] not in used_paths]
            if not valid:
                continue
            result.append({
                "text": label, "type": "heading",
                "bold": True, "size": "16", "color": None,
                "newline_before": 2, "newline_after": 1,
            })
            for img in valid:
                used_paths.add(img["path"])
                result.append(_make_image_segment(img, visual_type=key))

        # ── STEP 4: 인포그래픽 섹션 추가 ────────────────────────────────
        if infographic_imgs:
            result.append({
                "text": "인포그래픽", "type": "heading",
                "bold": True, "size": "16", "color": None,
                "newline_before": 2, "newline_after": 1,
            })
            for img in infographic_imgs:
                result.append(_make_image_segment(img, visual_type="infographic"))

        return result

    # ── HTML 원고 전처리 ──────────────────────────────────────────────
    def _clean_content_html(self, html: str) -> str:
        """
        HTML 파싱 전에 원고에서 편집 불필요 마커와 인라인 중복 단어를 제거합니다.

        처리 항목:
        0. <think>...</think> 추론 모델 사고 과정 잔여물 제거 (최종 안전망)
        1. [본문] 마커 제거
        2. 마크다운 코드블록 래퍼(```html ... ```) 제거
        3. [이미지N]───── 플레이스홀더 제거
        4. <strong>X</strong>X 패턴 → <strong>X</strong> (강조+동일어 연속 반복 제거)
        5. X<strong>X</strong> 패턴 → <strong>X</strong> (앞쪽 연결어 중복 제거)
        6. 연속 중복 이모지 → 1개만 유지
        """
        # 0. 추론 모델 사고 과정 잔여물 — 글작가 단계에서 걸러지지만 혹시 몰라 여기서도 재확인
        html = self.strip_think_tags(html)

        # 1. [본문] 마커
        html = re.sub(r'\[본문\]\s*', '', html)

        # 2. 마크다운 코드블록 래퍼 — 앞/중간 어디서든 등장해도 제거
        html = re.sub(r'```[a-zA-Z]*\n?', '', html)
        html = re.sub(r'\n?```', '', html)

        # 3. [이미지N] 플레이스홀더 뒤 구분선 문자만 제거 (마커 자체는 보존)
        html = re.sub(r'(\[이미지\d*\])[─━\-\s]+', r'\1 ', html)

        # 4. 강조태그 뒤 동일 단어 즉시 반복 패턴 (후방 중복)
        #    예: <strong>착각</strong>착각  →  <strong>착각</strong>
        #    예: <strong>전망</strong>전망이  →  <strong>전망</strong>이 (접미 유지)
        def _strip_trailing_repeat(m):
            tag, word, after = m.group(1), m.group(2), m.group(3)
            if after.startswith(word):
                after = after[len(word):]
            return f'<{tag}>{word}</{tag}>{after}'

        html = re.sub(
            r'<(strong|b|em|i)>([^<]{1,30})</\1>(\S{0,60})',
            _strip_trailing_repeat,
            html
        )

        # 5. 강조태그 앞 동일 단어 즉시 반복 패턴 (전방 중복)
        #    예: 그런데<strong>그런데</strong>  →  <strong>그런데</strong>
        #    예: 전망<strong>전망이</strong>    →  <strong>전망이</strong>
        def _strip_leading_repeat(m):
            before, tag, word = m.group(1), m.group(2), m.group(3)
            # before가 word로 끝나면(또는 word의 앞부분과 일치하면) 앞쪽 단어 제거
            stripped = before
            if before.endswith(word):
                stripped = before[: -len(word)]
            elif word and before.endswith(word[:-1]) and len(word) > 1:
                # 접사가 붙은 경우: 전망이 → word=전망이, before=전망 → 제거
                for length in range(len(word), 0, -1):
                    stem = word[:length]
                    if before.endswith(stem):
                        stripped = before[: -len(stem)]
                        break
            return f'{stripped}<{tag}>{word}</{tag}>'

        html = re.sub(
            r'(\S{1,30})<(strong|b|em|i)>([^<]{1,30})</\2>',
            _strip_leading_repeat,
            html
        )

        # 6. 연속 중복 이모지 제거 (같은 이모지가 2개 이상 붙어 있을 때 1개만)
        #    유니코드 이모지 범위: 대부분 \U0001F000~\U0001FFFF + 기본 기호
        html = re.sub(
            r'([\U0001F000-\U0001FFFF\u2600-\u27BF])\1+',
            r'\1',
            html
        )

        return html

    # ── 텍스트 내 즉시 반복 단어/구 제거 ────────────────────────────────
    @staticmethod
    def _deduplicate_inline(text: str) -> str:
        """
        단일 텍스트 문자열 안에서 즉시 반복되는 단어/구와 중복 이모지를 제거합니다.

        예: "무려무려"        → "무려"
            "착각착각"        → "착각"
            "분위기입니다.분위기입니다." → "분위기입니다."
            "지원금지원금"    → "지원금"
            "🔥🔥"          → "🔥"  (이모지 중복)
        2~25자 범위의 즉시 반복 패턴만 대상으로 합니다.
        """
        # 1. 연속 중복 이모지 제거
        text = re.sub(
            r'([\U0001F000-\U0001FFFF\u2600-\u27BF\u2300-\u23FF\u25A0-\u25FF\u2700-\u27BF])\1+',
            r'\1',
            text
        )
        # 2. 반복 단어/구 제거 (2~25자)
        return re.sub(r'(.{2,25})\1+', r'\1', text)

    # ── 중복 문장 / 중복 강조어 제거 ────────────────────────────────────
    def _deduplicate_segments(self, segments: list) -> list:
        """
        파싱된 세그먼트에서 중복을 제거하고 인라인 반복어를 정리합니다.

        처리 순서:
        A. 각 세그먼트 텍스트에 _deduplicate_inline() 적용 (인라인 반복어·이모지)
        A2. 이모지로 시작하는 emphasis 세그먼트 → 이모지 뒤 줄넘김(\n) 삽입
        B. emphasis 직후 normal이 같은 텍스트로 시작하면 앞부분 trim (경계 반복)
        C. 동일 텍스트 세그먼트 전체 중복 제거 (heading 텍스트도 seen_normal에 등록)
        """
        _MIN_LEN = 5
        _EMOJI_RE = re.compile(
            r'^[\U0001F000-\U0001FFFF\u2600-\u27BF\u2300-\u23FF\u25A0-\u25FF\u2700-\u27BF]'
        )

        # ── A. 인라인 반복어·이모지 중복 제거 ──────────────────────────────
        for seg in segments:
            if seg.get("type") not in ("image", "hr") and seg.get("text"):
                cleaned = self._deduplicate_inline(seg["text"].strip())
                if cleaned != seg["text"].strip():
                    logger.debug(f"[편집과장] 인라인 중복 제거: '{seg['text']}' → '{cleaned}'")
                seg["text"] = cleaned

        # ── A2. 이모지 강조 세그먼트: 이모지 뒤 줄넘김 삽입 ────────────────
        for seg in segments:
            if seg.get("type") == "emphasis" and seg.get("text"):
                t = seg["text"]
                if _EMOJI_RE.match(t) and '\n' not in t:
                    seg["text"] = re.sub(
                        r'^([\U0001F000-\U0001FFFF\u2600-\u27BF\u2300-\u23FF\u25A0-\u25FF\u2700-\u27BF]+)\s*',
                        r'\1\n', t
                    )

        # ── B. emphasis→normal 경계 반복 제거 ───────────────────────────────
        for i in range(len(segments) - 1):
            curr = segments[i]
            nxt  = segments[i + 1]
            if curr.get("type") == "emphasis" and nxt.get("type") in ("normal", "emphasis"):
                emp_text    = curr.get("text", "").strip()
                normal_text = nxt.get("text", "").strip()
                if emp_text and normal_text.startswith(emp_text):
                    nxt["text"] = normal_text[len(emp_text):].lstrip()

        # ── C. 세그먼트 단위 전체 중복 제거 ────────────────────────────────
        seen_normal   = set()
        seen_emphasis = set()
        result        = []

        for seg in segments:
            seg_type = seg.get("type", "normal")
            text     = seg.get("text", "").strip()

            if seg_type in ("image", "hr") or not text:
                result.append(seg)
                continue
            if len(text) < _MIN_LEN:
                result.append(seg)
                continue

            normalized = re.sub(r'\s+', ' ', text).lower()

            if seg_type == "heading":
                seen_normal.add(normalized)
                result.append(seg)
                continue

            if seg_type == "emphasis":
                if normalized in seen_emphasis:
                    logger.debug(f"[편집과장] 중복 강조어 제거: '{text}'")
                    continue
                seen_emphasis.add(normalized)
                result.append(seg)
                continue

            if normalized in seen_normal:
                logger.debug(f"[편집과장] 중복 문장 제거: '{text[:50]}'")
                continue
            seen_normal.add(normalized)
            result.append(seg)

        removed = len(segments) - len(result)
        if removed:
            logger.info(f"[편집과장] 중복 제거 완료 — {removed}개 세그먼트 삭제")
        return result

    # ── HTML → 서식 세그먼트 변환 ───────────────────────────────────────
    def _html_to_segments(self, html: str) -> list:
        """
        HTML 원고를 포스터가 에디터 툴바로 직접 적용 가능한
        서식 세그먼트 목록으로 변환합니다.

        Returns:
            list of dict: 각 세그먼트는 text/type/bold/size/color/
                          newline_before/newline_after 필드를 포함합니다.
        """
        parser = _HtmlSegmentParser()
        # 마크다운 코드 블록 래퍼 제거 (안전한 정규식 방식)
        cleaned = html.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned.strip())
        # [박스]...[/박스] 마커 → <blockquote> 태그 변환
        cleaned = re.sub(
            r'\[박스\](.*?)\[/박스\]',
            lambda m: "<blockquote>" + m.group(1).strip() + "</blockquote>",
            cleaned,
            flags=re.DOTALL,
        )
        parser.feed(cleaned)
        return parser.result()


    # ── 메인 실행 ────────────────────────────────────────────────────────
    def execute(self, title: str, content: str, images_data: list,
                visual_references: dict = None) -> dict:
        """
        글과 이미지를 병합하고 최종 메타데이터를 추출합니다.

        Args:
            images_data (list): 이미지대리가 반환한 이미지 목록
            visual_references (dict): 서치대리가 수집한 시각 참고자료
                {"business_model": [...], "system_architecture": [...], "service_blueprint": [...]}
        """
        import time

        # ── 강화 학습 메모리 반영 ──────────────────────────────────────────
        from agents.agent_memory import get_memory as _get_mem
        _mem  = _get_mem()
        _fs   = _mem.build_fewshot_block("편집과장", k=2)
        _adj  = _mem.get_param_adjustments("편집과장")
        _rl_prefix = "\n".join(filter(None, [_fs, _adj.get("extra_instruction", "")]))
        if _rl_prefix:
            logger.info(f"[편집과장] 강화학습 반영 — 평균 점수 {_adj.get('avg_score','N/A')}/10")
        # ──────────────────────────────────────────────────────────────────

        system_instruction = (
            (_rl_prefix + "\n\n" if _rl_prefix else "")
            + "당신은 포스팅 직전 최종 원고를 책임지는 수석 '편집과장'입니다.\n"
            "【편집과장 소명】\n"
            "① 원고 전체를 처음부터 끝까지 완전히 추론·분석하여 글의 흐름과 논리적 일관성을 파악한다.\n"
            "② 중복된 단락·문장·단어를 찾아 제거하거나 합쳐 군더더기 없는 글로 만든다.\n"
            "③ 내용이 서로 상이하거나 모순되는 부분을 찾아 논리적으로 올바른 방향으로 교정한다.\n"
            "④ 강조 단어의 중복·반복을 제거하여 강조의 가치를 지킨다.\n"
            "⑤ 글 띄움(단어·문장 간격)과 글마침 줄넘김을 정돈하여 모바일 가독성을 최대화한다.\n"
            "⑥ 각 단락의 내용을 정확히 이해한 뒤, 가장 어울리는 이미지를 그 단락에 배치한다.\n"
            "새로운 내용을 창작하거나 추가하지 않으며, 오직 원고 안에 이미 있는 내용만으로 편집한다."
        )

        # 이미지 정보 요약 (번호 + 키워드 + 설명 명시)
        img_summary_lines = []
        for i, img in enumerate(images_data, 1):
            mod_tag = "[오버레이 수정됨]" if img.get("modified") else "[원본]"
            overlay = f' / 오버레이: "{img["overlay_text"]}"' if img.get("overlay_text") else ""
            img_summary_lines.append(
                f"  {i}번 이미지 | 섹션: {img.get('section','')} | "
                f"설명: {img.get('description', img.get('keyword',''))} {mod_tag}{overlay}"
            )
        img_summary = "\n".join(img_summary_lines)

        import os

        def _load_tmpl(name: str) -> str:
            with open(os.path.join(os.path.dirname(__file__), name), "r", encoding="utf-8") as f:
                return f.read()

        # 40개 항목짜리 채점 기준표를 통째로 넣으면 그것만으로 TPM 한도(6,000)의
        # 대부분을 소진해버려서, 제목/태그/이미지매핑(기준표 불필요) → 글작가 채점(20개) →
        # 이미지대리 채점(20개) 3개의 작은 호출로 분리하고 사이사이 쿨다운을 둔다.

        # ── 호출 1: 제목 교정 + 해시태그 + 이미지-단락 매핑 (기준표 불필요) ──
        prompt_meta = _load_tmpl("editor_prompt_meta.txt").format(
            title=title,
            content_summary=content[:1200],
            total_images=len(images_data),
            img_summary=img_summary
        )
        meta_res = self.generate_content_with_cost(prompt_meta, system_instruction=system_instruction)
        meta_json = self.parse_json_from_text(meta_res["text"])

        final_title = meta_json.get("final_title", title)
        tags = meta_json.get("keywords", "")
        image_assignments = meta_json.get("image_assignments", [])

        total_usage = {"메타": meta_res.get("usage", {})}
        time.sleep(20)

        # ── 호출 2: 글작가 채점 (20개 기준) ──
        prompt_score_writer = _load_tmpl("editor_prompt_score_writer.txt").format(
            title=title,
            content_summary=content[:2000],
        )
        writer_res = self.generate_content_with_cost(prompt_score_writer)
        writer_json = self.parse_json_from_text(writer_res["text"])
        writer_score = int(writer_json.get("writer_score", 100))
        writer_feedback = writer_json.get("writer_feedback", "우수함")
        total_usage["글작가_채점"] = writer_res.get("usage", {})
        time.sleep(20)

        # ── 호출 3: 이미지대리 채점 (20개 기준) ──
        prompt_score_image = _load_tmpl("editor_prompt_score_image.txt").format(
            total_images=len(images_data),
            img_summary=img_summary,
        )
        image_res = self.generate_content_with_cost(prompt_score_image)
        image_json = self.parse_json_from_text(image_res["text"])
        image_score = int(image_json.get("image_score", 100))
        image_feedback = image_json.get("image_feedback", "우수함")
        total_usage["이미지대리_채점"] = image_res.get("usage", {})

        if image_assignments:
            logger.info("[편집과장] 이미지-단락 매핑 결과:")
            for a in image_assignments:
                logger.info(
                    f"  {a.get('image_num')}번 이미지 → [{a.get('section_title')}] ({a.get('reason','')})"
                )

        logger.info(f"[편집과장] 📊 품질 채점 결과 — 글작가: {writer_score}점 | 이미지대리: {image_score}점")

        # 앞선 채점 호출과 아래 AI 교정 호출이 연달아 나가면 분당 누적 토큰(TPM) 한도를
        # 초과할 수 있어 쿨다운을 둔다 (agent_writer.py와 동일 컨벤션).
        time.sleep(20)

        # ── AI 교정 패스: 강조·글 띄움·글마침 줄넘김·이미지 마커 재배치 ──
        logger.info("[편집과장] AI 교정 패스 시작 (강조·줄넘김·이미지 배치)...")
        refined_content = self._refine_html_with_ai(content, images_data, image_assignments)

        # 확산 채널 CTA 삽입
        refined_content += f"\n{SPREAD_CTA_BLOCK}\n"

        # ── HTML → 서식 세그먼트 변환 + 중복 제거 + 이미지 삽입 ──────────
        cleaned_content = self._clean_content_html(refined_content)
        segments = self._html_to_segments(cleaned_content)
        segments = self._deduplicate_segments(segments)
        segments = self._merge_images_into_segments(segments, images_data, visual_references)

        image_paths = [
            seg["path"] for seg in segments
            if seg.get("type") == "image" and seg.get("path") and os.path.exists(seg["path"])
        ]

        return {
            "status": "success",
            "final_title": final_title,
            "final_content": refined_content,
            "segments": segments,
            "tags": tags,
            "image_paths": image_paths,
            "image_assignments": image_assignments,
            "writer_score": writer_score,
            "writer_feedback": writer_feedback,
            "image_score": image_score,
            "image_feedback": image_feedback,
            "usage": total_usage
        }

    # ── AI 교정 패스 ─────────────────────────────────────────────────────
    def _refine_html_with_ai(self, content: str, images_data: list,
                             image_assignments: list = None) -> str:
        """
        원본 HTML을 최종 교정합니다.

        교정 4대 원칙:
        1. 강조 단어 반복 제거 — 같은 단어는 섹션당 1회만 bold
        2. 글 띄움 — 단어/문장/단락 간격을 <br>로 정돈
        3. 글마침 줄넘김 — 단락 끝 문장 뒤 <br><br> 보장
        4. 이미지 마커 재배치 — image_assignments 지시에 따라 최적 단락 직후로 이동
        """
        img_descriptions = "\n".join(
            f"  {i+1}번 이미지 | 섹션:{img.get('section','?')} | "
            f"설명:{img.get('description', img.get('keyword',''))}"
            + (f" | 오버레이:\"{img['overlay_text']}\"" if img.get('overlay_text') else "")
            for i, img in enumerate(images_data)
        )

        # image_assignments → 마커 재배치 지시 문자열
        if image_assignments:
            assign_lines = "\n".join(
                f"  [이미지{a.get('image_num')}] → 단락 제목: \"{a.get('section_title')}\" 바로 뒤에 배치"
                for a in image_assignments
            )
            marker_guide = f"【이미지 마커 재배치 지시 (편집과장 분석 결과)】\n{assign_lines}"
        else:
            marker_guide = "【이미지 마커】 원본 위치를 유지하되, 단락 내용과 더 잘 맞는 위치가 있으면 이동 가능"

        # Qwen3(6,000 TPM) 한도 — 이 프롬프트는 원고 원문 + 교정본을 프롬프트·완성
        # 양쪽에 모두 들고 있어야 하는 데다 고정 지시문(규칙+이미지목록)만 약 1,600자라
        # 실측 결과 4000자도 위험했음 — 3000자로 축소해 여유를 확보.
        # HTML 태그 중간 절단 방지: 마지막 '>' 위치에서 자름
        if len(content) <= 3000:
            content_for_refine = content
        else:
            truncated = content[:3000]
            last_tag_end = truncated.rfind('>')
            if last_tag_end > 0:
                truncated = truncated[:last_tag_end + 1]
            content_for_refine = truncated + "\n...(이하 생략)"

        refine_prompt = f"""당신은 네이버 블로그 포스팅 직전 최종 원고를 책임지는 수석 편집과장입니다.
원고 전체를 처음부터 끝까지 완전히 읽은 뒤, 아래 3대 원칙만 적용하여 HTML을 교정하세요.
글작가의 문체·개성·표현은 최대한 보존하고, 사실 정확성과 중복 제거에만 집중합니다.

[원본 HTML 원고 — 전체 분석 대상]
{content_for_refine}

[이미지 목록]
{img_descriptions if img_descriptions else '이미지 없음'}

{marker_guide}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【1. 중복 단락·문장 제거】
- 동일하거나 매우 유사한 내용이 다른 단락에 반복되면 뒤쪽 중복 부분을 삭제한다
  예: A 단락에서 "DSR 40% 규제"를 설명했는데 B 단락에서 동일 설명이 반복 → B 단락 해당 문장 삭제
- 섹션 전환 시 "위에서 살펴본 것처럼", "앞서 언급했듯이" 류의 반복 접속 표현 삭제
- 단, 원고의 분량이 줄어드는 것이 우려된다면 삭제하지 말고 유의어로 대체

【2. 내용 모순·사실 불일치 교정】
- 원고 내에서 서로 모순되거나 논리적으로 맞지 않는 내용을 찾아 교정한다
  예: 앞에서 "금리 3.5%"라 했다가 뒤에서 "금리 4.2%"라 하면 → 더 구체적·신뢰할 수 있는 수치로 통일
  예: 앞에서 "2025년부터 시행"이라 했다가 뒤에서 "2024년부터 적용"이라 하면 → 일관된 연도로 교정
- 사실 관계가 불분명하면 더 범위가 넓은 표현으로 통일
- 새 내용을 창작하거나 추가하지 말 것

【3. 이미지 마커 배치 — 최우선 규칙】
- 위 [이미지 마커 재배치 지시]에 명시된 단락의 H2/H3 닫힘 태그 직후에 해당 마커 삽입
- 원본에 존재하는 [이미지1], [이미지2] 등 모든 마커를 단 하나도 누락하지 말 것
- 마커 개수는 원본과 동일하게 유지 (줄이거나 추가 금지)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【편집 가능】  중복 내용 삭제, 모순 수정, 유의어 대체, 반복 접속 표현 제거
【절대 금지】  글작가의 문체·표현 변경 / 새 내용·문장 추가 / <br> 강제 삽입 / color CSS 추가 / [이미지N] 마커 삭제·누락

교정된 HTML만 출력하세요. ```html 래퍼 없이 태그만 작성합니다."""

        refine_system = (
            "당신은 네이버 블로그 포스팅 전 최종 교정을 담당하는 수석 편집과장입니다.\n"
            "① 중복 단락·문장 제거 ② 사실 모순 교정 ③ 이미지 마커 배치만 수행합니다.\n"
            "글작가의 문체·개성을 절대 훼손하지 않으며, 원고 안에 있는 내용만으로 편집하고 HTML 코드만 출력합니다."
        )
        try:
            res = self.generate_content_with_cost(refine_prompt, system_instruction=refine_system)
            refined = res["text"].strip()
            refined = re.sub(r"^```[a-zA-Z]*\n?", "", refined)
            refined = re.sub(r"\n?```$", "", refined.strip())
            if len(refined) < len(content_for_refine) * 0.4:
                logger.warning("[편집과장] AI 교정 결과 너무 짧음 — 원본 사용")
                return content
            logger.info(f"[편집과장] AI 교정 완료 — 원본 {len(content)}자 → 교정 {len(refined)}자")

            # ── 마커 유실 자동 복구 ────────────────────────────────────
            refined = self._recover_missing_markers(content, refined)

            return refined
        except Exception as e:
            logger.error(f"[편집과장] AI 교정 실패: {e} — 원본 사용")
            return content

    @staticmethod
    def _recover_missing_markers(original: str, refined: str) -> str:
        """
        AI 교정 후 [이미지N] 마커가 소실된 경우 원본 위치를 참조해 자동 복구합니다.

        복구 전략:
        1. 원본에서 마커 목록 추출 (순서 유지)
        2. 교정본에서 누락된 마커만 식별
        3. 누락 마커를 가장 가까운 H2/H3 섹션 직후에 재삽입
           (매핑 불가 시 교정본 맨 끝에 추가)
        """
        _marker_re = re.compile(r'\[이미지\d+\]')

        original_markers = _marker_re.findall(original)
        refined_markers  = set(_marker_re.findall(refined))

        missing = [m for m in original_markers if m not in refined_markers]
        if not missing:
            return refined  # 누락 없음 — 그대로 반환

        logger.warning(f"[편집과장] 마커 유실 감지: {missing} — 자동 복구 시작")

        # H2/H3 태그 뒤에 순서대로 삽입
        _heading_re = re.compile(r'(</h[23]>)', re.IGNORECASE)
        headings = list(_heading_re.finditer(refined))

        result = refined
        offset = 0  # 삽입으로 인한 인덱스 이동량 누적
        for i, marker in enumerate(missing):
            if i < len(headings):
                m = headings[i]
                insert_pos = m.end() + offset
                insert_str = f"\n{marker}\n"
                result = result[:insert_pos] + insert_str + result[insert_pos:]
                offset += len(insert_str)
                logger.info(f"[편집과장] 마커 복구: {marker} → H2/H3 #{i+1} 직후 삽입")
            else:
                result = result + f"\n{marker}\n"
                logger.info(f"[편집과장] 마커 복구: {marker} → 본문 끝에 추가")

        return result
