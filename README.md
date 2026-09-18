# 미니 PJT: 해외여행플래너

## 무엇을 푸나
예산·동반인·여행 목적만 입력하면 AI가 국가를 추천(또는 직접 탐색)하고, 선택한 국가 기준 Day별 코스와 예산까지 자동으로 완성해주는 해외여행 플래닝 서비스.

## 이번 제출 범위 (우선순위)
도구가 여러 개라 우선순위를 나눠서 관리했다. **국가 후보는 이미 큐레이션해 둔 인기 국가 목록 안에서 고르는 정도로 두고, 핵심은 그 안에서의 "장소 검증"과 "코스 생성" 품질이다.**
- **P0 (핵심)**: 코스 생성(`tools.py`의 `list_candidate_places`로 검증된 장소만 사용해 LLM이 초안 작성) + 장소 검증(`verify_place`)
- **P0 (지원, 가벼운 수준)**: 인기 국가 목록 안에서의 예산/목적 필터링(`score_countries`), 동반인 프로필 기반 일정 보정, 찜 장소 반영
- **P1 (시간 허락 시)**: 동선 최적화(`optimize_route`) — 이미 구현·테스트는 해뒀지만, 장소 검증·코스 생성이 부실해지면서까지 우선하지 않는다
- **보조**: 구글맵 연동 표시, 계절 적합도 안내, 예산 시뮬레이션

## 빌드 체크리스트 (12개 패턴) 반영 현황
과제 채점 기준의 12개 패턴 중 필수 4개(1·3·11·12)를 포함해 아래 항목을 반영했다. 표에 없는 항목(MCP·HITL·Multi-Agent Supervisor·Plan-Execute·장기 메모리)은 이 서비스 규모에서 굳이 넣을 필요가 없다고 판단해 의도적으로 제외했다(자세한 사유는 각 항목 참고).

| # | 패턴 | 상태 | 어디에 |
|---|---|---|---|
| 1 | LCEL + 구조화 출력 (필수) | ✅ | `src/intake.py`의 `parse_trip_intent`/`aparse_trip_intent`가 `with_structured_output(TripIntent)`로 사용자 자유 텍스트를 예산·기간·동반인·목적·시기·목적지로 구조화하고, `src/api.py`가 이를 `/query` 응답의 `intent` 필드에 그대로 실어 반환한다. (참고: `evaluation/run_eval.py`의 LLM-judge도 `JudgeResult`로 같은 패턴을 쓰지만, 그건 평가 스크립트일 뿐 서비스 자체는 아니라서 이번에 core에도 넣었다.) |
| 2 | ReAct (도구 자율 선택) | ✅ | `src/agent.py`의 `create_agent` — 시스템 프롬프트 기준으로 매 턴 어떤 도구를 부를지 모델이 자율 판단 |
| 3 | RAG + 쿼리 확장 (필수) | ✅ | `src/retriever.py`의 `_expand_query`가 원래 질문과 같은 의도의 검색어 2개를 LLM으로 더 만들어(`_expand_chain.with_structured_output`) 함께 검색하고, slug 기준으로 중복 제거해 상위 k개를 돌려준다. 하이브리드 검색·리랭킹까지는 넣지 않았다(11개 문서뿐인 코퍼스 규모상 비용 대비 효과가 낮다고 판단) |
| 4 | 도구 다중 | ✅ | `src/tools.py` 6개(DB 조회형 4개, 계산기형 2개) + `src/retriever.py`의 `search_country_notes` = 총 7개, 전부 단일 에이전트에 바인딩. 한 질의에 2~4개를 자율 결합하는 경우가 실제 트레이스에서 흔히 나온다 |
| 5 | MCP 서버 연동 | 제외 | 구글 플레이스는 REST 직접 호출/로컬 큐레이션으로 대체. 사내 시스템처럼 MCP로 노출할 만한 별도 서버가 이 프로젝트엔 없다 |
| 6 | 가드레일 (PII·인젝션) | ✅ | `src/guardrails.py` — PII는 `PiiGuardrailMiddleware`가 모델 호출 전에 즉시 차단(입력 측), 인젝션은 `InjectionLogMiddleware`가 SERVICE.md 정책대로 차단 없이 감사 로그만 남김, `DataDisclosureMiddleware`가 출력 측에서 데이터 고지 문구 누락을 보정 |
| 7 | HITL (위험 작업 승인) | 제외 | 이 서비스엔 실제 결제·예약처럼 되돌리기 어려운 위험 작업이 없어 승인 게이트가 필요한 지점 자체가 없다 |
| 8 | 미들웨어 (요약·마스킹·재시도) | ✅ | 미들웨어 3종(위 6번) + `src/llm.py`의 `ResilientChatBedrock`이 쓰로틀링 시 모델을 순서대로 전환하는 재시도 로직(미들웨어 계층은 아니고 커스텀 `BaseChatModel` 래퍼) |
| 9 | Multi-Agent Supervisor | 제외 | 현재 규모(단일 도메인, 7개 도구)에서는 역할을 나눌 서브 에이전트가 필요한 복잡도가 아니라고 판단해 단일 ReAct 에이전트로 충분하다고 봤다 |
| 10 | Plan-Execute · 장기 메모리 | 제외 | 코스 생성이 "계획 후 실행"을 분리할 만큼 다단계가 아니고, `api.py`의 `history`는 클라이언트가 매 요청마다 실어 보내는 요청 단위 단기 메모리라 서버 측 영속 저장(LangGraph Store 등)까지는 필요하지 않다고 판단 |
| 11 | Observability · Trace (필수) | ✅ | `.env`에 `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`(smith.langchain.com 무료 발급)를 채우면 LangChain이 모든 실행을 LangSmith에 자동 기록한다(코드 변경 없음, `requirements.txt`에 `langsmith` 명시). `/query` 응답의 `trace` 필드는 별개로, 요청 하나 안에서 호출된 도구만 보여주는 자체 제작 리스트다 |
| 12 | 평가 (RAGAS · LLM-as-Judge) (필수) | ✅ | `evaluation/run_eval.py`(LLM-judge, RAGAS 스타일 4지표) + `evaluation/grade_queries.py`(규칙 기반 도구 호출/forbidden 채점) |

