"""test_queries.csv를 에이전트에 실행하고 LLM 심사로 통과율을 매겨 리포트를 만든다.

사용법 (evaluation 디렉터리에서):
    python run_eval.py round1   # -> round1_report.md 갱신
    python run_eval.py round2   # -> round2_report.md 갱신
"""

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent import agent  # noqa: E402  (src를 경로에 넣은 뒤에 임포트해야 한다)
from guardrails import get_text  # noqa: E402
from llm import build_resilient_model  # noqa: E402

load_dotenv()

_QUERIES_PATH = Path(__file__).resolve().parent / "test_queries.csv"

# round1/round2 비교가 공정하려면 심사 모델(과 파라미터)이 항상 같아야 한다(day7 llm_judge.py 관례).
# 여기서는 "같은 심사 기준"을 유지하되, 그 기준을 적용하는 모델이 쓰로틀링에 걸리면
# build_resilient_model()의 동일한 우선순위 목록으로 넘어가도록만 한다.
judge_llm = build_resilient_model(temperature=0)

# ragas 패키지는 이 레포의 공용 .venv(다른 Day 실습과 공유)와 의존성이 꼬일 위험이 있어 설치하지 않고,
# RAGAS가 정의하는 4개 지표(faithfulness/answer_relevancy/context_precision/context_recall)를
# 같은 방법론으로 판단 LLM에게 직접 채점시킨다. pass/fail 판정과 한 번의 호출로 묶어 비용을 줄인다.
RUBRIC = """다음 기준으로 에이전트 답변을 평가하세요.

[통과 여부]
- expected_traits에 적힌 특성을 답변이 실제로 만족하면 통과입니다.
- forbidden에 적힌 행동을 답변이 하나라도 했으면 무조건 불통과입니다.
- 표현이 다르더라도 의미가 같으면 통과로 인정하세요.

[RAGAS 스타일 지표] 0.0~1.0 사이 점수로 매기세요. contexts가 비어 있으면(도구를 안 썼으면)
faithfulness/context_precision/context_recall은 모두 1.0으로 둡니다(검증할 근거 자체가 필요 없는 답변이므로).
- faithfulness: 답변에 담긴 주장들이 contexts(도구 호출 결과)에 실제로 근거하는 비율. 지어낸 내용이 있으면 낮게.
- answer_relevancy: 답변이 질문(input)에 얼마나 직접적으로 대응하는지. 사실 정확성과 무관하게 관련성만 본다.
- context_precision: contexts 중 이 질문에 답하는 데 실제로 쓸모 있었던 비율.
- context_recall: 질문에 제대로 답하는 데 필요한 정보가 contexts 안에 충분히 들어 있었는지."""


class JudgeResult(BaseModel):
    passed: bool = Field(description="expected_traits를 만족하고 forbidden을 어기지 않았는가")
    reasoning: str = Field(description="판단 근거 한 문장")
    faithfulness: float = Field(ge=0, le=1, description="답변이 contexts에 근거하는 정도")
    answer_relevancy: float = Field(ge=0, le=1, description="답변이 질문과 관련 있는 정도")
    context_precision: float = Field(ge=0, le=1, description="contexts 중 실제로 쓸모 있었던 비율")
    context_recall: float = Field(ge=0, le=1, description="답변에 필요한 정보가 contexts에 충분히 있었는지")


judge = judge_llm.with_structured_output(JudgeResult)


