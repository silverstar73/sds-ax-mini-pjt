# 미니 PJT: 해외여행플래너

## 무엇을 푸나
예산·동반인·여행 목적만 입력하면 AI가 국가를 추천(또는 직접 탐색)하고, 선택한 국가 기준 Day별 코스와 예산까지 자동으로 완성해주는 해외여행 플래닝 서비스.

## 이번 제출 범위 (우선순위)
도구가 여러 개라 우선순위를 나눠서 관리했다. **국가 후보는 이미 큐레이션해 둔 인기 국가 목록 안에서 고르는 정도로 두고, 핵심은 그 안에서의 "장소 검증"과 "코스 생성" 품질이다.**
- **P0 (핵심)**: 코스 생성(`tools.py`의 `list_candidate_places`로 검증된 장소만 사용해 LLM이 초안 작성) + 장소 검증(`verify_place`)
- **P0 (지원, 가벼운 수준)**: 인기 국가 목록 안에서의 예산/목적 필터링(`score_countries`), 동반인 프로필 기반 일정 보정, 찜 장소 반영
- **P1 (시간 허락 시)**: 동선 최적화(`optimize_route`) — 이미 구현·테스트는 해뒀지만, 장소 검증·코스 생성이 부실해지면서까지 우선하지 않는다
- **보조**: 구글맵 연동 표시, 계절 적합도 안내, 예산 시뮬레이션

## 활용한 패턴 (Day 1~7)
- Day 1: 구조화된 출력 (Pydantic + `with_structured_output`) — `evaluation/run_eval.py`의 LLM-judge가 `JudgeResult` 스키마로 통과 여부를 판정
- Day 2: RAG — `src/retriever.py`에서 국가별 안전/비자/여행 팁 노트를 Bedrock 임베딩 + Chroma로 색인하고 `search_country_notes` 도구로 의미 검색
- Day 4: Tool use — `src/tools.py`에 `@tool`로 국가 스코어링·계절 정보·장소 후보 조회·장소 검증·동선 최적화·예산 추정 도구를 정의 (MCP는 미사용, 구글 플레이스는 REST 직접 호출/로컬 큐레이션 데이터로 대체)
- Day 5: 가드레일 — `src/guardrails.py`의 `AgentMiddleware`로 개인정보 패턴은 즉시 차단(`PiiGuardrailMiddleware`), 프롬프트 인젝션 의심은 SERVICE.md 정책대로 차단 없이 감사 로그만 남김(`InjectionLogMiddleware`)
- Day 5/6: `langchain.agents.create_agent` 기반 단일 ReAct 에이전트 — 국가추천·코스생성·장소검증·예산산정을 별도 그래프 노드로 나누지 않고, 한 에이전트가 상황에 맞는 도구를 골라 호출
- Day 7: LLM-as-judge 평가 — `evaluation/run_eval.py`가 `evaluation/test_queries.csv`를 실행해 `expected_traits`/`forbidden` 기준으로 통과율을 채점
- (MVP 제외) Day 3 커스텀 StateGraph, Day 6 멀티에이전트 supervisor, Day 7 Plan-and-Execute — 현재 규모에서는 단일 ReAct 에이전트로 충분하다고 판단해 v2로 미룸

## 아키텍처
```
[사용자 질문] (자연어)
   │
   ▼
[가드레일] PiiGuardrailMiddleware(개인정보 즉시 차단) → InjectionLogMiddleware(인젝션 의심 로그만)
   │
   ▼
[create_agent 단일 ReAct 에이전트] ── list_candidate_places / verify_place (P0, 장소 검증 — Google Places API 또는 로컬 큐레이션 데이터)
   │                              ├─ score_countries (P0 지원, 인기 국가 목록 안에서 예산 1차 필터 + 목적60%/동반인40%)
   │                              ├─ optimize_route (P1, 시간 허락 시에만 동선 최적화)
   │                              ├─ get_climate_info (보조, 건기/우기)
   │                              ├─ estimate_budget (보조, 예산 시뮬레이션)
   │                              └─ search_country_notes (보조, RAG 안전/비자/팁 자유 질문)
   ▼
[응답] 도구 결과에 근거한 한국어 답변
```

## 실행 방법
1. 레포 루트 `.env`에 AWS 자격 증명이 있어야 합니다 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) — Bedrock 모델·임베딩 호출용. `GOOGLE_MAPS_API_KEY`는 선택 사항(없으면 로컬 큐레이션 장소 데이터로 검증).
2. `pip install -r requirements.txt`
3. CLI 데모: `./run.sh` (내부적으로 `cd src && python agent.py`)
4. API 서버: `./run.sh api` → `POST http://localhost:8000/query` `{"question": "..."}` → `{answer, contexts, trace}`
5. 평가: `cd evaluation && python run_eval.py round1` (또는 `round2`) → `round*_report.md` 갱신

## RAGAS 평가 결과
이 프로젝트는 순수 RAG QA가 아니라 도구 호출형 에이전트라 RAGAS 지표(context_recall 등)가 그대로 들어맞지 않아, 대신 `evaluation/run_eval.py`의 LLM-as-judge로 `test_queries.csv` 기준 통과율을 측정했습니다 (아래 절 참고). RAG 파트(`search_country_notes`)만 따로 RAGAS로 채점하는 것은 v2 검토 사항입니다.
- context_recall: 미측정
- context_precision: 미측정
- faithfulness: 미측정
- answer_relevancy: 미측정

## 인-아웃 세트 통과율 (자체 평가)
- 1차 (Day 9 종료): XX / XX 통과
- 2차 (Day 10 개선 후): XX / XX 통과
- 개선폭: +XX 건 (주요 개선 사항: ...)

## 트라이앤에러 회고
- 시도했지만 실패한 접근 · 왜 실패했는가
- 최종 채택한 접근 · 왜 그것으로 갔는가
- 남은 한계 · 향후 개선 방향

## 핵심 코드 위치
- `src/agent.py` — 메인 에이전트 (`create_agent` + 시스템 프롬프트 + 가드레일 미들웨어 + 도구 목록)
- `src/tools.py` — 도메인 도구 (P0: 장소 후보/검증, 코스 생성 보조 / P0 지원: 국가 필터링 / P1: 동선 최적화 / 보조: 계절 정보, 예산 추정)
- `src/retriever.py` — RAG 파이프라인 (Bedrock 임베딩 + Chroma, `search_country_notes` 도구)
- `src/guardrails.py` — 입력 가드레일 미들웨어 (개인정보 차단, 프롬프트 인젝션 감사 로그)
- `src/country_data.py` — `data/countries.json`, `data/places/*.json` 로더
- `src/api.py` — `POST /query` API (`{answer, contexts, trace}`)
- `evaluation/run_eval.py` — `test_queries.csv` 실행 + LLM-judge 채점 스크립트