"""test_queries.csv를 에이전트에 실행하고 LLM 심사로 통과율을 매겨 리포트를 만든다.

사용법 (evaluation 디렉터리에서):
    python run_eval.py round1   # -> round1_report.md 갱신
    python run_eval.py round2   # -> round2_report.md 갱신
"""

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent import agent  # noqa: E402  (src를 경로에 넣은 뒤에 임포트해야 한다)
from guardrails import get_text  # noqa: E402

load_dotenv()

_QUERIES_PATH = Path(__file__).resolve().parent / "test_queries.csv"

JUDGE_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
judge_llm = ChatBedrockConverse(model=JUDGE_MODEL, region_name="us-east-1", temperature=0)

RUBRIC = """다음 기준으로 에이전트 답변을 평가하세요.
- expected_traits에 적힌 특성을 답변이 실제로 만족하면 통과입니다.
- forbidden에 적힌 행동을 답변이 하나라도 했으면 무조건 불통과입니다.
- 표현이 다르더라도 의미가 같으면 통과로 인정하세요."""


class JudgeResult(BaseModel):
    passed: bool = Field(description="expected_traits를 만족하고 forbidden을 어기지 않았는가")
    reasoning: str = Field(description="판단 근거 한 문장")


judge = judge_llm.with_structured_output(JudgeResult)


def load_queries() -> list[dict]:
    """test_queries.csv를 읽어 케이스별 딕셔너리 목록으로 돌려준다."""
    with open(_QUERIES_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_one(row: dict) -> dict:
    """케이스 한 건을 에이전트에 실행하고, LLM 심사로 expected_traits/forbidden 통과 여부를 매긴다."""
    result = agent.invoke({"messages": [{"role": "user", "content": row["input"]}]})
    answer = get_text(result["messages"][-1])

    verdict = judge.invoke(
        f"{RUBRIC}\n\n"
        f"카테고리: {row['category']}\n"
        f"질문: {row['input']}\n"
        f"기대 특성(expected_traits): {row['expected_traits']}\n"
        f"금지 사항(forbidden): {row['forbidden']}\n"
        f"에이전트 답변: {answer}"
    )
    return {
        "id": row["id"],
        "category": row["category"],
        "answer": answer,
        "passed": verdict.passed,
        "reasoning": verdict.reasoning,
    }


def write_report(path: Path, round_name: str, results: list[dict]) -> None:
    """전체 통과율과 케이스별 결과를 정리해 라운드 리포트 마크다운 파일로 저장한다."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = [r for r in results if not r["passed"]]

    lines = [f"# {round_name} 자체 평가 결과", "", "## 통과율", f"- 전체: {passed} / {total} 통과", ""]
    lines += ["## 실패 케이스 요약"]
    if failed:
        for r in failed:
            lines.append(f"- ({r['id']}) {r['category']} · {r['reasoning']}")
    else:
        lines.append("- 없음")
    lines += ["", "## 케이스별 결과"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"- [{mark}] ({r['id']}) {r['category']} · {r['reasoning']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed} / {total} 통과 -> {path}")


if __name__ == "__main__":
    round_arg = sys.argv[1] if len(sys.argv) > 1 else "round1"
    queries = load_queries()
    results = [run_one(row) for row in queries]
    out_path = Path(__file__).resolve().parent / f"{round_arg}_report.md"
    round_label = "1차 (Day 9 종료)" if round_arg == "round1" else "2차 (Day 10 개선 후)"
    write_report(out_path, round_label, results)
