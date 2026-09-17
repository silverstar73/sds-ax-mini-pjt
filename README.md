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
모델 호출 자체도 `src/llm.py`의 `ResilientChatBedrock`을 통해, Sonnet 4.5/4.6 → Haiku → Nova 순으로 쓰로틀링 시 자동 전환되도록 감싸져 있다 (agent/judge 공용).

## 실행 방법
1. 레포 루트 `.env`에 AWS 자격 증명이 있어야 합니다 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) — Bedrock 모델·임베딩 호출용. `GOOGLE_MAPS_API_KEY`는 선택 사항(없으면 로컬 큐레이션 장소 데이터로 검증).
2. `pip install -r requirements.txt`
3. CLI 데모: `./run.sh` (내부적으로 `cd src && python agent.py`)
4. API 서버: `./run.sh api` → `POST http://localhost:8000/query` `{"question": "..."}` → `{answer, contexts, trace}`
5. 평가: `cd evaluation && python run_eval.py round1` (또는 `round2`) → `round*_report.md` 갱신

## RAGAS 평가 결과
이 프로젝트는 순수 RAG QA가 아니라 도구 호출형 에이전트라 `ragas` 패키지(RAGAS는 이 레포의 공용 `.venv`에 설치하면 다른 Day 실습과 의존성이 꼬일 위험이 있어 설치하지 않음)를 그대로 쓰는 대신, `evaluation/run_eval.py`의 LLM-judge가 RAGAS와 같은 4개 지표 정의(faithfulness/answer_relevancy/context_precision/context_recall)를 매 케이스마다 채점하도록 구현했습니다. contexts는 실행 중 호출된 도구(list_candidate_places, score_countries 등)의 결과를 그대로 사용합니다.

- 1차 (Day 9, 20건 중 2건만 실행됨 — 나머지는 Bedrock 쿼터 초과로 미실행): faithfulness 0.97 · answer_relevancy 0.97 · context_precision 1.00 · context_recall 1.00
- 2차 (Day 10 개선 후, 20건 전체 실행): **faithfulness 0.98 · answer_relevancy 0.96 · context_precision 0.94 · context_recall 0.94**

## 테스트 세트 통과율 (자체 평가)
`test_queries.csv` 20건 · positive 8(40%) · negative 4(20%) · edge 5(25%) · guardrail 3(15%)
- 1차 (Day 9 종료): **13 / 20 통과 (65%)**
- 2차 (Day 10 개선 후): **18 / 20 통과 (90%)** — SERVICE.md 목표치(90%) 달성
- 개선폭: +5건 (아래 회고 참고)

## 트라이앤에러 회고
**시도했지만 실패한 접근**
- 1차 평가를 처음 돌렸을 때 계정의 Bedrock 일일 토큰 한도(공유 교육 계정)에 걸려 20건 중 2건만 실행되고 나머지는 전부 `ThrottlingException`으로 죽었다. 재시도 로직 없이 단일 모델만 쓰는 구조라 한도가 풀릴 때까지 사실상 평가를 진행할 수 없었다.

**최종 채택한 접근**
- `src/llm.py`에 `ResilientChatBedrock`을 만들어, Sonnet 4.5/4.6 → Haiku → Nova 순으로 모델 목록을 두고 `ThrottlingException` 등 일시 오류가 나면 다음 모델로 자동 전환하도록 했다. `create_agent`가 요구하는 `BaseChatModel` 인터페이스(`bind_tools`, `_generate`)를 직접 구현해서 에이전트와 LLM-judge 양쪽에 그대로 끼워 넣었다. 실제로 1차 재시도 때 Sonnet 4.5(us/global)·4.6(us)이 모두 막혀 있었는데 4번째 모델로 자동 전환되어 20건 전체를 완주할 수 있었다.
- 1차 결과(65%)를 분석해 보니 진짜 버그 2개와 테스트 설계 문제 1개가 섞여 있었다:
  1. (진짜 버그) 금액을 "560,000원"처럼 콤마로 표기하니 LLM이 자릿수를 잘못 읽어 "560만원"이라고 10배 틀리게 말한 사례 발견 → `tools.py`에 `_format_krw()`를 추가해 모든 금액을 "56만원"처럼 만원 단위로 통일
  2. (진짜 버그) "미식 목적 국가만"이라고 했는데 관련 없는 국가를 자체 판단으로 끼워 넣은 사례 발견 → 시스템 프롬프트에 "score_countries가 준 국가만 쓰고 임의로 추가하지 않는다"를 명시
  3. (테스트 설계 문제) "이 코스", "이 식당"처럼 이전 대화가 있다고 가정한 테스트 케이스 5건이, 대화 기록 없이 한 번만 묻는 평가 방식과 맞지 않아 에이전트가 (합리적으로) 되묻다가 실패 처리됨 → 목적지를 질문에 직접 포함시켜 단일 질문으로도 자기완결되게 재작성

**남은 한계 · 향후 개선 방향**
- (8번 케이스, 아직 실패) "미식 목적 국가만" 요청에 일본·싱가포르를 포함하면서 "프리미엄 옵션이라 예산 여유 필요"라는 부연을 달았는데, 실제로는 둘 다 예산·목적 조건에 부합함에도 judge가 이 표현을 조건 위반으로 해석했다. 데이터·로직상 잘못은 아니고 표현 방식의 문제로 보여, 국가 목록을 부연설명 없이 동일한 형식으로만 제시하도록 프롬프트를 더 다듬을 여지가 있다.
- (14번 케이스) 1차에서는 통과, 2차에서는 실패로 같은 유형의 응답("정보가 부족해 되묻기")에 대해 judge 판정이 라운드마다 달랐다. 폴백 구조상 라운드마다 실제로 응답한 모델이 다를 수 있어(1차는 Sonnet, 2차는 다른 폴백 모델이었을 가능성), 심사 대상 자체의 미세한 표현 차이가 판정을 갈랐을 수 있다. 라운드 간 비교의 엄밀성을 높이려면, 폴백이 실제로 어떤 모델로 응답했는지도 케이스별로 리포트에 남기는 개선이 필요하다.
- RAG(`search_country_notes`)만 따로 떼어 실제 `ragas` 패키지로 채점하는 것, "이미 갈 곳을 정했어요" 같은 멀티턴 시나리오를 대화 기록을 유지한 채 평가하는 것은 v2 과제로 남긴다.

## 핵심 코드 위치
- `src/agent.py` — 메인 에이전트 (`create_agent` + 시스템 프롬프트 + 가드레일 미들웨어 + 도구 목록)
- `src/llm.py` — Bedrock 모델 쓰로틀링 시 다음 모델로 자동 전환하는 `ResilientChatBedrock`
- `src/tools.py` — 도메인 도구 (P0: 장소 후보/검증, 코스 생성 보조 / P0 지원: 국가 필터링 / P1: 동선 최적화 / 보조: 계절 정보, 예산 추정)
- `src/retriever.py` — RAG 파이프라인 (Bedrock 임베딩 + Chroma, `search_country_notes` 도구)
- `src/guardrails.py` — 입력 가드레일 미들웨어 (개인정보 차단, 프롬프트 인젝션 감사 로그)
- `src/country_data.py` — `data/countries.json`, `data/places/*.json` 로더
- `src/api.py` — `POST /query` API (`{answer, contexts, trace}`)
- `evaluation/run_eval.py` — `test_queries.csv` 실행 + LLM-judge 채점 스크립트