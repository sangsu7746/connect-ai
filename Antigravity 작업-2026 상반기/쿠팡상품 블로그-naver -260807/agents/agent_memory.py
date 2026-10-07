"""
agent_memory.py — 블로그 성과 기반 에이전트 강화 학습 메모리

블로그 성과 지표(조회수·좋아요·댓글수)를 기반으로:
  ① 우수 출력물을 few-shot 예시로 자동 누적 → 다음 실행 프롬프트에 주입
  ② 파라미터(extra_instruction·길이·이미지수) 자동 조정
  ③ run_daily_posting 세션 저장 → run_nightly_batch에서 지표 기록

사용 흐름:
  [포스팅] run_daily_posting → 세션 스냅샷 저장
  [야간]   run_nightly_batch(stats) → memory.record_session(stats) 호출
  [다음날] 각 에이전트 execute() 시 few-shot/param 자동 반영
"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# memory_store 디렉토리: agents/ 폴더 안에 생성
_STORE_DIR = os.path.join(os.path.dirname(__file__), "memory_store")

# ── 성과 지표 가중치 & 정규화 기준 ──────────────────────────────────────────
_WEIGHTS = {"views": 0.40, "likes": 0.35, "comments": 0.25}
# 기준값: 조회수 1000·좋아요 50·댓글 20에서 만점 10점
_NORM    = {"views": 1000, "likes": 50,   "comments": 20}

_MAX_RECORDS           = 20   # 에이전트당 최대 보관 레코드 수
_MIN_SCORE_FOR_FEWSHOT = 7.0  # few-shot 예시로 활용할 최소 점수
_LOW_THRESHOLD         = 5.5  # 이 이하 → 창의성·풍부도 강화 지시
_HIGH_THRESHOLD        = 8.0  # 이 이상 → 현재 패턴 유지


class AgentMemory:
    """에이전트별 성과 기록을 관리하고 프롬프트 강화·파라미터 조정을 제공한다."""

    def __init__(self):
        os.makedirs(_STORE_DIR, exist_ok=True)

    # ── 점수 계산 ─────────────────────────────────────────────────────────────
    @staticmethod
    def calculate_score(metrics: dict) -> float:
        """
        조회수·좋아요·댓글수를 가중합산해 0~10점으로 환산한다.
        각 지표는 정규화 기준값(_NORM) 기준 10점 만점.
        """
        score = 0.0
        for key, weight in _WEIGHTS.items():
            val  = float(metrics.get(key, 0))
            norm = float(_NORM.get(key, 1))
            score += weight * min(val / norm, 1.0) * 10
        return round(score, 2)

    # ── 기록 저장 ──────────────────────────────────────────────────────────────
    def record(
        self,
        agent_name:     str,
        input_summary:  str,
        output_summary: str,
        output_snippet: str,
        metrics:        dict,
        params:         dict | None = None,
    ) -> float:
        """
        에이전트 실행 결과와 블로그 성과 지표를 기록한다.
        반환: 계산된 종합 점수 (0~10)
        """
        score = self.calculate_score(metrics)
        entry = {
            "agent_name":     agent_name,
            "timestamp":      datetime.now().isoformat(),
            "input_summary":  input_summary,
            "output_summary": output_summary,
            "output_snippet": output_snippet[:400],
            "metrics":        metrics,
            "score":          score,
            "params":         params or {},
        }
        records = self._load(agent_name)
        records.append(entry)
        # 초과 시 점수 낮은 것부터 제거
        if len(records) > _MAX_RECORDS:
            records = sorted(records, key=lambda r: r["score"], reverse=True)[:_MAX_RECORDS]
        self._save(agent_name, records)
        m = metrics
        logger.info(
            f"[AgentMemory] {agent_name} 기록 저장 ✅ "
            f"점수 {score:.1f}/10 | "
            f"조회 {m.get('views', 0)} · 좋아요 {m.get('likes', 0)} · 댓글 {m.get('comments', 0)}"
        )
        return score

    # ── 세션 일괄 기록 (야간 배치 호출용) ───────────────────────────────────────
    def record_session(self, metrics: dict) -> dict:
        """
        load_session()으로 불러온 세션 데이터를 기준으로
        관여 에이전트 전체에 동일 성과 지표를 기록한다.
        Returns: {agent_name: score} 매핑
        """
        session = self.load_session()
        if not session:
            logger.warning("[AgentMemory] 저장된 세션 없음 — record_session 스킵")
            return {}
        score_map = {}
        for agent_name, snap in session.items():
            score = self.record(
                agent_name=agent_name,
                input_summary=snap.get("input_summary", ""),
                output_summary=snap.get("output_summary", ""),
                output_snippet=snap.get("output_snippet", ""),
                metrics=metrics,
                params=snap.get("params", {}),
            )
            score_map[agent_name] = score
        return score_map

    # ── 우수 예시 조회 ──────────────────────────────────────────────────────────
    def get_top_examples(self, agent_name: str, k: int = 3) -> list:
        """점수 기준 상위 k개 예시 반환. _MIN_SCORE_FOR_FEWSHOT 미달 제외."""
        records = self._load(agent_name)
        qualified = [r for r in records if r["score"] >= _MIN_SCORE_FOR_FEWSHOT]
        return sorted(qualified, key=lambda r: r["score"], reverse=True)[:k]

    # ── few-shot 블록 생성 (프롬프트 앞에 삽입) ──────────────────────────────────
    def build_fewshot_block(self, agent_name: str, k: int = 2) -> str:
        """
        상위 k개 예시를 few-shot 블록 문자열로 반환.
        예시가 없거나 점수 기준 미달이면 빈 문자열 반환.
        """
        examples = self.get_top_examples(agent_name, k=k)
        if not examples:
            return ""
        lines = [f"\n[📚 {agent_name} 강화 학습 — 과거 우수 사례 {len(examples)}건]"]
        for i, ex in enumerate(examples, 1):
            m = ex["metrics"]
            lines.append(
                f"\n▶ 우수 사례 {i}  성과 점수 {ex['score']:.1f}/10 "
                f"(조회 {m.get('views',0)} · 좋아요 {m.get('likes',0)} · 댓글 {m.get('comments',0)})"
            )
            lines.append(f"  주제/입력: {ex['input_summary']}")
            lines.append(f"  결과 요약: {ex['output_summary']}")
            if ex.get("output_snippet"):
                lines.append(f"  우수 구절:\n  {ex['output_snippet'][:250]}")
        lines.append("\n위 우수 사례의 구조·톤·길이 패턴을 이번 작업에 적극 반영하라.\n")
        return "\n".join(lines)

    # ── 파라미터 자동 조정 ──────────────────────────────────────────────────────
    def get_param_adjustments(self, agent_name: str) -> dict:
        """
        최근 5회 평균 점수 기반으로 에이전트별 파라미터 조정값을 반환한다.

        반환 키:
          avg_score          (float)  최근 평균 점수
          trend              (float)  이전 대비 변화량 (+상승/-하락)
          extra_instruction  (str)    프롬프트 말미에 추가할 강화 지시
          min_images_delta   (int)    이미지대리 전용: 이미지 수 증감
          length_hint        (str)    글 길이 힌트 ("longer" | "shorter" | "maintain")
        """
        records = self._load(agent_name)
        if not records:
            return {}

        recent = sorted(records, key=lambda r: r["timestamp"], reverse=True)[:5]
        avg    = sum(r["score"] for r in recent) / len(recent)
        prev   = sum(r["score"] for r in recent[1:]) / max(len(recent) - 1, 1)
        trend  = round(avg - prev, 2)

        adj = {"avg_score": round(avg, 2), "trend": trend}

        if avg < _LOW_THRESHOLD:
            adj["extra_instruction"] = (
                f"⚠️ [강화학습] 최근 5회 평균 성과 점수 {avg:.1f}/10으로 낮습니다 (트렌드 {trend:+.1f}). "
                "독자 흥미를 끄는 스토리텔링·구체적 수치·실용 팁을 더 풍부하게 추가하고, "
                "제목의 호기심 유발과 첫 문장의 임팩트를 강화하세요."
            )
            adj["min_images_delta"] = +2
            adj["length_hint"]      = "longer"
        elif avg >= _HIGH_THRESHOLD:
            adj["extra_instruction"] = (
                f"✅ [강화학습] 최근 5회 평균 성과 점수 {avg:.1f}/10으로 우수합니다 (트렌드 {trend:+.1f}). "
                "현재 패턴을 유지하며 더욱 정교하게 작성하세요."
            )
            adj["min_images_delta"] = 0
            adj["length_hint"]      = "maintain"
        else:
            adj["extra_instruction"] = (
                f"📊 [강화학습] 최근 5회 평균 성과 점수 {avg:.1f}/10 (트렌드 {trend:+.1f}). "
                "지속적 개선을 위해 가독성과 정보 밀도를 균형있게 높이세요."
            )
            adj["min_images_delta"] = +1 if avg < 6.5 else 0
            adj["length_hint"]      = "longer" if avg < 6.5 else "maintain"

        return adj

    # ── 세션 저장/로드 ──────────────────────────────────────────────────────────
    def save_session(self, session: dict) -> None:
        """
        run_daily_posting 종료 시 에이전트별 스냅샷을 저장한다.
        session 구조: {agent_name: {input_summary, output_summary, output_snippet, params}}
        """
        path = os.path.join(_STORE_DIR, "last_session.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        logger.info(f"[AgentMemory] 세션 저장 완료 ({len(session)}개 에이전트)")

    def load_session(self) -> dict:
        """run_nightly_batch에서 마지막 포스팅 세션을 불러온다."""
        path = os.path.join(_STORE_DIR, "last_session.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[AgentMemory] 세션 로드 실패: {e}")
            return {}

    # ── 트렌드 리포트 ───────────────────────────────────────────────────────────
    def get_trend_report(self) -> str:
        """전체 에이전트 성과 트렌드 요약 문자열을 반환한다."""
        agents = ["글작가", "편집과장", "이미지대리", "서치대리"]
        lines  = ["=" * 55, "  에이전트 강화 학습 성과 리포트", "=" * 55]
        for name in agents:
            records = self._load(name)
            if not records:
                lines.append(f"  {name}: 기록 없음")
                continue
            recent = sorted(records, key=lambda r: r["timestamp"], reverse=True)[:5]
            scores = [r["score"] for r in recent]
            avg    = sum(scores) / len(scores)
            trend  = scores[0] - scores[-1] if len(scores) > 1 else 0
            lines.append(
                f"  {name}: 평균 {avg:.1f}/10 | 최고 {max(scores):.1f}/10 | "
                f"누적 {len(records)}건 | 트렌드 {trend:+.1f}"
            )
        lines.append("=" * 55)
        return "\n".join(lines)

    # ── 내부 IO ──────────────────────────────────────────────────────────────────
    def _path(self, agent_name: str) -> str:
        safe = agent_name.replace("/", "_").replace(" ", "_")
        return os.path.join(_STORE_DIR, f"{safe}_records.json")

    def _load(self, agent_name: str) -> list:
        p = self._path(agent_name)
        if not os.path.exists(p):
            return []
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, agent_name: str, records: list) -> None:
        with open(self._path(agent_name), "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


# ── 싱글톤 (모든 에이전트에서 공유) ─────────────────────────────────────────────
_instance: "AgentMemory | None" = None


def get_memory() -> AgentMemory:
    """프로세스 단위 싱글톤 AgentMemory 인스턴스를 반환한다."""
    global _instance
    if _instance is None:
        _instance = AgentMemory()
    return _instance
