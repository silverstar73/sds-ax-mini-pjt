"""사용자의 자유 텍스트 여행 요청을 구조화된 조건(TripIntent)으로 미리 파싱하는 LCEL 체인.

에이전트가 도구를 호출하기 전에 한 번 훑어보는 용도로, 에이전트 자신의 도구 호출 인자를
대신하거나 강제하지는 않는다. API 응답에 원문과 나란히 실어 사용자가 자신의 요청이 어떻게
해석됐는지 투명하게 확인할 수 있게 한다.
"""

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from llm import build_resilient_model

_INTAKE_PROMPT = (
    "다음은 해외여행플래너 서비스에 들어온 사용자 요청이다. 언급된 조건만 뽑아 구조화하라. "
    "요청에 없는 항목은 모르는 값(숫자는 0, 문자열은 빈 문자열)으로 둔다. 지어내지 않는다.\n\n"
    "요청: {question}"
)


class TripIntent(BaseModel):
    """자유 텍스트 여행 요청에서 뽑아낸 핵심 조건. 언급되지 않은 항목은 기본값(0/빈 문자열)이다."""

    budget_krw: int = Field(0, description="1인 총 여행 예산(원). 언급 없으면 0")
    days: int = Field(0, description="여행 일수. 언급 없으면 0")
    companions: str = Field("", description="동반인 구성 요약(예: '부모님 모시고 효도여행'). 언급 없으면 빈 문자열")
    purpose: str = Field("", description="여행 목적(예: '휴양, 미식'). 언급 없으면 빈 문자열")
    month: int = Field(0, description="여행 예정 월(1~12). 언급 없으면 0")
    preferred_country: str = Field("", description="사용자가 이미 정한 국가/도시. 없으면 빈 문자열")


_intake_chain = build_resilient_model(temperature=0).with_structured_output(TripIntent)


def parse_trip_intent(question: str) -> TripIntent:
    """사용자 질문 원문을 TripIntent로 구조화한다. 실패하면 전부 빈 값인 TripIntent를 돌려준다 (동기 경로, CLI에서 사용)."""
    try:
        return _intake_chain.invoke([HumanMessage(content=_INTAKE_PROMPT.format(question=question))])
    except Exception:
        return TripIntent()


async def aparse_trip_intent(question: str) -> TripIntent:
    """parse_trip_intent의 비동기 버전 (api.py에서 사용). 실패하면 전부 빈 값인 TripIntent를 돌려준다."""
    try:
        return await _intake_chain.ainvoke([HumanMessage(content=_INTAKE_PROMPT.format(question=question))])
    except Exception:
        return TripIntent()
