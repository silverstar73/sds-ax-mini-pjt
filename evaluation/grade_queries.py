"""test_queries.csv를 읽어 문항마다 에이전트를 실행하고 규칙 기반으로 채점한다.

채점 방식 (LLM 심사 없이 결정적으로 판정):
- expected_tools가 있으면, 나열된 도구를 실제로 전부 호출했는지 trace로 확인한다.
- forbidden 항목(세미콜론 구분)이 답변 텍스트에 그대로 들어 있으면 그 자리에서 실패로 본다.
- expected_traits는 자동 채점하지 않는다. 답변과 나란히 리포트에 남겨 사람이 확인한다.

사용법 (evaluation 디렉터리에서): python grade_queries.py
결과: 콘솔에 카테고리별/전체 통과율 출력 + evaluation/grading_report.md 저장.
"""

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent import agent  # noqa: E402  (src를 경로에 넣은 뒤에 임포트해야 한다)
from guardrails import get_text  # noqa: E402

load_dotenv()

_QUERIES_PATH = Path(__file__).resolve().parent / "test_queries.csv"
_REPORT_PATH = Path(__file__).resolve().parent / "grading_report.md"


def load_queries() -> list[dict]:
    """test_queries.csv를 읽어 케이스별 딕셔너리 목록으로 돌려준다."""
    with open(_QUERIES_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _split(field: str) -> list[str]:
    """세미콜론으로 구분된 필드를 항목 리스트로 나눈다. 빈 문자열이면 빈 리스트."""
    return [p.strip() for p in field.split(";") if p.strip()]


def grade_one(row: dict) -> dict:
    """케이스 한 건을 에이전트에 실행하고, expected_tools/forbidden을 규칙 기반으로 채점한다."""
    error = None
    answer = ""
    tools_called: list[str] = []

    try:
        result = agent.invoke({"messages": [{"role": "user", "content": row["input"]}]})
        messages = result["messages"]
        answer = get_text(messages[-1])
        tools_called = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage)
            for call in (m.tool_calls or [])
        ]
    except Exception as e:
        error = str(e)

    expected_tools = _split(row["expected_tools"])
    forbidden_items = _split(row["forbidden"])

    missing_tools = [t for t in expected_tools if t not in tools_called] if not error else expected_tools
    tool_check_passed = not missing_tools

    matched_forbidden = [f for f in forbidden_items if f in answer] if not error else []
    forbidden_check_passed = not matched_forbidden

    passed = (error is None) and tool_check_passed and forbidden_check_passed

    return {
        "id": row["id"],
        "category": row["category"],
        "input": row["input"],
        "expected_traits": row["expected_traits"],
        "expected_tools": expected_tools,
        "tools_called": tools_called,
        "missing_tools": missing_tools,
        "forbidden_items": forbidden_items,
        "matched_forbidden": matched_forbidden,
        "answer": answer,
        "error": error,
        "passed": passed,
    }


def print_summary(results: list[dict]) -> None:
    """카테고리별 통과율과 전체 통과율을 콘솔에 출력한다."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"전체 통과율: {passed} / {total} ({passed / total * 100:.0f}%)")

    categories = sorted({r["category"] for r in results})
    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        cat_passed = sum(1 for r in cat_results if r["passed"])
        print(f"  - {cat}: {cat_passed} / {len(cat_results)} ({cat_passed / len(cat_results) * 100:.0f}%)")


def write_report(path: Path, results: list[dict]) -> None:
    """카테고리별/전체 통과율과 케이스별 상세(도구 체크·forbidden 체크·사람 확인용 답변)를 파일로 저장한다."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    lines = ["# 규칙 기반 채점 결과", "", "## 통과율", f"- 전체: {passed} / {total} ({passed / total * 100:.0f}%)"]

    categories = sorted({r["category"] for r in results})
    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        cat_passed = sum(1 for r in cat_results if r["passed"])
        lines.append(f"- {cat}: {cat_passed} / {len(cat_results)} ({cat_passed / len(cat_results) * 100:.0f}%)")

    lines += ["", "## 케이스별 상세"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        lines += [
            "",
            f"### [{mark}] ({r['id']}) {r['category']}",
            f"- 질문: {r['input']}",
        ]
        if r["error"]:
            lines.append(f"- 실행 오류: {r['error']}")
            continue
        tool_mark = "OK" if not r["missing_tools"] else "FAIL"
        lines.append(
            f"- 도구 체크 [{tool_mark}]: 기대={r['expected_tools'] or '(없음)'} · "
            f"실제 호출={r['tools_called'] or '(없음)'} · 누락={r['missing_tools'] or '(없음)'}"
        )
        forbidden_mark = "OK" if not r["matched_forbidden"] else "FAIL"
        lines.append(
            f"- forbidden 체크 [{forbidden_mark}]: 검사 항목={r['forbidden_items'] or '(없음)'} · "
            f"답변에서 발견됨={r['matched_forbidden'] or '(없음)'}"
        )
        lines += [
            f"- expected_traits (사람이 확인): {r['expected_traits']}",
            f"- 실제 답변: {r['answer']}",
        ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n상세 리포트 저장: {path}")


if __name__ == "__main__":
    queries = load_queries()
    results = []
    for i, row in enumerate(queries, start=1):
        print(f"[{i}/{len(queries)}] id={row['id']} category={row['category']} 실행 중...")
        results.append(grade_one(row))

    print()
    print_summary(results)
    write_report(_REPORT_PATH, results)