필수 4개(1·3·11·12) 전부 충족, 권장 6개 이상도 2·4·6·8을 더해 총 8개로 충족.

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
1. 이 프로젝트 루트에 `.env` 파일을 만들고 AWS 자격 증명을 넣어야 합니다 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) — Bedrock 모델·임베딩 호출용. `.gitignore`에 이미 포함돼 있어 커밋되지 않습니다. `GOOGLE_MAPS_API_KEY`는 선택 사항(없으면 로컬 큐레이션 장소 데이터로 검증). `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`(smith.langchain.com에서 무료 발급) + `LANGCHAIN_PROJECT`를 채우면 모든 에이전트 실행이 LangSmith에 자동으로 트레이싱됩니다 — 비워두면 트레이싱 없이 평소대로 동작합니다(코드 변경 없이 LangChain이 환경변수만 보고 자동으로 켜고 끕니다).
2. `pip install -r requirements.txt`
3. CLI 데모: `./run.sh` (내부적으로 `cd src && python agent.py`)
4. API 서버: `./run.sh api` → `POST http://localhost:8000/query` `{"question": "..."}` → `{answer, contexts, trace}`(제출 규약 필수 3키) `+ intent`(추가 필드, 구조화 파싱 결과 — 필수 3키는 그대로 유지되고 그 위에 덧붙인 것)
5. 웹 채팅 데모: 4번으로 API 서버를 켠 상태에서 `web/index.html`을 브라우저로 직접 열면(더블클릭 또는 `file://` 경로) 채팅 UI로 에이전트와 바로 대화할 수 있습니다. 별도 빌드·서버 없이 정적 HTML 하나로 동작하며, API 서버가 꺼져 있으면 상단 상태 표시가 "연결할 수 없음"으로 바뀝니다.
6. 평가(LLM-judge, RAGAS 지표): `cd evaluation && python run_eval.py round1` (또는 `round2`) → `round*_report.md` 갱신
7. 평가(규칙 기반 자동 채점): `cd evaluation && python grade_queries.py` → 케이스별로 에이전트를 실제 실행해 도구 호출·forbidden 문구를 결정적으로 채점하고 `grading_report.md` 생성
8. 단위 테스트(Bedrock 호출 없음, 무료·즉시): `pytest tests/`

