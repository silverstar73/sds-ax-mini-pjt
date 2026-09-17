"""Bedrock 모델이 일시적으로 쓰로틀링·과부하에 걸리면 다음 모델로 자동 전환해 재시도하는 래퍼."""

from typing import Any, Optional

from botocore.exceptions import ClientError
from langchain_aws import ChatBedrockConverse
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

# 우선순위 순서. 맨 앞이 기본 모델이고, 그 모델이 막히면 뒤로 넘어간다.
FALLBACK_MODEL_IDS = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
]

# 이 코드에 해당하는 오류만 "일시적"이라고 보고 다음 모델로 넘어간다.
# 요청 자체가 잘못된 오류(예: ValidationException)까지 넘기면 버그를 숨기게 되므로 포함하지 않는다.
_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}


def _is_retryable(exc: Exception) -> bool:
    """예외가 다음 모델로 넘어가도 되는 일시적 오류인지 판단한다."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _RETRYABLE_ERROR_CODES:
            return True
    # langchain_aws가 botocore 오류를 감싸서 다시 던질 때도 있어 메시지로도 한 번 더 확인한다.
    text = str(exc)
    return any(code in text for code in _RETRYABLE_ERROR_CODES) or "Too many tokens" in text


class ResilientChatBedrock(BaseChatModel):
    """model_ids를 순서대로 시도하다가 쓰로틀링 등 일시 오류를 만나면 다음 모델로 자동 전환한다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # bind_tools()를 거치면 BaseChatModel이 아니라 RunnableBinding이 되므로 타입을 느슨하게 둔다.
    models: list[Any] = Field(default_factory=list)

    @classmethod
    def from_model_ids(
        cls, model_ids: Optional[list[str]] = None, **bedrock_kwargs: Any
    ) -> "ResilientChatBedrock":
        """model_ids(기본값 FALLBACK_MODEL_IDS) 각각으로 ChatBedrockConverse를 만들어 감싼다."""
        ids = model_ids or FALLBACK_MODEL_IDS
        models = [ChatBedrockConverse(model=model_id, **bedrock_kwargs) for model_id in ids]
        return cls(models=models)

    @property
    def _llm_type(self) -> str:
        return "resilient-bedrock-fallback"

    def bind_tools(self, tools, **kwargs):
        """내부 모델 전부에 동일하게 도구를 바인딩한, 새 ResilientChatBedrock을 돌려준다."""
        return ResilientChatBedrock(models=[m.bind_tools(tools, **kwargs) for m in self.models])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """첫 모델부터 순서대로 시도하고, 일시 오류면 다음 모델로, 아니면 그대로 예외를 올린다.
        bind_tools() 이후에는 모델이 BaseChatModel이 아니라 RunnableBinding이 되므로,
        둘 다에서 동작하는 공통 인터페이스인 invoke()로 호출한다.
        """
        last_exc: Optional[Exception] = None
        for i, model in enumerate(self.models):
            try:
                ai_message = model.invoke(messages, stop=stop, **kwargs)
                return ChatResult(generations=[ChatGeneration(message=ai_message)])
            except Exception as e:
                is_last = i == len(self.models) - 1
                if _is_retryable(e) and not is_last:
                    print(f"[llm] 모델 #{i} 일시 오류로 모델 #{i + 1}로 전환: {e}")
                    last_exc = e
                    continue
                raise
        raise last_exc  # pragma: no cover - models가 비어 있지 않은 한 도달하지 않는다


def build_resilient_model(**bedrock_kwargs: Any) -> ResilientChatBedrock:
    """FALLBACK_MODEL_IDS 순서로 쓰로틀링 대응 모델을 만든다. agent.py/run_eval.py에서 공통으로 쓴다."""
    return ResilientChatBedrock.from_model_ids(**bedrock_kwargs)
