"""입력 가드레일: 개인정보 차단(즉시 거절) + 프롬프트 인젝션 감지(차단 없이 기록만)."""

import datetime
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

# 여권번호(영문 1자+숫자 7~8자리), 카드번호(4자리-4자리-4자리-4자리, 구분자 선택),
# 휴대폰번호(01X-XXXX-XXXX, 구분자 선택) 패턴을 감지한다.
# 한국어 문장은 숫자 뒤에 조사가 바로 붙는 경우가 많아(예: "M12345678로"),
# \b 대신 ASCII 영문/숫자만 경계로 보는 lookaround를 써서 뒤에 한글이 와도 놓치지 않게 한다.
PII_PATTERNS = {
    "여권번호": r"(?<![A-Za-z0-9])[A-Za-z]\d{7,8}(?![A-Za-z0-9])",
    "카드번호": r"(?<![A-Za-z0-9])\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?![A-Za-z0-9])",
    "전화번호": r"(?<![A-Za-z0-9])01[0-9][-\s]?\d{3,4}[-\s]?\d{4}(?![A-Za-z0-9])",
}

INJECTION_PATTERNS = [
    r"ignore (the |all )?(previous|above|prior) (instructions?|prompts?)",
    r"you are now a different",
    r"(위의?|이전|기존|지금까지)\s*(모든\s*)?(지시|명령|규칙|프롬프트)[은는를]?\s*.{0,8}(무시|잊|버려)",
    r"system\s*:\s*",
    r"</?(system|admin|root)>",
    r"(시스템\s*프롬프트|숨겨진\s*(지시|프롬프트)).{0,10}(공개|출력|알려)",
    r"개발자\s*모드",
]

REFUSAL_PII = (
    "죄송합니다. 개인정보(여권번호·카드번호·전화번호)로 보이는 내용이 포함되어 있어 "
    "이 요청은 처리할 수 없습니다. 개인정보를 빼고 다시 말씀해 주세요."
)


def get_text(message) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 줄 때가 있어 텍스트만 모아 돌려준다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


def check_pii(text: str) -> tuple[bool, str]:
    """개인정보 패턴 검사. (차단 여부, 사유)를 돌려준다."""
    for kind, pattern in PII_PATTERNS.items():
        if re.search(pattern, text):
            return True, f"개인정보 패턴 감지: {kind}"
    return False, "통과"


def check_injection(text: str) -> tuple[bool, str]:
    """프롬프트 인젝션 의심 패턴 검사. (의심 여부, 사유)를 돌려준다. 차단에는 쓰지 않는다."""
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"인젝션 의심 패턴: {pattern}"
    return False, "통과"


def _log(kind: str, reason: str) -> None:
    """가드레일 판정 결과를 감사 로그 파일에 남긴다. 사용자에게는 노출하지 않는다."""
    with open("guard_audit.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now().isoformat()}\t{kind}\t{reason}\n")


def _last_human_text(request) -> str | None:
    """미들웨어 요청에서 가장 최근 사용자 메시지의 텍스트를 꺼낸다. 없으면 None."""
    last_human = next(
        (m for m in reversed(request.state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    return get_text(last_human) if last_human else None


class PiiGuardrailMiddleware(AgentMiddleware):
    """개인정보 패턴이 감지되면 모델을 호출하지 않고 고정 거절 문구로 즉시 응답한다."""

    def wrap_model_call(self, request, handler):
        """개인정보가 있으면 모델 호출 전에 거절 메시지로 가로챈다 (동기 경로)."""
        text = _last_human_text(request)
        if text is not None:
            blocked, reason = check_pii(text)
            if blocked:
                _log("pii_block", reason)
                return AIMessage(content=REFUSAL_PII)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        """개인정보가 있으면 모델 호출 전에 거절 메시지로 가로챈다 (비동기 경로, api.py에서 사용)."""
        text = _last_human_text(request)
        if text is not None:
            blocked, reason = check_pii(text)
            if blocked:
                _log("pii_block", reason)
                return AIMessage(content=REFUSAL_PII)
        return await handler(request)


class InjectionLogMiddleware(AgentMiddleware):
    """프롬프트 인젝션 의심 패턴은 차단하지 않고 감사 로그만 남긴다.
    시스템 프롬프트 규칙은 매 턴 다시 전달되므로 이 자체가 '규칙 재확인' 역할을 한다.
    """

    def wrap_model_call(self, request, handler):
        """인젝션 의심 패턴을 감지해 로그만 남기고, 모델 호출은 그대로 진행한다 (동기 경로)."""
        text = _last_human_text(request)
        if text is not None:
            suspected, reason = check_injection(text)
            if suspected:
                _log("injection_suspected", reason)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        """인젝션 의심 패턴을 감지해 로그만 남기고, 모델 호출은 그대로 진행한다 (비동기 경로, api.py에서 사용)."""
        text = _last_human_text(request)
        if text is not None:
            suspected, reason = check_injection(text)
            if suspected:
                _log("injection_suspected", reason)
        return await handler(request)