## RAGAS 평가 결과
이 프로젝트는 순수 RAG QA가 아니라 도구 호출형 에이전트라 `ragas` 패키지(RAGAS는 이 레포의 공용 `.venv`에 설치하면 다른 Day 실습과 의존성이 꼬일 위험이 있어 설치하지 않음)를 그대로 쓰는 대신, `evaluation/run_eval.py`의 LLM-judge가 RAGAS와 같은 4개 지표 정의(faithfulness/answer_relevancy/context_precision/context_recall)를 매 케이스마다 채점하도록 구현했습니다. contexts는 실행 중 호출된 도구(list_candidate_places, score_countries 등)의 결과를 그대로 사용합니다.

**(구버전 기록, Day 9~10 · 20건 테스트셋 기준)**
- 1차 (Day 9, 20건 중 2건만 실행됨 — 나머지는 Bedrock 쿼터 초과로 미실행): faithfulness 0.97 · answer_relevancy 0.97 · context_precision 1.00 · context_recall 1.00
- 2차 (Day 10 개선 후, 20건 전체 실행): faithfulness 0.98 · answer_relevancy 0.96 · context_precision 0.94 · context_recall 0.94

**현재 (SERVICE.md 기준 12건 테스트셋 재실행)** — `test_queries.csv`를 컬럼(id/category/input/expected_traits/forbidden/expected_tools/note) 기준 12건(positive 5·negative 2·edge 3·guardrail 2)으로 재구성한 뒤, 이미 회고 과정에서 수정이 끝난 현재 에이전트 코드로 round1·round2를 다시 실행했다. 새 코드베이스 기준이라 두 라운드 모두 통과율·지표가 거의 동일하게 나왔다(아래 "테스트 세트 통과율" 참고).
- round1: faithfulness 0.98 · answer_relevancy 0.97 · context_precision 0.99 · context_recall 1.00
- round2: faithfulness 0.97 · answer_relevancy 0.96 · context_precision 1.00 · context_recall 1.00

## 테스트 세트 통과율 (자체 평가)
**(구버전 기록)** `test_queries.csv` 20건(당시 기준) · positive 8(40%) · negative 4(20%) · edge 5(25%) · guardrail 3(15%)
- 1차 (Day 9 종료): **13 / 20 통과 (65%)**
- 2차 (Day 10 개선 후): **18 / 20 통과 (90%)** — SERVICE.md 목표치(90%) 달성
- 개선폭: +5건 (아래 회고 참고)

**추가 검증(round2 이후)**: "가족+아동" 위주로만 테스트돼 있어 커플·효도여행 등 다른 동반인 유형에도 실제로 차별화된 동작(안전도 가중치, 저강도 일정 등)이 적용되는지가 빠져 있었다. `score_countries`에 효도여행(부모님/어르신) 감지·가중치를 추가하고, 테스트셋에 21번(효도여행)·22번(커플) 케이스를 새로 추가해 22건으로 확장했다 (positive 10·negative 4·edge 5·guardrail 3, 45/18/23/14%).
- 21번(효도여행): 첫 실행에 바로 PASS (F=1.00 AR=1.00 CP=1.00 CR=1.00) — 낮잠 대신 "무리한 이동 최소화, 고강도 액티비티 제외, 오후 휴식"으로 정확히 반영됨.
- 22번(커플): 첫 실행은 FAIL — 자세한 내용은 아래 회고 참고. 원인 수정 후 재실행해 PASS (F=1.00 AR=1.00 CP=1.00 CR=1.00).

**테스트셋 재구성 + 현재 통과율**: 위 20건/22건 버전은 이후 `test_queries.csv`를 SERVICE.md 기준 12건(positive 5·negative 2·edge 3·guardrail 2)으로 다시 간추리면서 케이스 구성이 바뀌었다. 위 1·2차 통과율(65%→90%)과 RAGAS 수치는 **그 이전 버전 파일 기준의 기록**이며, 케이스 ID·문구가 달라져 지금의 `test_queries.csv`와 1:1로 대응하지 않는다.

