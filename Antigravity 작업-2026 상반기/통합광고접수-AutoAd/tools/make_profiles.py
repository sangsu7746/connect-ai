# -*- coding: utf-8 -*-
"""홍보서 12종 → 업종 프로필 생성 (한 번만 실행하면 됨)

URL 은 각 홍보서 PDF 에 적힌 주소를 정본으로 쓴다(추측 금지, 접속 확인 완료).
NailPreview·WrapPreview 는 미배포라 제외.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

DOCS = Path(r"D:\headjim AI-LAB-Template\docs\광고홍보서")
OUT = Path(__file__).parent.parent / "profiles"

# 공통 금칙어 — AI 생성물이라 '완벽/100%' 류 확정 표현은 위험
BASE_BANNED = ["무조건", "100%", "완벽하게", "절대"]
# 미용·신체 관련은 의료 표현 추가 금지(의료법)
BEAUTY_BANNED = BASE_BANNED + ["치료", "부작용 없", "영구"]

AI_DISC = "※ AI가 생성한 결과물로, 실제와 다를 수 있습니다."
PREVIEW_DISC = "※ 미리보기는 AI가 생성한 예상 이미지로, 실제 결과와 다를 수 있습니다."

P = [
    # key, 표시명, 회사명, site, doc파일 키워드, disclaimer, banned, note
    ("adstudio", "AdStudio (AI 광고영상)", "AdStudio", "ad-studio-app.web.app",
     "AdStudio", AI_DISC, BASE_BANNED, "광고 제작 서비스. 성과·매출 보장 표현 금지."),
    ("colorcraft", "ColorCraft Kids (컬러링)", "ColorCraft Kids", "headjim-color.web.app",
     "ColorCraft", AI_DISC, BASE_BANNED, "아동 대상. 교육 효과를 단정하는 표현 금지."),
    ("inkcraft", "InkCraft (타투 도안)", "InkCraft", "headjim-ink.web.app",
     "InkCraft", PREVIEW_DISC, BEAUTY_BANNED,
     "타투 도안. 시술 결과·안전성을 단정하는 표현 금지(의료 영역 아님)."),
    ("memoryfilm", "MemoryFilm (기념 영상)", "MemoryFilm", "memoryfilm.web.app",
     "MemoryFilm", AI_DISC, BASE_BANNED, "기념 영상 제작. 감성 소구는 좋으나 과장 금지."),
    ("petportrait", "PetPortrait (반려동물 초상화)", "PetPortrait", "headjim-petportrait.web.app",
     "PetPortrait", AI_DISC, BASE_BANNED, "반려동물 초상화. 실물과의 동일성 단정 금지."),
    ("photomagic", "PhotoMagic (사진 변환)", "PhotoMagic", "headjim-photomagic.web.app",
     "PhotoMagic", AI_DISC, BASE_BANNED, "사진 변환. 원본 훼손·복원 보장 표현 금지."),
    ("printcraft", "PrintCraft AI (POD 디자인)", "PrintCraft AI", "headjim-pod.web.app",
     "PrintCraft", AI_DISC, BASE_BANNED,
     "POD 디자인. 상업 이용 권리는 사실대로만(FLUX.1 Apache 2.0 기반)."),
    ("proheadshot", "ProHeadshot (프로필 사진)", "ProHeadshot", "headjim-headshot.web.app",
     "ProHeadshot", PREVIEW_DISC, BEAUTY_BANNED,
     "프로필 사진. 취업·합격 등 결과를 암시하는 표현 금지."),
    ("stickerme", "StickerMe (캐릭터 스티커)", "StickerMe", "headjim-stickerme.web.app",
     "StickerMe", AI_DISC, BASE_BANNED, "캐릭터 스티커. 타 IP·캐릭터 연상 표현 금지."),
    ("wallpreview", "WallPreview (월아트 미리보기)", "WallPreview", "wallpreview-web.web.app",
     "WallPreview", PREVIEW_DISC, BASE_BANNED, "인테리어 미리보기. 실제 시공 결과 단정 금지."),
    ("mirizip", "미리집 (인테리어 미리보기)", "미리집", "mirizip.com",
     "미리집", PREVIEW_DISC, BASE_BANNED,
     "인테리어 미리보기. 시공비·기간을 단정하는 표현 금지."),
    ("homage", "오마주 (영상 스튜디오)", "오마주 영상 스튜디오", "headjim-ai.web.app",
     "오마주", AI_DISC, BASE_BANNED, "추모·기념 영상. 대상의 존엄을 해치는 표현 금지."),
]

TPL = """# ============================================================
#  업종 프로필 — {name}
#  홍보서에서 자동 생성 (URL 은 홍보서에 적힌 주소, 접속 확인 완료)
#  전환:  .env 의 AUTOAD_PROFILE={key}
# ============================================================
key: {key}
name: "{name}"

brand:
  company: "{company}"
  roman: ""
  phone: ""                      # 웹 서비스 → 전화 대신 site 로 유도
  region: "전국 온라인"
  channels: "웹에서 바로 이용"
  registered: ""
  site: "{site}"
  reg_no: ""

compliance:
  disclaimer: "{disc}"
  banned_phrases:
{banned}
  note: "{note}"

content:
  source: docs                   # 기성 전단이 없으므로 홍보서에서 소재 생성
  flyers_dir: ""
  docs_dir: "{docs_dir}"
  doc: "{doc}"                   # 이 업종의 기본 설명서

fallback_copy:
  body: "{fallback}"

intake:
  title: "서비스 문의"
  target: none                   # 대출앱으로 보내지 않음 (클라우드 수신함에만)
"""


def find_doc(keyword: str):
    for p in DOCS.glob("*.pdf"):
        if keyword.lower() in p.name.lower():
            return p.name
    return ""


def main():
    made = 0
    for key, name, company, site, kw, disc, banned, note in P:
        doc = find_doc(kw)
        if not doc:
            print(f"  [건너뜀] {key}: 홍보서 못 찾음({kw})")
            continue
        body = f"{company} — 자세한 내용은 {site} 에서 확인하세요."
        txt = TPL.format(
            key=key, name=name, company=company, site=site, disc=disc, note=note,
            banned="\n".join(f'    - "{b}"' for b in banned),
            docs_dir=str(DOCS).replace("\\", "/"), doc=doc, fallback=body)
        (OUT / f"{key}.yaml").write_text(txt, encoding="utf-8")
        print(f"  생성 {key:12s} {site:32s} ← {doc[:30]}")
        made += 1
    print(f"\n프로필 {made}개 생성 완료 → {OUT}")


if __name__ == "__main__":
    main()
