import sys
from agents.orchestrator import MasterOrchestrator

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    print("🚀 네블기(네이버 블로그 마스터) 시작 준비 중...")
    orchestrator = MasterOrchestrator()
    
    # 편집장 지시사항 실행
    orchestrator.run_daily_posting(
        topic="2026년 부동산 청약 트렌드",
        keywords="부동산, 청약, 내집마련, 신혼부부",
        tone_and_manner="전문적이고 신뢰감을 주지만, 사회초년생도 이해하기 쉽게 비유를 많이 써주세요.",
        theme_name="💰 재테크"
    )
