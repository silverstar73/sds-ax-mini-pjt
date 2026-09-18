"""해외여행플래너 API: POST /query로 question을 받아 answer/contexts/trace를 돌려준다."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel

from agent import agent
from guardrails import get_text
from intake import aparse_trip_intent

api = FastAPI()

# web/index.html을 파일로 직접 열어(file:// 오리진) 로컬 API를 호출하는 데모용 설정이라 전체 허용한다.
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class HistoryTurn(BaseModel):
    role: str
    content: str


class Query(BaseModel):
    question: str
    history: list[HistoryTurn] = []


def build_messages(history: list[HistoryTurn], question: str) -> list[dict]:
    """history(이전 턴)에 새 question을 이어붙여 에이전트에 넘길 메시지 목록을 만든다.

    question만 담아 매번 새 대화로 취급하면, 이전에 알려준 예산·기간·동반인 같은 정보를
    에이전트가 기억하지 못해 같은 질문을 계속 반복하게 된다.
    """
    return [{"role": h.role, "content": h.content} for h in history] + [
        {"role": "user", "content": question}
    ]


@api.post("/query")
async def query(q: Query):
    """question과 history를 받아 에이전트를 실행하고, 답변·도구 결과(contexts)·도구 호출 이력(trace)·
    구조화 파싱 결과(intent)를 돌려준다.
    """
    intent = await aparse_trip_intent(q.question)
    result = await agent.ainvoke({"messages": build_messages(q.history, q.question)})
    messages = result["messages"]

    answer = get_text(messages[-1])
    contexts = [m.content for m in messages if isinstance(m, ToolMessage)]
    trace = [
        {"tool": call["name"], "args": call["args"]}
        for m in messages
        if isinstance(m, AIMessage)
        for call in (m.tool_calls or [])
    ]

    # media_type에 charset=utf-8을 명시한다. 없으면 일부 클라이언트가 한글을 잘못 해석한다.
    return JSONResponse(
        content={"answer": answer, "contexts": contexts, "trace": trace, "intent": intent.model_dump()},
        media_type="application/json; charset=utf-8",
    )


# 실행: uvicorn api:api --port 8000 (src 디렉터리에서)
# 테스트: Invoke-RestMethod -Uri http://localhost:8000/query -Method Post -ContentType "application/json" -Body '{"question": "예산 300만원, 성인 2 아동 1(6세), 3월에 휴양 목적으로 갈만한 나라 추천해줘"}'