새 12건 세트에 대해 LLM-judge(`run_eval.py`)로 round1·round2를 다시 실행한 결과는 **round1 12/12(100%) · round2 12/12(100%)**로 동일하게 나왔다 ([`round1_report.md`](evaluation/round1_report.md), [`round2_report.md`](evaluation/round2_report.md)). 이번에는 두 라운드 사이에 코드 변경이 없었기 때문인데(round1을 만드는 시점에 이미 `grade_queries.py` 채점 사이클에서 발견한 버그들이 전부 수정되어 있었다), 1차→2차 "개선폭"을 보여주는 실험이라기보다는 **같은 안정된 코드에 대해 재현성을 확인**한 것에 가깝다. 실제 버그 발견→수정 과정은 위 20건/22건 회고와, 아래 `grade_queries.py` 절의 예산 검증 버그 사례에 기록돼 있다.

## 규칙 기반 자동 채점 (`grade_queries.py`)
`run_eval.py`의 LLM-judge와는 별도로, 사람 판단 없이도 재현 가능한 채점이 필요해 결정적 규칙 기반 채점 스크립트를 추가했다. 케이스마다 에이전트를 실제로 실행해:
- `expected_tools`가 있으면 실행 트레이스(`AIMessage.tool_calls`)에 해당 도구가 실제로 호출됐는지 확인하고,
- `forbidden` 문구(세미콜론 구분)가 최종 답변에 그대로 등장하면 그 자리에서 실패로 처리하며,
- `expected_traits`는 자동 채점하지 않고 답변 전문과 나란히 `grading_report.md`에 남겨 사람이 확인하도록 한다.

**결과: 12 / 12 통과 (100%)** — positive 5/5, negative 2/2, edge 3/3, guardrail 2/2. 상세는 [`evaluation/grading_report.md`](evaluation/grading_report.md) 참고.

이 100%는 처음부터 나온 값이 아니다. 최초 실행은 8/12(67%)였고, 실패 4건을 분석해 두 가지 다른 성격의 문제를 구분했다:
- **테스트 설계가 과도하게 프리스크립티브했던 3건(5·6·10번)**: 에이전트의 실제 답변 내용은 옳았지만(예: 아틀란티스처럼 명백히 가상 국가는 도구 호출 없이 바로 거절, 장소 하나만 물었으면 `verify_place`만 호출) `expected_tools`가 특정 도구 호출 "경로"까지 못박아 놓아 실패로 잡혔다. 결과가 맞다면 경로는 여러 개일 수 있다는 판단하에 `expected_tools`를 실제로 정당한 동작에 맞게 완화했다.
- **진짜 버그였던 1건(9번, 예산 -50만원)**: 에이전트가 음수 예산을 지적하지 않고 다른 조건만 되묻는 실제 결함이었다. `score_countries`에 `budget_krw <= 0` 방어 로직과 회귀 단위 테스트를 추가하고, 시스템 프롬프트에도 "잘못된 예산은 되묻기 전에 먼저 지적" 규칙을 넣어 수정했다. 수정 후에도 에이전트는 도구를 부르지 않고 스스로 판단해 거절하므로, 9번의 `expected_tools`도 결과 기준으로 완화했다.

## 트라이앤에러 회고
**시도했지만 실패한 접근**
- 1차 평가를 처음 돌렸을 때 계정의 Bedrock 일일 토큰 한도(공유 교육 계정)에 걸려 20건 중 2건만 실행되고 나머지는 전부 `ThrottlingException`으로 죽었다. 재시도 로직 없이 단일 모델만 쓰는 구조라 한도가 풀릴 때까지 사실상 평가를 진행할 수 없었다.