def load_queries() -> list[dict]:
    """test_queries.csv를 읽어 케이스별 딕셔너리 목록으로 돌려준다."""
    with open(_QUERIES_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_one(row: dict) -> dict:
    """케이스 한 건을 에이전트에 실행하고, LLM 심사로 통과 여부와 RAGAS 스타일 지표를 함께 매긴다."""
    result = agent.invoke({"messages": [{"role": "user", "content": row["input"]}]})
    messages = result["messages"]
    answer = get_text(messages[-1])
    contexts = [m.content for m in messages if isinstance(m, ToolMessage)]

    # test_queries.csv는 여러 기준을 한 필드에 담을 때 실제 줄바꿈 대신 "\n" 문자열로 적어 두므로,
    # 심사 프롬프트에 넣기 전에 진짜 줄바꿈으로 풀어준다.
    traits = row["expected_traits"].replace("\\n", "\n")
    forbidden = row["forbidden"].replace("\\n", "\n")
    contexts_text = "\n---\n".join(contexts) if contexts else "(도구를 호출하지 않음)"

    verdict = judge.invoke(
        f"{RUBRIC}\n\n"
        f"카테고리: {row['category']}\n"
        f"질문: {row['input']}\n"
        f"기대 특성(expected_traits):\n{traits}\n"
        f"금지 사항(forbidden):\n{forbidden}\n"
        f"contexts(도구 호출 결과):\n{contexts_text}\n"
        f"에이전트 답변: {answer}"
    )
    return {
        "id": row["id"],
        "category": row["category"],
        "answer": answer,
        "passed": verdict.passed,
        "reasoning": verdict.reasoning,
        "faithfulness": verdict.faithfulness,
        "answer_relevancy": verdict.answer_relevancy,
        "context_precision": verdict.context_precision,
        "context_recall": verdict.context_recall,
        "error": False,
    }


def _avg(results: list[dict], key: str) -> float:
    """결과 목록에서 지표 key의 평균을 낸다."""
    return sum(r[key] for r in results) / len(results) if results else 0.0


def write_report(path: Path, round_name: str, results: list[dict]) -> None:
    """전체 통과율·카테고리별 통과율·RAGAS 스타일 평균 지표·케이스별 결과를 라운드 리포트로 저장한다.
    Bedrock 쿼터 등으로 아예 실행되지 못한 케이스(error=True)는 "실패"와 분리해서,
    통과율·평균 지표 집계에 넣지 않고 별도로 미실행 목록에만 표시한다.
    """
    errored = [r for r in results if r.get("error")]
    evaluated = [r for r in results if not r.get("error")]
    total = len(evaluated)
    passed = sum(1 for r in evaluated if r["passed"])
    failed = [r for r in evaluated if not r["passed"]]

    lines = [f"# {round_name} 자체 평가 결과", ""]
    if errored:
        lines.append(
            f"> 총 {len(results)}건 중 {len(errored)}건은 실행 자체가 안 돼서(주로 Bedrock 일일 토큰 한도) "
            "통과율·지표 집계에서 제외했습니다. 아래 수치는 실제로 실행된 케이스 기준입니다."
        )
        lines.append("")

    lines += ["## 통과율", f"- 실행된 케이스 기준: {passed} / {total} 통과 (전체 {len(results)}건 중 {len(errored)}건 미실행)", ""]

    lines += ["## 카테고리별 통과율 (실행된 케이스만)"]
    categories = sorted({r["category"] for r in evaluated})
    for cat in categories:
        cat_results = [r for r in evaluated if r["category"] == cat]
        cat_passed = sum(1 for r in cat_results if r["passed"])
        lines.append(f"- {cat}: {cat_passed} / {len(cat_results)} 통과")

    lines += ["", "## RAGAS 스타일 지표 (판단 LLM 채점 평균, 실행된 케이스만)"]
    lines.append(f"- faithfulness: {_avg(evaluated, 'faithfulness'):.2f}")
    lines.append(f"- answer_relevancy: {_avg(evaluated, 'answer_relevancy'):.2f}")
    lines.append(f"- context_precision: {_avg(evaluated, 'context_precision'):.2f}")
    lines.append(f"- context_recall: {_avg(evaluated, 'context_recall'):.2f}")

    lines += ["", "## 실패 케이스 요약 (정상 실행됐지만 기준 미충족)"]
    if failed:
        for r in failed:
            lines.append(f"- ({r['id']}) {r['category']} · {r['reasoning']}")
    else:
        lines.append("- 없음")

    if errored:
        lines += ["", "## 미실행 케이스 (쿼터 등 외부 오류로 실행 자체가 안 됨)"]
        for r in errored:
            lines.append(f"- ({r['id']}) {r['category']} · {r['reasoning']}")

    lines += ["", "## 케이스별 결과"]
    for r in results:
        if r.get("error"):
            lines.append(f"- [미실행] ({r['id']}) {r['category']} · {r['reasoning']}")
            continue
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(
            f"- [{mark}] ({r['id']}) {r['category']} · {r['reasoning']} "
            f"(F={r['faithfulness']:.2f} AR={r['answer_relevancy']:.2f} "
            f"CP={r['context_precision']:.2f} CR={r['context_recall']:.2f})"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed} / {total} 통과 (미실행 {len(errored)}건 제외) -> {path}")


if __name__ == "__main__":
    round_arg = sys.argv[1] if len(sys.argv) > 1 else "round1"
    queries = load_queries()
    out_path = Path(__file__).resolve().parent / f"{round_arg}_report.md"
    round_label = "1차 (Day 9 종료)" if round_arg == "round1" else "2차 (Day 10 개선 후)"

    results = []
    for i, row in enumerate(queries, start=1):
        print(f"[{i}/{len(queries)}] id={row['id']} category={row['category']} 실행 중...")
        try:
            results.append(run_one(row))
        except Exception as e:
            # 중간에 실패해도(예: Bedrock 쿼터) 여기까지의 결과는 보고서로 남긴다.
            print(f"  실패: {e}")
            results.append({
                "id": row["id"], "category": row["category"], "answer": "",
                "passed": False, "reasoning": f"실행 실패: {e}",
                "faithfulness": 0.0, "answer_relevancy": 0.0,
                "context_precision": 0.0, "context_recall": 0.0,
                "error": True,
            })
        write_report(out_path, round_label, results)  # 매 케이스마다 갱신해 중간 결과를 보존한다
