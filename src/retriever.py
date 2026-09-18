"""국가 메타데이터 RAG 파이프라인: Bedrock 임베딩 + Chroma 벡터 검색 + LLM 쿼리 확장."""

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from country_data import load_countries
from llm import build_resilient_model

load_dotenv()

_PERSIST_DIR = str(Path(__file__).resolve().parent.parent / "chroma_db")
_COLLECTION_NAME = "country_notes"

_db = None  # 첫 호출 때만 임베딩을 만들어 지연 초기화한다 (임포트 시 네트워크 호출 방지)


def _build_documents() -> list[Document]:
    """국가별 안전/비자/팁 노트를 Chroma에 색인할 Document 목록으로 변환한다."""
    docs = []
    for country in load_countries():
        docs.append(
            Document(
                page_content=country["notes"],
                metadata={
                    "slug": country["slug"],
                    "country": country["country"],
                    "city": country["city"],
                },
            )
        )
    return docs


def _get_db():
    """Chroma 벡터 저장소를 첫 호출 때만 만들어 재사용한다(지연 초기화). 비어 있으면 국가 노트로 채운다."""
    global _db
    if _db is not None:
        return _db

    from langchain_aws import BedrockEmbeddings
    from langchain_chroma import Chroma

    embeddings = BedrockEmbeddings(model_id="amazon.titan-embed-text-v2:0", region_name="us-east-1")
    _db = Chroma(
        collection_name=_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=_PERSIST_DIR,
    )
    if _db._collection.count() == 0:
        _db.add_documents(_build_documents())
    return _db


class _ExpandedQueries(BaseModel):
    """원래 질문과 같은 의도를 담았지만 표현이 다른 검색어들."""

    queries: list[str] = Field(description="원래 질문과 같은 의도를 담은, 표현이 다른 검색어 2개")


_expand_chain = build_resilient_model(temperature=0).with_structured_output(_ExpandedQueries)


def _expand_query(query: str) -> list[str]:
    """원래 질문과 표현이 다른 검색어 2개를 LLM으로 더 만들어 함께 검색한다(쿼리 확장).
    사용자 문구가 노트 원문과 어휘가 달라 벡터 검색이 놓칠 수 있는 관련 문서를 넓게 찾기 위함이다.
    확장에 실패해도(쓰로틀링 등) 원래 질문만으로는 검색을 이어간다.
    """
    try:
        expanded = _expand_chain.invoke(
            [HumanMessage(content=f"다음 여행 관련 질문과 같은 의도를 담았지만 표현이 다른 검색어 2개를 만들어줘: {query}")]
        )
        return [query] + expanded.queries
    except Exception:
        return [query]


@tool
def search_country_notes(query: str, k: int = 3) -> str:
    """국가별 안전 정보·비자·여행 팁 노트를 의미 검색으로 찾아 근거와 함께 돌려준다.
    "치안이 안전한 나라", "무비자로 갈 수 있는 곳" 처럼 정형 조건으로 딱 떨어지지 않는
    자유 질문에 답할 때 사용한다. 원래 질문 외에 LLM이 만든 유사 검색어로도 함께 찾아
    (쿼리 확장) 어휘 차이로 놓치는 문서를 줄인다. 검색 결과가 없으면 그 사실을 그대로 안내한다.
    """
    try:
        db = _get_db()
    except Exception as e:
        return f"국가 노트 검색을 사용할 수 없습니다 (임베딩 서비스 연결 실패: {e})."

    seen_slugs: set[str] = set()
    hits = []
    for q in _expand_query(query):
        for d in db.similarity_search(q, k=k):
            if d.metadata["slug"] not in seen_slugs:
                seen_slugs.add(d.metadata["slug"])
                hits.append(d)
    hits = hits[:k]
    if not hits:
        return "관련된 국가 노트를 찾지 못했습니다."

    lines = [f"- [{d.metadata['country']} {d.metadata['city']}] {d.page_content}" for d in hits]
    return "\n".join(lines)
