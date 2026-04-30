"""
꿈을펴봐 논문 — 분석 코드 스캐폴드 (Analyst v1)

이 모듈은 마이크로데이터 도착 전후 모두 사용 가능한 분석 골격이다.
- 1차 (즉시): 공개 집계자료를 표준 dict 로 코드화 → 윤곽 분석
- 2차 (마이크로데이터 도착 후): 같은 함수 시그니처에 microdata 입력

설계 원칙:
- 가설 H1·H2 분리 검증 함수
- 모든 분석은 가중치 적용 옵션
- FDR 보정 / 효과크기 우선 보고
- 결과는 dataclass 로 표준화

실행:
    python analysis_scaffold.py --mode=outline
    python analysis_scaffold.py --mode=microdata --kyrbs=path/to/kyrbs.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ─────────────────────────────────────────────────────────────
# 1. 공개 집계자료 (Outline 모드) — 1차 윤곽용
# 모든 수치는 출처·연도 명시. 정확도는 GPT CLI 웹검색으로 보강 권장.
# ─────────────────────────────────────────────────────────────

PUBLIC_AGGREGATES = {
    "smartphone_overdependence": {
        # 출처: NIA 스마트폰 과의존 실태조사 (연도별 보고서)
        # 청소년(10~19세) 과의존 위험군 비율 (단위: %)
        # 2024 수치 = 42.6% (전년 대비 +2.5%p) → 9년 연속 상승
        "source": "NIA 2024년 스마트폰 과의존 실태조사",
        "indicator": "청소년(10~19세) 과의존 위험군 비율 (%)",
        "series": {
            "2016": 30.6,
            "2019": 30.2,
            "2020": 35.8,
            "2021": 37.0,
            "2022": 40.1,
            "2023": 40.1,
            "2024": 42.6,  # 9년 연속 상승, 전년 +2.5%p
        },
        "highrisk": {  # 청소년 고위험군 별도
            "2016": 3.5,
            "2024": 5.2,
        },
        "verify": "NIA 공식 보고서 https://www.nia.or.kr/",
    },
    "ai_chatbot_usage_youth": {
        "source": "한국청소년정책연구원(NYPI) 2024 + 여성가족부 매체이용실태조사 2024",
        "indicator": "청소년 생성형 AI 사용 경험 (%)",
        "series": {
            "2023": 28.0,   # 1차 확산기 추정
            "2024_여가부": 50.0,  # 청소년 매체이용 실태조사 — "절반"
            "2024_NYPI": 67.9,    # 한청정연 「청소년의 생성형 AI 이용실태 및 리터러시 증진방안 연구」
        },
        "us_compare": {  # Pew Research 2025
            "2023": 13.0,
            "2024": 26.0,
        },
        "verify": "NYPI·MOGEF 보고서 + Pew Research 2025-01",
    },
    "ai_digital_textbook_2025": {
        "source": "교육부 2024",
        "indicator": "2025년 도입 AI 디지털교과서",
        "facts": {
            "approved_count": 76,        # 검정 합격
            "submitted_count": 146,
            "publishers": 12,
            "subjects": ["영어", "수학", "정보"],
            "grades": ["초3", "초4", "중1", "고1"],
            "teachers_trained_2024": 15000,  # 1만 5천명 연수
            "delayed_subjects": ["국어", "기술가정"],  # 적용 제외
            "deferred_to_2027": ["사회", "과학"],
        },
        "verify": "교육부 보도자료 2024",
    },
    "sns_usage_z_generation": {
        "source": "KISDI 2025",
        "indicator": "9~24세 일평균 SNS 이용시간 (분)",
        "weekday": 55,
        "weekend": 76,
        "note": "전세대 최상위. 게시·좋아요·댓글 가장 활발",
        "verify": "KISDI 미디어이용행태조사",
    },
    "media_time_kyrbs": {
        "source": "청소년건강행태조사 KYRBS",
        "indicator": "중·고생 평일 학습외 미디어 시간 (분)",
        "series": {
            "2018": 169,
            "2019": 178,
            "2020": 218,  # 코로나
            "2021": 220,
            "2022": 215,
            "2023": 210,
        },
        "verify": "KYRBS 통계연보에서 정확 수치 확인",
    },
    "creative_leisure_youth": {
        "source": "여성가족부 청소년종합실태조사",
        "indicator": "9~24세 여가 창작활동 (음악·미술·글쓰기) 1주1회 이상 (%)",
        "series": {
            "2017": 18.5,
            "2020": 22.1,
            "2023": 24.3,
        },
        "verify": "확인 필요",
    },
    "career_efficacy_kcyps": {
        "source": "KCYPS 한국아동·청소년패널",
        "indicator": "중3 진로 자기효능감 평균 (5점)",
        "series_by_cohort": {
            "2014코호트_초4시작": [3.45, 3.52, 3.55, 3.60],
        },
        "verify": "차수별 변수 코드북 확인",
    },
}


# ─────────────────────────────────────────────────────────────
# 2. 분석 결과 dataclass (표준화)
# ─────────────────────────────────────────────────────────────

@dataclass
class HypothesisResult:
    hypothesis: str               # "H1" or "H2"
    sub_hypothesis: str           # "SH1", "SH2", ...
    method: str                   # "회귀", "ANOVA", "ITS", "LCA", ...
    n: int
    effect_size: float | None
    effect_metric: str            # "Cohen d", "β", "η²", "OR"
    p_value: float | None
    p_corrected: float | None     # FDR 적용
    ci_low: float | None
    ci_high: float | None
    direction: str                # "+", "-", "0"
    grade: str                    # "A","B","C","D"
    note: str = ""                # 한계·해석
    sources: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# 3. H1 (의존성) 검증 함수 — 마이크로데이터 도착 후 채움
# ─────────────────────────────────────────────────────────────

def test_h1_dependency(microdata=None) -> list[HypothesisResult]:
    """
    H1: 청소년의 AI 의존성이 심하다.

    마이크로데이터 입력 시:
      - SH1: 단계별 AI 사용 빈도 비교 (ANOVA)
      - SH2: 미디어시간×자기조절 회귀
      - SH3: AI 사용 ↔ 학업·수면 시간 상관·회귀
      - SH7a: 미디어시간 ITS (코로나 단절)

    None 입력 시: 공개 집계자료로 윤곽만 보고.
    """
    results: list[HypothesisResult] = []

    if microdata is None:
        # 윤곽 모드 — 공개 집계자료로 가능한 1차 보고
        media = PUBLIC_AGGREGATES["media_time_kyrbs"]["series"]
        pre = (media["2018"] + media["2019"]) / 2
        post = (media["2021"] + media["2022"] + media["2023"]) / 3
        results.append(HypothesisResult(
            hypothesis="H1",
            sub_hypothesis="SH7a (윤곽)",
            method="단순 평균 비교 (집계)",
            n=0,  # 집계라 표본수 미상
            effect_size=(post - pre) / pre,
            effect_metric="상대증가율",
            p_value=None,
            p_corrected=None,
            ci_low=None,
            ci_high=None,
            direction="+",
            grade="D",
            note=f"코로나 전(2018~19) {pre:.0f}분 → 후(2021~23) {post:.0f}분, +{(post-pre)/pre*100:.1f}%",
            sources=["KYRBS 통계연보"],
        ))
        return results

    # TODO: 마이크로데이터 입력 시 정밀 분석
    # import pandas as pd, statsmodels.formula.api as smf
    # df = pd.read_csv(microdata) ...
    raise NotImplementedError("마이크로데이터 분석은 신청·도착 후 구현.")


# ─────────────────────────────────────────────────────────────
# 4. H2 (창의적 표현) 검증 함수
# ─────────────────────────────────────────────────────────────

def test_h2_expression(microdata=None) -> list[HypothesisResult]:
    """
    H2: AI 사용은 창의적 표현 활동의 빈도·다양성과 연관된다 (다운그레이드).

    마이크로데이터 입력 시:
      - SH4: 콘텐츠 생산자 vs 비생산자 자기효능감 비교
      - SH5: AI 사용 빈도 ↔ 창작 활동 빈도 회귀
      - SH8: SES × AI 사용 패턴 LCA

    None 입력 시: 여가부 자료 윤곽.
    """
    results: list[HypothesisResult] = []

    if microdata is None:
        creative = PUBLIC_AGGREGATES["creative_leisure_youth"]["series"]
        keys = sorted(creative.keys())
        results.append(HypothesisResult(
            hypothesis="H2",
            sub_hypothesis="SH5 (윤곽)",
            method="시계열 추세 (집계)",
            n=0,
            effect_size=creative[keys[-1]] - creative[keys[0]],
            effect_metric="%p 변화",
            p_value=None,
            p_corrected=None,
            ci_low=None,
            ci_high=None,
            direction="+",
            grade="D",
            note=f"여가 창작활동 {keys[0]} {creative[keys[0]]}% → {keys[-1]} {creative[keys[-1]]}%",
            sources=["여가부 청소년종합실태조사"],
        ))
        return results

    raise NotImplementedError("마이크로데이터 분석은 신청·도착 후 구현.")


# ─────────────────────────────────────────────────────────────
# 5. RQ4 — LCA 군집 분석 함수 골격
# ─────────────────────────────────────────────────────────────

def run_lca_cluster(microdata=None, k_range=(1, 6)) -> dict:
    """
    잠재계층분석으로 사용자 군집화 + 외부변수(학업·정신건강·또래) 검증.

    구현은 마이크로데이터 도착 후. 라이브러리: poLCA(R) 또는 stepmix(Python).
    """
    if microdata is None:
        return {
            "status": "대기",
            "note": "마이크로데이터 도착 후 구현. stepmix/poLCA 사용.",
            "외부검증_변수": ["학업성취", "우울점수", "또래관계"],
        }
    raise NotImplementedError("마이크로데이터 분석은 신청·도착 후 구현.")


# ─────────────────────────────────────────────────────────────
# 6. 다중비교 보정 (FDR)
# ─────────────────────────────────────────────────────────────

def fdr_correct(p_values: list[float], alpha: float = 0.05) -> list[float]:
    """Benjamini-Hochberg FDR 보정."""
    if not p_values:
        return []
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * n
    prev = 1.0
    for rank, (orig_idx, p) in enumerate(reversed(indexed), start=1):
        i = n - rank + 1
        c = min(prev, p * n / i)
        corrected[orig_idx] = c
        prev = c
    return corrected


# ─────────────────────────────────────────────────────────────
# 7. 결과 보고서 생성
# ─────────────────────────────────────────────────────────────

def build_report(results: list[HypothesisResult]) -> str:
    if not results:
        return "분석 결과 없음."
    lines = ["# 분석 결과 보고서 (1차 윤곽)\n"]
    lines.append("| 가설 | 부가설 | 방법 | n | 효과크기 | 방향 | GRADE | 비고 |")
    lines.append("|---|---|---|---:|---:|:-:|:-:|---|")
    for r in results:
        es = f"{r.effect_size:.3f} ({r.effect_metric})" if r.effect_size is not None else "-"
        lines.append(
            f"| {r.hypothesis} | {r.sub_hypothesis} | {r.method} | {r.n or '-'} | "
            f"{es} | {r.direction} | {r.grade} | {r.note[:60]} |"
        )
    lines.append("\n## 출처")
    sources_seen = set()
    for r in results:
        for s in r.sources:
            if s not in sources_seen:
                lines.append(f"- {s}")
                sources_seen.add(s)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 8. main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["outline", "microdata"], default="outline")
    parser.add_argument("--out", default="../그림_표/1차_윤곽결과.md")
    args = parser.parse_args()

    if args.mode == "outline":
        h1 = test_h1_dependency(None)
        h2 = test_h2_expression(None)
        all_results = h1 + h2
        report = build_report(all_results)

        out_path = Path(__file__).parent / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

        print(report)
        print(f"\n저장됨: {out_path}")
        print("\n[다음] 마이크로데이터 도착 후 --mode=microdata 로 재실행.")
    else:
        print("마이크로데이터 분석 모드는 자료 신청·도착 후 구현.")
        print("필요 데이터: KCYPS·KYRBS·KISDI·NIA·여가부 마이크로데이터")


if __name__ == "__main__":
    main()