**최종 채택한 접근**
- `src/llm.py`에 `ResilientChatBedrock`을 만들어, Sonnet 4.5/4.6 → Haiku → Nova 순으로 모델 목록을 두고 `ThrottlingException` 등 일시 오류가 나면 다음 모델로 자동 전환하도록 했다. `create_agent`가 요구하는 `BaseChatModel` 인터페이스(`bind_tools`, `_generate`)를 직접 구현해서 에이전트와 LLM-judge 양쪽에 그대로 끼워 넣었다. 실제로 1차 재시도 때 Sonnet 4.5(us/global)·4.6(us)이 모두 막혀 있었는데 4번째 모델로 자동 전환되어 20건 전체를 완주할 수 있었다.
- 1차 결과(65%)를 분석해 보니 진짜 버그 2개와 테스트 설계 문제 1개가 섞여 있었다:
  1. (진짜 버그) 금액을 "560,000원"처럼 콤마로 표기하니 LLM이 자릿수를 잘못 읽어 "560만원"이라고 10배 틀리게 말한 사례 발견 → `tools.py`에 `_format_krw()`를 추가해 모든 금액을 "56만원"처럼 만원 단위로 통일
  2. (진짜 버그) "미식 목적 국가만"이라고 했는데 관련 없는 국가를 자체 판단으로 끼워 넣은 사례 발견 → 시스템 프롬프트에 "score_countries가 준 국가만 쓰고 임의로 추가하지 않는다"를 명시
  3. (테스트 설계 문제) "이 코스", "이 식당"처럼 이전 대화가 있다고 가정한 테스트 케이스 5건이, 대화 기록 없이 한 번만 묻는 평가 방식과 맞지 않아 에이전트가 (합리적으로) 되묻다가 실패 처리됨 → 목적지를 질문에 직접 포함시켜 단일 질문으로도 자기완결되게 재작성

**추가 발견(companion 다양화 검증 중)**
- "서비스가 가족+아동 케이스만 검증돼 있고 커플·효도여행 등은 실제로 반영되는지 확인 안 됐다"는 지적을 받고 다시 보니, `score_countries`의 동반인 가중치가 "아동 있음/없음" 이분법뿐이었다(커플·효도여행·친구가 전부 동일 취급). `has_senior`(부모님/어르신 키워드) 분기를 추가하고 시스템 프롬프트에 효도여행/커플별 지침을 넣은 뒤, 테스트셋에 21·22번을 추가해 실제로 검증했다.
- 22번(커플, 태국 방콕 2박3일)을 처음 돌렸더니 FAIL: 방콕 큐레이션 장소가 4곳뿐인데 2박3일 슬롯(6~9개)을 채우려니 "루프탑 바", "크루즈 디너" 같은 검증 안 된 장소를 지어냈다. 커플이라서 생긴 문제가 아니라, **여행 일수 대비 큐레이션 장소 수가 부족하면 어떤 케이스든 지어낼 수 있다**는 더 일반적인 문제였다. → (1) `data/places/thailand_bangkok.json`에 실제 장소 4곳(왕궁·왓포·카오산로드·시암파라곤)을 추가해 8곳으로 확대, (2) 시스템 프롬프트에 "슬롯을 다 못 채우면 지어내지 말고 '자유 시간'으로 비워두고 부족하다고 알린다"는 명시적 폴백 규칙 추가. 재실행 결과 PASS(F=1.00 AR=1.00 CP=1.00 CR=1.00).

