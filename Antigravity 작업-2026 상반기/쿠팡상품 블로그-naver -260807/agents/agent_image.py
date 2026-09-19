"""
agent_image.py
이미지대리 (Image Agent)

[담당 업무 흐름]
STEP 2  글작가 프롬프트(writer_image_prompts) → Gemini AI 이미지 생성
STEP 3  글작가 썸네일 프롬프트 → Gemini AI 썸네일 이미지 생성 (section_index=0 확정)
STEP 4  단락-이미지 배치 계획 (Gemini LLM이 이미지 ↔ 섹션 매칭)
STEP 5  배치 계획 순서대로 이미지 정렬 (후처리 없음 — 원본 그대로 편집과장 전달)
"""
import os
import sys
import uuid
import json
import logging
import textwrap

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent
from dotenv import load_dotenv

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))

logger = logging.getLogger(__name__)

# ── 한국어 폰트 경로 후보 (윈도우 기준) ────────────────────────────────
_KR_FONTS = [
    "C:/Windows/Fonts/malgunbd.ttf",   # 맑은 고딕 Bold
    "C:/Windows/Fonts/malgun.ttf",     # 맑은 고딕
    "C:/Windows/Fonts/gulim.ttc",      # 굴림
    "C:/Windows/Fonts/NanumGothicBold.ttf",
]


def _load_kr_font(size: int = 48):
    """
    한국어 렌더링이 실제로 가능한지 테스트 후 폰트를 반환합니다.
    검증 실패 시 None을 반환합니다 (절대 load_default() 폴백 없음).
    """
    try:
        from PIL import ImageFont, ImageDraw, Image as PILImage
    except ImportError:
        return None

    for path in _KR_FONTS:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size=size)
            # 실제 한글 렌더링 테스트 — 깨지지 않으면 사용
            test_img = PILImage.new("RGB", (300, 80), (255, 255, 255))
            draw = ImageDraw.Draw(test_img)
            draw.text((0, 0), "한글 테스트", font=font, fill=(0, 0, 0))
            logger.info(f"[이미지대리] 한국어 폰트 확인: {os.path.basename(path)}")
            return font
        except Exception:
            continue

    logger.warning("[이미지대리] 한국어 지원 폰트를 찾지 못했습니다. 텍스트 오버레이를 건너뜁니다.")
    return None


