"""국가 메타데이터 RAG 파이프라인: Bedrock 임베딩 + Chroma 벡터 검색."""

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.tools import tool

from country_data import load_countries

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


@tool
def search_country_notes(query: str, k: int = 3) -> str:
    """국가별 안전 정보·비자·여행 팁 노트를 의미 검색으로 찾아 근거와 함께 돌려준다.
    "치안이 안전한 나라", "무비자로 갈 수 있는 곳" 처럼 정형 조건으로 딱 떨어지지 않는
    자유 질문에 답할 때 사용한다. 검색 결과가 없으면 그 사실을 그대로 안내한다.
    """
    try:
        db = _get_db()
    except Exception as e:
        return f"국가 노트 검색을 사용할 수 없습니다 (임베딩 서비스 연결 실패: {e})."

    hits = db.similarity_search(query, k=k)
    if not hits:
        return "관련된 국가 노트를 찾지 못했습니다."

    lines = [f"- [{d.metadata['country']} {d.metadata['city']}] {d.page_content}" for d in hits]
    return "\n".join(lines)