**웹 채팅 데모(`web/index.html`)로 실사용 테스트 중 발견한 버그**
- **멀티턴 대화 기억 상실**: 실제로 브라우저에서 "예산 100만원, 친구 셋, 11월, 미식&쇼핑 국가 추천" → "대만으로 갈게, 코스 짜줘"처럼 이어서 대화해 보니, 이미 알려준 예산·기간·동반인을 계속 다시 물어보는 문제를 발견했다. 원인은 `api.py`가 매 요청마다 `question` 하나만 담아 에이전트를 호출해 매번 새 대화로 취급했기 때문(이전 턴이 전혀 전달되지 않음). `Query`에 `history` 필드를 추가하고 `build_messages()`로 이전 턴+새 질문을 이어붙이도록 고쳤고, `web/index.html`도 턴마다 `history` 배열에 쌓아 함께 전송하도록 수정했다. 2턴 대화로 재검증해 이전 조건을 다시 묻지 않고 바로 코스를 생성하는 것을 확인했다.
- **항공료·숙박비 누락으로 인한 비현실적 예산**: "인당 100만원, 친구 셋, 대만"으로 코스를 받은 뒤 "예산에 비행기랑 숙소비용 포함이야?"라고 물었더니, 에이전트가 "포함돼 있다"면서 항공료 8~12만원처럼 터무니없이 낮은 항목별 금액을 답했다. 원인을 보니 `estimate_budget`/`score_countries`가 계산하는 총비용이 `avg_daily_cost_krw`(현지 체류비만) × 일수뿐이었고, 애초에 항공료 데이터 자체가 없었다 — 게다가 그 질문에 답할 때 에이전트가 도구를 다시 부르지 않고 스스로 항목별 숫자를 지어낸 것도 별개의 사실 왜곡이었다. `data/countries.json`에 국가별 왕복 항공료 평균치(`round_trip_flight_krw`)를 추가하고, `estimate_budget`에 "항공료(왕복)"을 별도 항목으로 넣어 총비용에 항상 합산하도록 했다. `score_countries`의 예산 필터링에도 항공료를 반영해, 이제 예산이 항공료를 감당 못 하면 애초에 후보에서 걸러진다. 시스템 프롬프트에도 "예산 항목 재질문에는 도구 결과를 그대로 인용하거나 다시 호출하고, 스스로 새 숫자를 만들지 않는다"를 명시했다.
- **구글맵 링크·별점이 답변에서 누락되는 경우**: 애초에 기획 단계에서 "구글 리뷰 기반으로 코스를 짜고, 실제 지도 링크와 별점을 보여달라"는 요구사항이 있었고 `list_candidate_places`/`verify_place` 도구는 항상 평점·리뷰수·구글맵 링크를 함께 돌려주도록 만들어져 있었다. 하지만 실사용 테스트 중 일부 답변(예: 타이베이 코스)에서 장소명만 나열되고 링크·별점이 빠지는 걸 발견했다 — 도구가 데이터는 주지만, 그걸 최종 답변에 항상 그대로 옮기라는 지시가 시스템 프롬프트에 없어서 LLM이 그때그때 임의로 생략한 것이었다. 시스템 프롬프트에 "언급하는 모든 장소는 `[장소명](구글맵 링크) · ⭐평점 (리뷰수건)` 형식으로 표기하고 생략하지 않는다"를 명시해 고쳤고, 같은 케이스(타이베이 2박3일)를 재실행해 모든 장소에 링크·별점이 일관되게 붙는 것을 확인했다.
- **장소 데이터 없음 안내가 프롬프트만으로는 신뢰할 수 없었던 문제**: 홍콩(장소 데이터 미보유 7개국 중 하나)으로 코스를 요청했을 때, 검증된 데이터가 없다는 안내를 답변 맨 앞이 아니라 맨 끝에 짧게만 언급하고, 심지어 실존하지 않는 조합(홍콩 일정에 싱가포르의 "오차드 로드"를 끼워 넣는 등)을 자신 있게 지어내는 사례를 발견했다. 같은 요청을 여러 번 재현해보니 어떤 실행은 안내를 맨 앞에 잘 붙이고, 어떤 실행은 아예 거절하고, 어떤 실행은 끝에만 붙이는 등 **모델 샘플링에 따라 프롬프트 준수 여부가 매번 달랐다** — 즉 프롬프트 지시만으로는 이 정책을 보장할 수 없다는 뜻이었다. PII 차단을 코드로 강제하는 것과 같은 방식으로, `guardrails.py`에 `DataDisclosureMiddleware`를 추가해 `list_candidate_places`가 "등록된 장소 데이터가 없습니다"를 돌려준 턴에서 최종 답변이 그 사실을 앞부분에 언급하지 않으면 코드가 강제로 경고 문구를 맨 앞에 붙이도록 했다(이전 턴의 무관한 판정에는 반응하지 않도록 이번 턴 메시지만 검사). 단위 테스트 4개로 로직을 고정했고, 실제 Bedrock 응답으로 "모델이 미묘하게 다른 표현("장소 데이터베이스가 없어서")을 써서 정규식이 못 잡을 뻔한" 경우까지 실제로 경고가 강제로 붙는 것을 확인했다. 다만 이 조치는 "안내 문구가 항상 앞에 온다"는 것만 보장할 뿐, 참고용 코스 본문 자체의 사실관계(오차드 로드 같은 착오)까지 막아주지는 않는다 — 이는 큐레이션 데이터가 없는 나라에 일반 지식으로 답하는 한 남는 근본적 한계다.

