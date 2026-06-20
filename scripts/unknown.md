오케스트레이션 판단 기반 도구 호출 역할 에이전트는 Langchain을 쓴다. CrewAI도 써볼 기회를 찾는다.

역할 간 경계는 명세(그래프) + 상태스키마 충분
대규모운영 장애격리, 독립배포, 언어혼합이면 역할별 '서버'가 유리
PoC기반 빠른 반복, 디버깅, 완결성검증이면 IN-process 그래프 

비교기준정의, 항목추출, 차이분석 3가지 워크플로 단계에서의 Verify 검증기준은 스키마 충족, 전 대상 수렴, NotNull으로 산출물 판정원칙 + 비용절감 축
최종 결과요약에서만 LLM-as-judge로 acceptance(이전 기준 커버, 상태메모리로 출처 존재, 복기가능)평가
이유는 매 단계를 LLM으로 검증하면 비싸고, 최종만 검증하면 에러가 걷잡을 수 없음. 

memory는 단기checkpoint(state, rollback) = SQLiteSaver 장기store(History,User(사용자선호)) = InMemoryStore

LangGraph = 코드로 직접 짜서 돌리는 런타임 프레임워크(State･Node･Edge･Checkpoint･BuiltEngine)
빌드/호출 로직:
LangGraph / LangChain = pyPI패키지 라이브러리. 내 파이썬 프로세스 안에서
LLM = API 호출(HTTPS).LangChain의 chat modle(init_chat_model('anthropic:...'))로 API_key호출.
MCP server = stdio or HTTP(MultiServerMCPClient({...}))로 연결하면 런타임에 서버의 도구를 발견해 LangChain도구로 변환(awaitclient.get_tools()).MCP 서버 자체는 공개서버를 npx/uvx로 실행하거나 사용자가 mcp/FastMCP로 직접 작성해 함수를 도구로 노출

코딩 빌드 순서
1. pip install langgraph langchain langchain-mcp-adapters langgraph-checkpoint-sqlite
2. State(TypedDict) = AgentContext 정의
3. 노드 함수 작성: PLAN/OFFER/TOOL/MEMORY/Verify (state 받아 갱신 반환)
4. g=StateGraph(State) → add_node → add_edge/add_conditional_edges → entry/finish
5. checkpointer(SqliteSaver)+Store 부착
6. client=MultiServerMCPClient({...}) → tools=await client.get_tools() → TOOL 노드에 바인드
7. app=g.compile(checkpointer=...) → app.invoke(input, config={"thread_id":...})
8. 트레이싱=LangSmith(환경변수)

State = AgentContext 중요
from typing import TypedDict, Literal, Optional, Any
from typing_extensions import NotRequired

class PlanStep(TypedDict):
    step_id: str; subgoal: str; priority: int
    depends_on: list[str]; status: Literal["pending","running","done","failed"]

class Constraints(TypedDict):
    definition: dict[str, Any]      # 비교기준/대상 등 초기 정의
    allowed_tools: list[str]        # 최소권한 화이트리스트
    forbidden: list[str]            # 안전필터(rm -rf, DROP TABLE ...)
    acceptance: dict[str, Any]      # 완결성 기준

class HistoryEntry(TypedDict):
    t: str; actor: Literal["ORC","PLAN","OFFER","TOOL","MEMORY","Verify"]
    action: str; input_digest: str; result_digest: str
    status: Literal["ok","fail"]; cause: Optional[str]

class Budget(TypedDict):
    iter: int; max_iter: int; retry: int; consec_fail: int; fail_threshold: int

class Verdict(TypedDict):
    passed: bool; cause: Optional[str]; detail: NotRequired[str]

class AgentContext(TypedDict):
    goal: str; constraints: Constraints; plan: list[PlanStep]
    cursor: Optional[str]; artifacts: dict[str, Any]; scratch: dict[str, Any]
    history: list[HistoryEntry]; budget: Budget; verdict: Optional[Verdict]

