SEED = {
    "부동산": ("🏠", ["전세 보증보험", "청약 가점", "재개발 투자", "월세 계약", "등기부등본 보는법"]),
    "재테크": ("💰", ["ISA 계좌", "연금저축펀드", "파킹통장 금리", "배당주 투자", "연말정산 절세"]),
    "건강":   ("💪", ["단백질 섭취량", "수면의 질", "혈당 관리", "허리 통증 스트레칭", "간헐적 단식"]),
    "요리":   ("🍳", ["에어프라이어 레시피", "밑반찬 만들기", "자취 요리", "도시락 메뉴", "김치찌개 황금레시피"]),
    "여행":   ("✈️", ["제주 여행 코스", "일본 여행 준비물", "국내 당일치기", "캠핑 준비물", "호텔 싸게 예약"]),
    "IT":     ("💻", ["아이폰 숨은기능", "노션 활용법", "챗GPT 활용", "윈도우 단축키", "갤럭시 설정"]),
}

def ensure_seed(conn) -> None:
    if conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]:
        return
    for name, (emoji, kws) in SEED.items():
        cur = conn.execute(
            "INSERT INTO categories(name, emoji) VALUES(?,?)", (name, emoji))
        for kw in kws:
            conn.execute(
                "INSERT INTO seed_keywords(category_id, keyword) VALUES(?,?)",
                (cur.lastrowid, kw))
    conn.commit()