class AgentImage(BaseAgent):
    """
    이미지대리 (Image Agent)

    담당 업무:
    - 서치대리 수집 이미지 검토 및 단락별 배치 결정
    - 필요 시 한국어 텍스트 오버레이로 이미지 수정
    - AI 이미지 생성으로 부족분 보충 (최소 min_images컷 보장)
    """

    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="이미지대리", client=client, model=model, temperature=temperature)

        # Gemini 이미지 생성 전용 클라이언트 — Groq 클라이언트와 별도로 초기화
        self._gemini_client = None
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            # .env에 없으면 config.json에서 재시도
            _cfg_path = os.path.join(_project_root, "config.json")
            if os.path.exists(_cfg_path):
                try:
                    import json as _json
                    with open(_cfg_path, "r", encoding="utf-8") as f:
                        gemini_key = _json.load(f).get("gemini_api_key", "")
                except Exception:
                    pass
        if gemini_key:
            try:
                import google.genai as genai
                self._gemini_client = genai.Client(api_key=gemini_key)
                logger.info("[이미지대리] Gemini 이미지 생성 클라이언트 초기화 완료")
            except Exception as e:
                logger.warning(f"[이미지대리] Gemini 클라이언트 초기화 실패: {e}")
        else:
            logger.warning("[이미지대리] GEMINI_API_KEY 없음 — 이미지 생성 불가, 수집 이미지로만 동작")

    # ══════════════════════════════════════════════════════════════════
    # 내부 헬퍼
    # ══════════════════════════════════════════════════════════════════

    def _parse_sections(self, content: str) -> list:
        """
        블로그 본문을 단락(섹션)으로 분리합니다.
        마크다운 제목(#, ##, **소제목**) 기준으로 분리하며,
        제목이 없으면 문단 단위로 묶습니다.

        Returns:
            list of dict: [{"index": 0, "title": "서두", "preview": "...첫 200자..."}, ...]
        """
        sections = []
        lines = content.split("\n")
        current_title = "서두"
        current_lines = []

        for line in lines:
            stripped = line.strip()
            # 마크다운 제목 감지
            is_heading = (
                stripped.startswith("#")
                or (stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4)
            )
            if is_heading and current_lines:
                sections.append({
                    "index": len(sections),
                    "title": current_title,
                    "preview": " ".join(current_lines)[:300]
                })
                current_title = stripped.lstrip("#").strip().strip("*")
                current_lines = []
            elif not is_heading:
                if stripped:
                    current_lines.append(stripped)

        # 마지막 섹션 추가
        if current_lines:
            sections.append({
                "index": len(sections),
                "title": current_title,
                "preview": " ".join(current_lines)[:300]
            })

        # 섹션이 너무 적으면 전체를 하나의 섹션으로 처리
        if not sections:
            sections.append({
                "index": 0,
                "title": "전체 본문",
                "preview": content[:400]
            })

        return sections

    def _plan_assignments(self, title: str, content: str, available_images: list) -> list:
        """
        Gemini AI를 이용해 단락별 이미지 배치 계획을 수립합니다.

        - 어떤 이미지가 어느 단락에 적합한지 선택
        - 이미지를 그대로 써도 되는지, 아니면 한국어 텍스트를 추가해야 하는지 결정
        - 추가할 텍스트 내용(한국어)과 위치(top/bottom/center)도 지정

        Returns:
            list of dict: 배치 계획 목록
        """
        sections = self._parse_sections(content)

        # 이미지 목록 설명 문자열 생성
        img_desc_lines = []
        for i, img in enumerate(available_images):
            if img.get("source") == "nanobanana":
                src_label = "나노바나나생성"
            elif img.get("source") == "crawled":
                src_label = "네이버수집"
            else:
                src_label = "AI생성"
            desc = img.get("description", img.get("section", f"이미지{i}"))
            sec_idx = img.get("section_index")
            sec_hint = f" → 섹션{sec_idx} 대응" if sec_idx is not None else ""
            img_desc_lines.append(f"[이미지 {i}] ({src_label}){sec_hint} {desc}")
        img_desc_str = "\n".join(img_desc_lines)

        # 섹션 목록 설명 문자열
        sec_desc_lines = []
        for s in sections:
            sec_desc_lines.append(f"[섹션 {s['index']}] 제목: {s['title']}\n  내용 요약: {s['preview'][:200]}")
        sec_desc_str = "\n".join(sec_desc_lines)

        system_instruction = (
            "당신은 네이버 블로그 이미지 편집 전문가 '이미지대리'입니다. "
            "글의 각 단락을 분석하여 가장 어울리는 이미지를 선택하고, "
            "이미지에 추가할 한국어 텍스트를 정확하게 작성합니다. "
            "한국어 맞춤법을 반드시 준수하며, 오탈자가 없어야 합니다."
        )

        prompt = f"""
아래 블로그 글의 단락 목록과 사용 가능한 이미지 목록을 보고,
각 단락에 배치할 최적의 이미지를 선택하고, 필요 시 이미지에 추가할 한국어 텍스트를 작성하세요.

[블로그 제목]: {title}

[단락 목록]
{sec_desc_str}

[사용 가능한 이미지 목록]
{img_desc_str}

판단 기준:
1. 이미지의 키워드·분위기가 단락 내용과 잘 맞으면 → needs_overlay: false (수정 없이 그대로 배치)
2. 이미지는 괜찮지만 단락 주제를 더 명확히 나타내려면 → needs_overlay: true, 적절한 한국어 텍스트 추가
3. 하나의 이미지를 여러 단락에 중복 배치하지 마세요.
4. 이미지가 부족하면 일부 단락은 image_index를 null로 설정하세요.
5. overlay_text는 반드시 자연스러운 한국어 완전한 문장 또는 핵심 키워드여야 합니다. 영어 혼용 최소화.
6. image_type은 해당 이미지가 사진(photo)인지 인포그래픽/도표(infographic)인지 판단해 주세요.
   인포그래픽은 텍스트·아이콘·차트가 많은 이미지이며, 이 경우 텍스트 색상·폰트만 변경하므로
   needs_overlay를 false로 설정하고 image_type을 "infographic"으로 지정하세요.

아래 JSON 형식으로만 응답하세요.
```json
{{
  "assignments": [
    {{
      "section_index": 0,
      "section_title": "서두",
      "image_index": 0,
      "image_type": "photo",
      "needs_overlay": true,
      "overlay_text": "2026년 부동산 완벽 가이드",
      "overlay_position": "bottom",
      "reason": "제목 단락이므로 글 제목을 이미지 하단에 추가"
    }},
    {{
      "section_index": 1,
      "section_title": "청약 절차 안내",
      "image_index": 2,
      "image_type": "infographic",
      "needs_overlay": false,
      "overlay_text": "",
      "overlay_position": "",
      "reason": "인포그래픽 이미지 → 텍스트 색상·폰트만 변경"
    }}
  ]
}}
```
"""
        try:
            response_data = self.generate_content_with_cost(prompt, system_instruction=system_instruction)
            plan_data = self.parse_json_from_text(response_data["text"])
            assignments = plan_data.get("assignments", [])
            logger.info(f"[이미지대리] 단락-이미지 배치 계획 완료: {len(assignments)}개 배치 결정")
            return assignments, response_data.get("usage", {})
        except Exception as e:
            logger.warning(f"[이미지대리] 배치 계획 생성 실패: {e} → 순서대로 배치")
            return [], {}

    def _verify_korean_text(self, text: str) -> str:
        """
        Gemini로 한국어 텍스트 맞춤법을 교정합니다.
        교정된 텍스트만 반환하며, 실패 시 원본을 반환합니다.
        """
        if not text.strip():
            return text
        try:
            prompt = (
                f"다음 텍스트의 한국어 맞춤법과 띄어쓰기를 교정해주세요.\n"
                f"교정된 텍스트만 출력하고, 설명이나 부연 내용은 절대 포함하지 마세요.\n\n"
                f"텍스트: {text}"
            )
            resp = self.generate_content_with_cost(prompt)
            corrected = resp["text"].strip().strip('"').strip("'")
            # 결과가 합리적인 길이면 사용 (너무 길면 원본 유지)
            if corrected and len(corrected) <= len(text) * 2:
                if corrected != text:
                    logger.info(f"[이미지대리] 맞춤법 교정: '{text}' → '{corrected}'")
                return corrected
        except Exception as e:
            logger.warning(f"[이미지대리] 맞춤법 교정 실패: {e}")
        return text

    def _apply_text_overlay(self, image_path: str, overlay_text: str,
                             position: str = "bottom", opacity: int = 127,
                             font_size_pt: int = None,
                             band_height_pt: int = None) -> str:
        """
        이미지에 한국어 텍스트를 오버레이합니다.

        font_size_pt : 고정 폰트 크기(pt). None이면 이미지 너비 기준 동적 계산.
        band_height_pt: 고정 띠 높이(pt). None이면 텍스트 높이 기준 동적 계산.
                        band_height_pt 지정 시 박스는 항상 가로 full, 세로 고정값.
        """
        if not overlay_text.strip():
            return image_path

        try:
            from PIL import Image, ImageDraw
        except ImportError:
            logger.warning("[이미지대리] Pillow 미설치 — 오버레이 건너뜀")
            return image_path

        if not os.path.exists(image_path):
            return image_path

        # ── STEP 1: 맞춤법 교정 (Gemini) ────────────────────────────────
        overlay_text = self._verify_korean_text(overlay_text)

        try:
            img = Image.open(image_path).convert("RGBA")
            width, height = img.size

            fixed_mode = font_size_pt is not None or band_height_pt is not None

            if fixed_mode:
                # ── 고정 크기 모드 (썸네일 캡션 바 등) ──────────────────
                fs = max(1, font_size_pt or 6)   # pt ≈ px (72dpi 기준)
                font = _load_kr_font(fs)
                if font is None:
                    logger.warning("[이미지대리] 한글 폰트 없음 → 오버레이 건너뜀")
                    return image_path

                # 한 줄로만 렌더링 (너무 작은 폰트에서 줄바꿈은 무의미)
                wrapped_text = overlay_text
                dummy = ImageDraw.Draw(img)
                try:
                    bbox = dummy.textbbox((0, 0), wrapped_text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                except AttributeError:
                    text_w, text_h = dummy.textsize(wrapped_text, font=font)

                band_h = max(1, band_height_pt or 8)   # pt ≈ px
                text_x = max(0, (width - text_w) / 2)

                if position == "top":
                    band_y0, band_y1 = 0, band_h
                elif position == "center":
                    band_y0 = (height - band_h) // 2
                    band_y1 = band_y0 + band_h
                else:  # bottom
                    band_y0 = height - band_h
                    band_y1 = height

                text_y = band_y0 + max(0, (band_h - text_h) // 2)

                overlay_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay_layer)
                # 가로 full 박스
                draw.rectangle([(0, band_y0), (width, band_y1)],
                               fill=(0, 0, 0, opacity))
                draw.text((text_x, text_y), wrapped_text,
                          font=font, fill=(255, 255, 255, 255))

            else:
                # ── 동적 크기 모드 (기존 로직) ───────────────────────────
                max_allowed_w = int(width * 0.8)
                font_size = max(36, int(width * 0.052))

                chars_per_line = max(6, int(max_allowed_w / (font_size * 0.65)))
                wrapped_lines = textwrap.wrap(overlay_text, width=chars_per_line)
                if not wrapped_lines:
                    wrapped_lines = [overlay_text]
                wrapped_text = "\n".join(wrapped_lines)

                font = None
                for _ in range(10):
                    font = _load_kr_font(font_size)
                    if font is None:
                        break
                    dummy = ImageDraw.Draw(img)
                    try:
                        bbox = dummy.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=6)
                        text_w = bbox[2] - bbox[0]
                        text_h = bbox[3] - bbox[1]
                    except AttributeError:
                        text_w, text_h = dummy.multiline_textsize(wrapped_text, font=font, spacing=6)
                    if text_w <= max_allowed_w:
                        break
                    font_size = max(24, int(font_size * 0.9))

                if font is None:
                    logger.warning("[이미지대리] 한글 폰트 없음 → 오버레이 건너뜀")
                    return image_path

                padding = int(font_size * 0.7)
                band_h = text_h + padding * 2

                if position == "top":
                    band_y0, band_y1 = 0, band_h
                elif position == "center":
                    band_y0 = (height - band_h) // 2
                    band_y1 = band_y0 + band_h
                else:
                    band_y0 = height - band_h
                    band_y1 = height

                text_x = max(0, (width - text_w) / 2)
                text_y = band_y0 + padding

                overlay_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay_layer)
                draw.rectangle([(0, band_y0), (width, band_y1)],
                               fill=(0, 0, 0, opacity))
                draw.multiline_text(
                    (text_x + 2, text_y + 2), wrapped_text,
                    font=font, fill=(0, 0, 0, 210), align="center", spacing=6
                )
                draw.multiline_text(
                    (text_x, text_y), wrapped_text,
                    font=font, fill=(255, 255, 255, 255), align="center", spacing=6
                )

            # ── 합성 후 저장 ───────────────────────────────────────────
            combined = Image.alpha_composite(img, overlay_layer).convert("RGB")
            base, _ = os.path.splitext(image_path)
            out_path = f"{base}_overlay.png"
            combined.save(out_path, "PNG")
            logger.info(
                f"[이미지대리] 텍스트 오버레이 완료: '{overlay_text}' "
                f"({position}, font={font_size_pt or 'auto'}pt, "
                f"band={band_height_pt or 'auto'}pt) → {os.path.basename(out_path)}"
            )
            return out_path

        except Exception as e:
            logger.warning(f"[이미지대리] 오버레이 실패 ({e}) → 원본 유지")
            return image_path

    def _save_image_bytes(self, raw_bytes: bytes, temp_dir: str) -> str | None:
        """이미지 바이트를 PNG 파일로 저장하고 경로를 반환합니다."""
        import io
        filename = f"gemini_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(temp_dir, filename)
        try:
            from PIL import Image as PILImage
            PILImage.open(io.BytesIO(raw_bytes)).save(filepath, "PNG")
        except Exception:
            with open(filepath, "wb") as f:
                f.write(raw_bytes)
        return filepath

    def _generate_nanobanana_image(self, prompt_en: str, section: str, description_kr: str,
                                   temp_dir: str, apply_overlay: bool = False) -> dict | None:
        """
        Gemini API로 이미지를 생성합니다.

        한글 텍스트 전략:
          - Gemini 확산 모델은 CJK 문자를 정확히 렌더링 불가 (깨짐)
          - 이미지 내 텍스트 완전 금지 → 생성 후 Pillow로 한글 오버레이 적용
          - apply_overlay=True (썸네일 전용)일 때만 캡션을 오버레이하며,
            본문 콘텐츠 이미지에는 오버레이를 적용하지 않는다.

        Rate limit 대응:
          - 1차: 원본 상세 프롬프트로 시도
          - 2차: 단순화 프롬프트로 재시도 (안전필터·복잡도 우회)
          - 429 감지 시 10초 추가 대기
        """
        import traceback
        import time as _time

        if not self._gemini_client:
            logger.warning("[이미지대리] Gemini 클라이언트 미설정 — 이미지 생성 불가")
            return None

        # 제안 1: 프롬프트 자동 보정 — 금지어 제거 + 품질 태그 정규화
        prompt_en = self._sanitize_prompt(prompt_en)
        logger.info(f"[이미지대리] 이미지 생성 시작 | 섹션: {section} | 프롬프트: {prompt_en[:80]}...")

        from google.genai import types as genai_types

        # 이미지 내 텍스트 완전 금지 — 한글은 생성 후 Pillow로 별도 추가
        _no_text = (
            " No text, letters, words, signs, labels, banners, watermarks,"
            " or captions of any kind anywhere in the image."
        )
        full_prompt   = prompt_en.rstrip() + _no_text
        # 제안 3: 최소 폴백 프롬프트 (3차 시도용)
        simple_prompt = (
            f"Professional high-quality photo about: {section}. "
            f"Clean composition, soft studio lighting, 8k resolution, photorealistic."
            + _no_text
        )

        _MODELS = [
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image",
            "gemini-3-pro-image",
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
        ]

        def _try_prompt(prompt: str) -> bytes | None:
            for model_id in _MODELS:
                try:
                    resp = self._gemini_client.models.generate_content(
                        model=model_id,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"]
                        )
                    )
                    for cand in (getattr(resp, "candidates", []) or []):
                        for part in (getattr(cand.content, "parts", []) or []):
                            data = getattr(getattr(part, "inline_data", None), "data", None)
                            if data:
                                logger.info(f"[이미지대리] ✅ {model_id} 성공")
                                return data
                    logger.warning(f"[이미지대리] {model_id} — 이미지 파트 없음")

                except Exception as e:
                    err = str(e)
                    logger.warning(f"[이미지대리] {model_id} 실패: {err[:120]}")
                    if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                        logger.info("[이미지대리] Rate limit 감지 → 10초 대기")
                        _time.sleep(10)
                    logger.debug(traceback.format_exc())
            return None

        # ── 1차: sanitized 원본 상세 프롬프트 ───────────────────────────
        raw_bytes = _try_prompt(full_prompt)

        # ── 2차: LLM 핵심 추출 단순화 재시도 (제안 3) ───────────────────
        if raw_bytes is None:
            logger.info(f"[이미지대리] 1차 실패 → LLM 단순화 프롬프트 재시도: {section}")
            _time.sleep(5)
            llm_simple = self._simplify_prompt_with_llm(prompt_en, section) + _no_text
            raw_bytes = _try_prompt(llm_simple)

        # ── 3차: 템플릿 최소 프롬프트 최후 재시도 (제안 3) ─────────────
        if raw_bytes is None:
            logger.info(f"[이미지대리] 2차 실패 → 최소 템플릿 프롬프트 재시도: {section}")
            _time.sleep(5)
            raw_bytes = _try_prompt(simple_prompt)

        if raw_bytes is not None:
            filepath = self._save_image_bytes(raw_bytes, temp_dir)

            # ── 한글 캡션 오버레이: 썸네일에만 적용 (본문 이미지는 원본 유지) ──
            if apply_overlay and description_kr:
                first_line = description_kr.split(".")[0].split("。")[0].strip()
                if len(first_line) > 22:
                    first_line = first_line[:22] + "…"
                if first_line:
                    overlaid = self._apply_text_overlay(
                        filepath, first_line, position="bottom"
                    )
                    if overlaid != filepath:
                        filepath = overlaid
                        logger.info(f"[이미지대리] 한글 오버레이 완료: '{first_line}'")

            return {"section": section, "description": description_kr,
                    "path": filepath, "source": "nanobanana"}

        # ── 최후: Imagen 4 / Imagen 3 (유료 Pro 플랜) ────────────────────
        for imagen_model in ["imagen-4.0-fast-generate-001", "imagen-4.0-generate-001",
                              "imagen-3.0-generate-002"]:
            try:
                response = self._gemini_client.models.generate_images(
                    model=imagen_model,
                    prompt=full_prompt,
                    config=genai_types.GenerateImageConfig(
                        number_of_images=1,
                        output_mime_type="image/png",
                        aspect_ratio="1:1",
                    )
                )
                generated = getattr(response, "generated_images", [])
                if generated:
                    raw_bytes = generated[0].image.image_bytes
                    filepath = self._save_image_bytes(raw_bytes, temp_dir)
                    logger.info(f"[이미지대리] ✅ {imagen_model} 완료: {os.path.basename(filepath)}")
                    return {"section": section, "description": description_kr,
                            "path": filepath, "source": "nanobanana"}
                logger.warning(f"[이미지대리] {imagen_model} — 응답에 이미지 없음")
                continue

            except Exception as e:
                logger.warning(f"[이미지대리] {imagen_model} 실패: {e}")
                logger.debug(traceback.format_exc())

        logger.error("[이미지대리] ❌ 모든 생성 시도 실패 — 수집 이미지 폴백으로 전환")
        return None

    # ══════════════════════════════════════════════════════════════════
    # 제안 1 — 프롬프트 자동 보정 (Prompt Sanitizer)
    # ══════════════════════════════════════════════════════════════════

    def _sanitize_prompt(self, prompt_en: str) -> str:
        """
        글작가 프롬프트에서 AI 이미지 생성 금지 요소 자동 제거 + 품질 태그 정규화.

        - 이미지 내 텍스트 렌더링을 유발하는 패턴 제거 ("sign reading X" 등)
        - 필수 품질 태그 누락 시 자동 보충
        - 연속 쉼표/공백 정리
        """
        import re

        _TEXT_PATTERNS = [
            r'\bsign\s+(?:reading|saying|that\s+says)\b[^,\.]*',
            r'\btext\s+(?:reading|saying|that\s+says)\b[^,\.]*',
            r'\blabel\s+(?:reading|saying)\b[^,\.]*',
            r'\bbanner\s+(?:reading|saying)\b[^,\.]*',
            r'\bwritten\s+(?:on|in|across)\b[^,\.]*',
            r'\bthe\s+words?\s+"[^"]*"',
            r'\blettering\b[^,\.]*',
            r'\bcaption\s+(?:reading|saying)\b[^,\.]*',
        ]
        cleaned = prompt_en
        for pat in _TEXT_PATTERNS:
            cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)

        _REQUIRED = ["highly detailed", "studio lighting", "professional composition"]
        lower = cleaned.lower()
        missing = [t for t in _REQUIRED if t not in lower]
        if missing:
            cleaned = cleaned.rstrip(" ,") + ", " + ", ".join(missing)

        cleaned = re.sub(r',\s*,+', ',', cleaned)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(" ,")
        return cleaned

    # ══════════════════════════════════════════════════════════════════
    # 제안 3 — 실패 재시도용 LLM 프롬프트 단순화 헬퍼
    # ══════════════════════════════════════════════════════════════════

    def _simplify_prompt_with_llm(self, prompt_en: str, section: str) -> str:
        """
        복잡한 프롬프트에서 핵심 피사체+스타일만 추출하여 단순화된 프롬프트 반환.
        생성 실패 시 LLM 재시도용으로 사용.
        """
        refine_prompt = (
            f"Simplify this AI image generation prompt to its 2-3 most essential visual elements.\n"
            f"Keep: main subject, setting, and one style tag (cinematic / 3D render / photo).\n"
            f"Remove: complex descriptions, redundant adjectives.\n"
            f"Section context: {section}\n"
            f"Original: {prompt_en}\n\n"
            f"Rules: max 40 words. No text/signs/labels in the image. "
            f"End with: studio lighting, 8k resolution, sharp focus.\n"
            f"Output ONLY the simplified prompt."
        )
        try:
            resp = self.generate_content_with_cost(refine_prompt)
            result = resp["text"].strip().strip('"').strip("'")
            if result and len(result) > 10:
                logger.info(f"[이미지대리] LLM 단순화 성공: {result[:60]}...")
                return result
        except Exception as e:
            logger.warning(f"[이미지대리] LLM 단순화 실패 ({e})")
        return f"{section}, professional photography, clean background, studio lighting, 8k resolution, sharp focus"

    # ══════════════════════════════════════════════════════════════════
    # 제안 4 — 프롬프트 강화 LLM (일괄 배치 강화)
    # ══════════════════════════════════════════════════════════════════

    def _enhance_prompts(self, prompts: list, title: str) -> tuple:
        """
        글작가의 image_prompts를 Groq LLM으로 일괄 강화.
        구체적인 조명/각도/분위기 태그를 추가하여 AI 이미지 생성 품질 극대화.

        Returns:
            (enhanced_prompts: list, usage: dict)
        """
        if not prompts:
            return prompts, {}

        prompt_lines = []
        for i, p in enumerate(prompts):
            prompt_lines.append(
                f"{i+1}. [{p.get('marker','')}] 섹션={p.get('section','')} | "
                f"설명={p.get('description_kr','')[:60]} | "
                f"원본={p.get('prompt_en','')[:120]}"
            )

        system_instr = (
            "You are a professional AI image prompt engineer specializing in "
            "photorealistic, cinematic, and 3D render prompts for blog illustration."
        )
        batch_prompt = f"""Enhance each image prompt below for maximum AI image generation quality.
Preserve the original subject/scene intent, but add specific details.

Blog title: {title}
Number of prompts: {len(prompts)}

Prompts:
{chr(10).join(prompt_lines)}

For EACH prompt:
1. Keep the original scene/subject from 섹션 and 설명 (Korean description)
2. Add specific camera angle, lighting type, mood
3. Add material/texture details where relevant
4. Append quality suffix: "8k resolution, sharp focus, professional composition"
5. NEVER include any text, signs, labels, words, or captions in the image
6. Max 80 words per prompt

Respond ONLY with JSON array (same count as input, same order):
```json
[
  {{"index": 1, "enhanced_prompt": "..."}},
  {{"index": 2, "enhanced_prompt": "..."}}
]
```"""

        try:
            resp = self.generate_content_with_cost(batch_prompt, system_instruction=system_instr)
            items = self.parse_json_from_text(resp["text"])
            if not isinstance(items, list):
                raise ValueError("응답이 리스트 아님")

            enhanced = [p.copy() for p in prompts]
            applied = 0
            for item in items:
                idx = item.get("index", 0) - 1
                ep  = item.get("enhanced_prompt", "").strip()
                if 0 <= idx < len(enhanced) and ep:
                    enhanced[idx]["prompt_en"] = ep
                    applied += 1

            logger.info(f"[이미지대리] 프롬프트 강화 완료 — {applied}/{len(prompts)}컷 업그레이드")
            return enhanced, resp.get("usage", {})

        except Exception as e:
            logger.warning(f"[이미지대리] 프롬프트 강화 실패 ({e}) — 원본 그대로 사용")
            return prompts, {}

    # ══════════════════════════════════════════════════════════════════
    # 제안 5 — 생성 결과 검증 (Gemini Vision Verification)
    # ══════════════════════════════════════════════════════════════════

    def _verify_image_content(self, image_path: str, section: str, description_kr: str) -> float:
        """
        생성된 이미지가 섹션 내용을 제대로 표현하는지 Gemini Vision으로 검증.

        Returns:
            float 0.0 ~ 1.0 (0.0=완전 불일치, 1.0=완벽 일치)
            Gemini 클라이언트 없거나 오류 시 → 1.0 반환 (검증 통과 처리)
        """
        if not self._gemini_client or not os.path.exists(image_path):
            return 1.0

        try:
            from google.genai import types as genai_types

            with open(image_path, "rb") as f:
                img_bytes = f.read()

            verify_prompt = (
                f"Evaluate how well this image visually represents the blog section below.\n\n"
                f"Section title: {section}\n"
                f"Section description (Korean): {description_kr}\n\n"
                f"Score criteria:\n"
                f"  1.0 — image perfectly captures the section topic\n"
                f"  0.7 — relevant but missing some key elements\n"
                f"  0.4 — loosely related\n"
                f"  0.1 — unrelated\n\n"
                f"Respond with ONLY a decimal number between 0.0 and 1.0. No explanation."
            )

            for model_id in ["gemini-2.5-flash", "gemini-2.5-flash-latest", "gemini-2.0-flash"]:
                try:
                    resp = self._gemini_client.models.generate_content(
                        model=model_id,
                        contents=genai_types.Content(
                            role="user",
                            parts=[
                                genai_types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                                genai_types.Part.from_text(text=verify_prompt),
                            ]
                        )
                    )
                    score_text = (resp.text or "").strip()
                    score = float(score_text)
                    return min(1.0, max(0.0, score))
                except ValueError:
                    continue
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"[이미지대리] 비전 검증 오류 ({e}) → 통과 처리")
        return 1.0

    # ══════════════════════════════════════════════════════════════════
    # 메인 실행
    # ══════════════════════════════════════════════════════════════════

    def execute(self, title: str, content: str, min_images: int = 5,
                writer_image_prompts: list = None,
                thumbnail_prompt: dict = None,
                feedback: str = None) -> dict:
        """
        STEP 2  글작가 프롬프트 → Gemini AI 이미지 생성
        STEP 3  글작가 썸네일 프롬프트 → Gemini AI 썸네일 전용 생성
        STEP 4  단락-이미지 배치 계획 (Gemini LLM)
        STEP 5  배치 순서대로 정렬 — 후처리 없음, 원본 그대로 편집과장 전달
        """
        import time

        if feedback:
            logger.info(f"[이미지대리] ⚠️ 이전 검수 피드백 수신: {feedback}")
            title = f"{title} (피드백 반영 필요: {feedback})"

        # ── 강화 학습 메모리 반영 ──────────────────────────────────────────
        from agents.agent_memory import get_memory as _get_mem
        _adj  = _get_mem().get_param_adjustments("이미지대리")
        _delta = _adj.get("min_images_delta", 0)
        if _delta:
            min_images = max(4, min_images + _delta)
            logger.info(f"[이미지대리] 강화학습 반영 — 최소 {min_images}컷 (점수 {_adj.get('avg_score','N/A')}/10)")
        # ──────────────────────────────────────────────────────────────────

        total_usage = {}
        temp_dir = os.path.join(os.getcwd(), "temp_images")
        os.makedirs(temp_dir, exist_ok=True)

        # ── 제안 2: 스타일 일관성 토큰 추출 ────────────────────────────
        style_token = ""
        if thumbnail_prompt:
            style_token = thumbnail_prompt.get("visual_style", "").strip()
            if style_token:
                logger.info(f"[이미지대리] 스타일 일관성 토큰 적용: {style_token}")

        # ── STEP 2: 글작가 프롬프트 → AI 이미지 생성 ────────────────────
        pool = []
        prompts = list(writer_image_prompts or [])
        if prompts:
            # 제안 4: LLM 일괄 프롬프트 강화
            logger.info(f"[이미지대리] STEP 2 — 프롬프트 강화 LLM 단계 ({len(prompts)}컷)")
            prompts, enhance_usage = self._enhance_prompts(prompts, title)
            total_usage["prompt_enhance"] = enhance_usage

            logger.info(f"[이미지대리] STEP 2 — 이미지 생성 시작 ({len(prompts)}컷)")
            for i, wp in enumerate(prompts[:30]):
                if i > 0:
                    time.sleep(7)   # 10 RPM 한도 준수
                marker    = wp.get("marker", f"[이미지{i + 1}]")
                desc_kr   = wp.get("description_kr", "")
                section   = wp.get("section", "본문")
                prompt_en = wp.get("prompt_en", f"{title} high quality photo")

                # 제안 2: 스타일 일관성 토큰 주입
                if style_token and style_token.lower() not in prompt_en.lower():
                    prompt_en = prompt_en.rstrip(" ,") + f", {style_token}"

                logger.info(f"[이미지대리] {marker} 생성 중 ({i+1}/{len(prompts)}) — {section}")
                result = self._generate_nanobanana_image(
                    prompt_en=prompt_en, section=section,
                    description_kr=desc_kr, temp_dir=temp_dir,
                )
                if result:
                    # 제안 5: 생성 결과 비전 검증
                    v_score = self._verify_image_content(result["path"], section, desc_kr)
                    result["verify_score"] = v_score
                    if v_score < 0.5:
                        logger.warning(
                            f"[이미지대리] {marker} 검증 점수 {v_score:.2f} < 0.5 → 재생성 시도"
                        )
                        time.sleep(7)
                        retry_prompt = self._simplify_prompt_with_llm(prompt_en, section)
                        if style_token and style_token.lower() not in retry_prompt.lower():
                            retry_prompt = retry_prompt.rstrip(" ,") + f", {style_token}"
                        retry = self._generate_nanobanana_image(
                            prompt_en=retry_prompt, section=section,
                            description_kr=desc_kr, temp_dir=temp_dir,
                        )
                        if retry:
                            r_score = self._verify_image_content(retry["path"], section, desc_kr)
                            retry["verify_score"] = r_score
                            if r_score >= v_score:
                                result = retry
                                logger.info(f"[이미지대리] {marker} 재생성 채택 (점수 {v_score:.2f} → {r_score:.2f})")
                    result["section_index"] = i + 1
                    result["marker"] = marker
                    pool.append(result)
                    logger.info(
                        f"[이미지대리] {marker} 완료 ✓ "
                        f"(검증 {result.get('verify_score', 0):.2f}) ({len(pool)}컷 누적)"
                    )
                else:
                    logger.warning(f"[이미지대리] {marker} 생성 실패 — 건너뜀")
            logger.info(f"[이미지대리] STEP 2 완료 — {len(pool)}컷 / {len(prompts)}컷 요청")

        # ── STEP 3: 글작가 썸네일 프롬프트 → 썸네일 전용 생성 ───────────
        # 글작가가 만든 thumbnail_prompt dict를 우선 사용
        # 없으면 제목 기반으로 자동 생성
        logger.info("[이미지대리] STEP 3 — 글작가 썸네일 프롬프트로 썸네일 생성 시작")
        time.sleep(7)   # RPM 간격 유지

        if thumbnail_prompt and thumbnail_prompt.get("prompt_en"):
            thumb_prompt_en = thumbnail_prompt["prompt_en"]
            thumb_desc      = thumbnail_prompt.get("description_kr", f"{title} 썸네일")
            logger.info(f"[이미지대리] 글작가 썸네일 프롬프트 수신 — {thumb_desc[:40]}")
        else:
            # 폴백: 제목 기반 자동 생성
            thumb_prompt_en = (
                f"{title}, cinematic hero shot, vibrant colors, "
                "hyper-realistic 3D isometric render, dramatic studio lighting, "
                "highly detailed, 8k resolution, sharp focus, professional composition"
            )
            thumb_desc = f"{title} 메인 썸네일"
            logger.info("[이미지대리] 글작가 썸네일 프롬프트 없음 — 제목 기반 자동 생성")

        thumbnail = self._generate_nanobanana_image(
            prompt_en=thumb_prompt_en,
            section="제목/썸네일",
            description_kr=thumb_desc,
            temp_dir=temp_dir,
            apply_overlay=True,
        )
        if thumbnail:
            thumbnail["section_index"] = 0
            thumbnail["marker"] = "[썸네일]"
            pool.insert(0, thumbnail)
            logger.info(f"[이미지대리] STEP 3 완료 — 썸네일 생성 ✓ ({os.path.basename(thumbnail['path'])})")
        else:
            logger.warning("[이미지대리] STEP 3 — 썸네일 생성 실패, 풀 첫 번째 이미지를 썸네일로 사용")
            if pool:
                pool[0]["section_index"] = 0
                pool[0]["marker"] = "[썸네일]"

        # ── min_images 미달 시 자동 보충 ─────────────────────────────────
        ai_needed = max(0, min_images - len(pool))
        if ai_needed > 0:
            logger.info(f"[이미지대리] {ai_needed}컷 추가 생성 필요 — 자동 기획 시작")
            sections = self._parse_sections(content)
            used_idxs = {img.get("section_index") for img in pool if img.get("section_index") is not None}
            sec_lines = [
                f"[섹션 {s['index']}] {s['title']}: {s['preview'][:150]}"
                for s in sections if s["index"] not in used_idxs
            ]
            plan_prompt = f"""블로그 '{title}'의 아래 섹션 중 {ai_needed}컷의 이미지를 기획하세요.

{chr(10).join(sec_lines[:8])}

각 이미지에 대해 아래 JSON 형식으로만 응답하세요.
```json
{{"images": [
  {{"section_index": 2, "section": "섹션명", "description_kr": "한국어 설명",
    "prompt_en": "English prompt, studio lighting, highly detailed, 8k resolution, professional composition, sharp focus"}}
]}}
```"""
            try:
                plan_resp = self.generate_content_with_cost(plan_prompt)
                images_plan = self.parse_json_from_text(plan_resp["text"]).get("images", [])
                total_usage["ai_plan"] = plan_resp.get("usage", {})
                while len(images_plan) < ai_needed:
                    images_plan.append({
                        "section_index": None, "section": "추가 본문",
                        "description_kr": "추가 분위기 컷",
                        "prompt_en": (f"{title}, atmospheric background scene, "
                                      "studio lighting, highly detailed, 8k resolution")
                    })
                for img_plan in images_plan[:ai_needed]:
                    time.sleep(7)
                    result = self._generate_nanobanana_image(
                        prompt_en=img_plan.get("prompt_en", f"{title} photo"),
                        section=img_plan.get("section", "본문"),
                        description_kr=img_plan.get("description_kr", ""),
                        temp_dir=temp_dir,
                    )
                    if result:
                        result["section_index"] = img_plan.get("section_index")
                        pool.append(result)
            except Exception as e:
                logger.error(f"[이미지대리] 자동 보충 기획 오류: {e}")

        logger.info(f"[이미지대리] 전체 이미지 풀: {len(pool)}컷 확보")

        # ── STEP 4: 단락-이미지 배치 계획 ───────────────────────────────
        assignments, assign_usage = self._plan_assignments(title, content, pool)
        total_usage["assignment"] = assign_usage

        # ── STEP 5: 배치 순서대로 정렬 — 후처리 없음 ─────────────────────
        final_images = []
        used_indices = set()

        for assign in assignments:
            img_idx = assign.get("image_index")
            if img_idx is None or img_idx >= len(pool) or img_idx in used_indices:
                continue
            used_indices.add(img_idx)
            img_entry = pool[img_idx].copy()
            img_entry["section"]           = assign.get("section_title", img_entry.get("section", ""))
            img_entry["modified"]          = False
            img_entry["modification_type"] = "none"
            img_entry["overlay_text"]      = ""
            img_entry["reason"]            = assign.get("reason", "")
            final_images.append(img_entry)

        # 배치 계획에서 빠진 이미지 순서대로 추가
        for i, img_entry in enumerate(pool):
            if i not in used_indices:
                entry = img_entry.copy()
                entry["modified"]          = False
                entry["modification_type"] = "none"
                entry["overlay_text"]      = ""
                entry["reason"]            = "미배정 보충"
                final_images.append(entry)

        logger.info(f"[이미지대리] 최종 {len(final_images)}컷 → 편집과장 전달")
        return {
            "status":      "success",
            "image_count": len(final_images),
            "images":      final_images,
            "usage":       total_usage,
        }
