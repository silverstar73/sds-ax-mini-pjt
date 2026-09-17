"""해외여행플래너 API: POST /query로 question을 받아 answer/contexts/trace를 돌려준다."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel

from agent import agent
from guardrails import get_text

api = FastAPI()


class Query(BaseModel):
    question: str


@api.post("/query")
async def query(q: Query):
    """question을 받아 에이전트를 실행하고, 답변·도구 결과(contexts)·도구 호출 이력(trace)을 돌려준다."""
    result = await agent.ainvoke({"messages": [{"role": "user", "content": q.question}]})
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
        content={"answer": answer, "contexts": contexts, "trace": trace},
        media_type="application/json; charset=utf-8",
    )


# 실행: uvicorn api:api --port 8000 (src 디렉터리에서)
# 테스트: Invoke-RestMethod -Uri http://localhost:8000/query -Method Post -ContentType "application/json" -Body '{"question": "예산 300만원, 성인 2 아동 1(6세), 3월에 휴양 목적으로 갈만한 나라 추천해줘"}'