노드 6개 + 행동 제약
state를 받아 고칠 부분만 딕셔너리로 반환 -> LangGraph가 반환을 state에 병합
- ORC = 순수 라우터, LLM 안씀, 다음 순서 노드만 규칙으로 결정(토큰 소비･예측가능성 보충)
- Plan = 목표를 step단위로 쪼갬
- Offer = 유일하게 매번 LLM 추론하는 노드, state에 따라 How?, What 도구 호출.
- TOOL 실제 실행(input/output). 여기만 MCP 경계 + 보안차단
- Memory = state 저장･체크포인트
- Verify = 수락기준 충족했나 평가
역할 침범 방지, 각 역할이 멋대로 끝났는지의 여부는 검증과 ORC의 몫?

라우팅 -- 고정 파이프라인과 다른 지점
route가 verify의 결정을 보고 다음 step을 정한다. 실패지점을 인식하고 가드레일을 세우는 것.
그런데 verify가 단계마다 검증을 하지만 마지막을 제외하고는 LLM 호출안함. 구조검증(스키마), 마지막 결과요약만 LLM으로 심판해서 오류 발생단계 추적 or 재실행 판단, 이유는 비용 최소화(중간단계에서 부터 수정하려면 과몰입되고 비용증가하고 문제가 있다면 계획부터 검열하는게 맞다고 판단)


비전 모델까지 만들어지고 난 후 /User/karla/cowork/의 파일과, ~/Documents/constgx/의 파일들을 
중요도 순으로 나누어 불필요한 3번에 해당하는 파일은 정리한다. 
1. 모델이 구동하는데 직접적으로 영향을 주는 장치적인 역할문서
2. 포트폴리오나 사용자가 학습 및 재학습을 위해서 저장을 요청한 문서
3. 그 외 문서(테스트, 참고문헌 등 필요한 내용은 추출해서 중요도 파일에 병합)

모듈이 "인프라"가 되려면
지금 orc/는 돌아가는 프로토타입이지 아직 인프라는 아닙니다. 인프라가 되려면 다섯 가지가 채워져야 합니다.
범용화 — 지금은 "모델 비교"라는 한 인스턴스에 묶여 있습니다. 오케스트레이터 자체는 도메인 무관이어야 하고, 비전 작업은 그 위에 올리는 하나의 인스턴스가 돼야 해요(goal·tools·acceptance만 갈아끼우면 되게). AgentContext 설계가 이미 그걸 가능케 합니다.
도구 평면(tool plane) 확장 — TOOL을 웹검색 하나에서, 비전/RAG/파인튜닝이 실제로 쓸 도구들로 넓힙니다: GCS 데이터 조회, 학습 잡 실행, 메트릭 수집, RAG 검색. 오케스트레이터는 이것들을 지휘합니다.
지속성 — in-memory(:memory: SqliteSaver/InMemoryStore) → 영속 백엔드(Postgres checkpointer 등). 그래야 실행이 중단돼도 재개되고, 무인 운영이 됩니다.
서비스 표면 + 관측성 — FastAPI 엔드포인트나 그 자체를 MCP 서버로 감싸 다른 것들이 호출하게. 여기에 운영 3축(HITL·안전필터 / 평가 / 비용·트레이싱)을 붙입니다.
배포 — 컨테이너화 + 상시 호스트. ← 여기서 COST-MODEL.md의 "상시 서버 = 시간당 과금"이 발동합니다.

PoC 직무에서 "실제 업무 워크플로에 대입 가능"하다는 신호는 배포된 제품이 아니라, 이런 오케스트레이터입니다: ①실제 여러 단계 작업을 실제 도구로 돌리고 ②실패·재시도·한도를 다루고 ③한 일을 들여다볼 수 있고(관측) ④다른 작업으로 바꿀 때 코드를 거의 안 고쳐도 되는 것. ①~③은 이미 프로토타입에 있습니다.