**남은 한계 · 향후 개선 방향**
- (8번 케이스, 아직 실패) "미식 목적 국가만" 요청에 일본·싱가포르를 포함하면서 "프리미엄 옵션이라 예산 여유 필요"라는 부연을 달았는데, 실제로는 둘 다 예산·목적 조건에 부합함에도 judge가 이 표현을 조건 위반으로 해석했다. 데이터·로직상 잘못은 아니고 표현 방식의 문제로 보여, 국가 목록을 부연설명 없이 동일한 형식으로만 제시하도록 프롬프트를 더 다듬을 여지가 있다.
- (14번 케이스) 1차에서는 통과, 2차에서는 실패로 같은 유형의 응답("정보가 부족해 되묻기")에 대해 judge 판정이 라운드마다 달랐다. 폴백 구조상 라운드마다 실제로 응답한 모델이 다를 수 있어(1차는 Sonnet, 2차는 다른 폴백 모델이었을 가능성), 심사 대상 자체의 미세한 표현 차이가 판정을 갈랐을 수 있다. 라운드 간 비교의 엄밀성을 높이려면, 폴백이 실제로 어떤 모델로 응답했는지도 케이스별로 리포트에 남기는 개선이 필요하다.
- RAG(`search_country_notes`)만 따로 떼어 실제 `ragas` 패키지로 채점하는 것은 v2 과제로 남긴다. 멀티턴 대화(웹 채팅에서 history를 주고받는 것)는 위 회고에서 다뤘듯 이미 구현·검증했지만, `test_queries.csv`/`grade_queries.py`는 아직 단일 턴 케이스만 다루므로 멀티턴 시나리오를 자동 평가에 포함시키는 것은 v2 과제다.
- **국가 추천(`data/countries.json`, 11곳)과 코스 생성용 장소 데이터(`data/places/`, 4곳: 베트남·태국·대만·미국 서부)의 커버리지가 다르다.** 나머지 7개국(일본·싱가포르·필리핀·말레이시아·인도네시아·괌·홍콩)은 국가로는 추천되지만, 코스를 요청하면 장소 데이터가 없다고 정직하게 안내된다(지어내지 않음). 22번 케이스(방콕 2박3일)에서 큐레이션 장소가 부족하면 지어내려는 경향을 발견한 만큼, 나머지 7개국의 장소 데이터를 확충하는 것이 v2 우선순위다.

## 핵심 코드 위치
- `src/agent.py` — 메인 에이전트 (`create_agent` + 시스템 프롬프트 + 가드레일 미들웨어 + 도구 목록)
- `src/llm.py` — Bedrock 모델 쓰로틀링 시 다음 모델로 자동 전환하는 `ResilientChatBedrock`
- `src/tools.py` — 도메인 도구 (P0: 장소 후보/검증, 코스 생성 보조 / P0 지원: 국가 필터링 / P1: 동선 최적화 / 보조: 계절 정보, 예산 추정)
- `src/retriever.py` — RAG 파이프라인 (Bedrock 임베딩 + Chroma, `search_country_notes` 도구, LLM 쿼리 확장 `_expand_query`)
- `src/intake.py` — 자유 텍스트 요청을 `TripIntent`(Pydantic)로 구조화하는 LCEL 체인 (`with_structured_output`)
- `src/guardrails.py` — 가드레일·정책 미들웨어 (개인정보 즉시 차단, 프롬프트 인젝션 감사 로그, 장소 데이터 없음 안내 강제)
- `src/country_data.py` — `data/countries.json`, `data/places/*.json` 로더
- `src/api.py` — `POST /query` API (`{answer, contexts, trace, intent}`)
- `evaluation/run_eval.py` — `test_queries.csv` 실행 + LLM-judge 채점 스크립트
- `evaluation/grade_queries.py` — `test_queries.csv` 실행 + 규칙 기반(도구 호출·forbidden) 채점 스크립트
- `tests/test_tools.py` — 도구·가드레일·미들웨어 결정적 로직 단위 테스트 (Bedrock 미호출, `pytest tests/`)