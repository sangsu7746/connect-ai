import datetime
from fastapi import APIRouter, HTTPException
from core.db import get_conn
from core import naver

router = APIRouter(prefix="/api/categories", tags=["trends"])

@router.post("/{cid}/trends/refresh")
def refresh_trends(cid: int):
    conn = get_conn()
    try:
        kws = [r["keyword"] for r in conn.execute(
            "SELECT keyword FROM seed_keywords WHERE category_id=?", (cid,))]
        if not kws:
            raise HTTPException(404, "no seed keywords")
        ratios = naver.datalab_ratios(kws)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        rows = []
        for kw, (last, prev) in ratios.items():
            rp = naver.rise_pct(last, prev)
            conn.execute("""INSERT INTO trends(category_id,keyword,ratio_last,
                            ratio_prev,rise_pct,fetched_at) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(category_id,keyword) DO UPDATE SET
                            ratio_last=excluded.ratio_last,
                            ratio_prev=excluded.ratio_prev,
                            rise_pct=excluded.rise_pct,
                            fetched_at=excluded.fetched_at""",
                         (cid, kw, last, prev, rp, now))
            rows.append({"keyword": kw, "rise_pct": rp})
        conn.commit()
        return sorted(rows, key=lambda x: -x["rise_pct"])
    finally:
        conn.close()
