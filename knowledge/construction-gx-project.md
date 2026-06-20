# 건설GX 포트폴리오 프로젝트 — 설계 메모

> 작성 2026-06-14. 정본 설계 노트. 구현·다운로드가 진행되며 갱신한다.

## 1. 목적
- 건설GX 분야 취업을 목표로 한 **포트폴리오 프로젝트**.
- 데이터: AI Hub **'237.건설 현장 장비 모니터링 및 생산성 측정 데이터'** (datasetkey 71388, 약 414GB).
- 핵심 의도: 대용량 실데이터를 end-to-end로 다루고 여러 AI 기능을 통합해 **문제 구조화 능력과 구현의 깊이**를 드러내는 것.

## 2. 구현하고자 한 기능 (4종)
1. **멀티에이전트 오케스트레이션 (자동화 인프라)** — 오케스트레이션 에이전트가 MCP 서버로 요청 → MCP 서버가 도구 호출 → **자기검증 루프(self-verification)** 로 오류·병목을 개선. 데이터 다운로드와 **병렬로** 구축할 워크스트림.
2. **RAG**
3. **LLM 파인튜닝** — 비용 최소화, 가능한 범위까지만.
4. **PyTorch 이미지 인식 딥러닝(머신비전)** — **메인 기능**.

## 3. 기능별 구현 방향 (초안)
- **머신비전(메인)**: 건설자재·굴착기 이미지 객체탐지. 원천(이미지) + 라벨(어노테이션 JSON) 짝으로 supervised 학습.
- **멀티에이전트**: 오케스트레이터 → MCP → 도구 호출, self-verification loop로 자동화. 다운로드와 동시 진행.
- **RAG / 파인튜닝**: 라벨 JSON·문서(텍스트) 자원에 연결. 파인튜닝은 비용 최소가 제약.

## 4. 구현에 필요한 것 (리소스·전제)
- **데이터**: AI Hub 71388 (414GB). 집(한국 IP)에서 배치 다운로드 → GCS 버킷에 적재.
- **클라우드**: GCP (무료 체험 $300 / 90일). 저장 = GCS 버킷, 학습 = GPU VM(필요 시 생성 → 종료 후 삭제).
- **GPU**: 파인튜닝/학습용. ⚠ 무료 체험 계정은 GPU 할당량 기본 0 → 막히면 Colab 등 대안.
- **스택**: PyTorch, MCP, 오케스트레이션 프레임워크.

## 5. 데이터셋 특징 (파악 내용)
- 약 **414.13GB**, **거의 전부 원천(이미지)**. 라벨 전체 합쳐도 1GB 미만.
- **3종 데이터**: ① 건설자재(brick·scaffold·pvcPipe 등 20종, 객체탐지 이미지 — 용량 대부분: Training 원천 ~300GB, Validation 원천 ~68GB) ② 굴착기/입출입 이미지 ③ 위치궤적(GPS, KB~MB로 매우 작음).
- **구조**: Training(TS 원천 / TL 라벨) + Validation(VS 원천 / VL 라벨).
- **머신비전 유용 근거**: 대량의 **라벨링된(객체탐지 어노테이션 JSON) 건설 이미지** → PyTorch 이미지 인식/객체탐지 학습에 직접 적합. 원천+라벨 짝 구조가 supervised 학습 파이프라인과 일치.
- **제약**: AI Hub는 **해외/클라우드 IP 다운로드를 차단**(GCP 서울 리전 포함 → "해외 다운로드 제한 502"). 다운로드는 **한국 IP(집)에서만** 가능. 클라우드 VM 직접 다운로드 불가.

## 6. 다운로드 운영 (배치 방식) — v2 재설계(2026-06-14)
- **공간 모델 정정**: aihubshell은 download.tar 수신 후 압축해제 시 tar+추출본 동시 존재 → **peak ≈ 배치×2**. 안전식 **`B_max = 0.40 × free`**(peak 0.80 + 버퍼 0.20).
- 269GB free 기준: 이론 한도 ~107GB, **권장 ~80GB/배치** → **5배치로 수렴**(이전 6배치 축소). free가 175GB(배치1 잔류 시)면 한도 70GB로 자동 축소.
- 고정 배치 수 대신 **적응형 플래너**로 산정: `constgx/scripts/plan_batches.py`(파일트리+실시간 df → filekey 빈패킹, dry-run). 맥에서 `aihubshell -mode l > tree.txt` 후 실행.
- 루프: 다운로드 → GCS 업로드 → **검증(객체 존재+크기 일치)** → 통과 시에만 로컬 삭제 → 다음 배치. (삭제는 파괴적 작업이라 검증 게이트 필수.)
- 상세: `knowledge/download-batch-plan.md`.

## 7. 멀티에이전트 자동화 인프라 — 설계 착수(2026-06-14)
- 패턴: **Orchestrator → MCP(도구 게이트웨이) → Tool → Verifier → 진단·보정·재시도**. 핵심 차별점 = 자기검증 루프.
- 산출물: `constgx/agents/` — ARCHITECTURE.md(설계), orchestrator.py + verifier.py + tools.py(실행 골격, 모의 도구로 테스트 통과). 실행 로그는 `agents/runs/*.jsonl`.
- 1차 적용 워크플로우 = 데이터 배치 적재(다운로드→업로드→검증→삭제). 2차 = 비전 학습/평가(mAP 미달 시 하이퍼파라미터 보정 재시도). 2단계에서 모의 도구를 실제 aihubshell/gsutil/PyTorch로 교체 + MCP 서버 분리.

## 8. 데이터 파이프라인 진행 (2026-06-14 갱신)
- **GCP 완료**: gcloud 설치·인증 완료. 버킷 `gs://constgx-aihub-237` 생성(asia-northeast3/서울, uniform access). 무료체험 크레딧 ~₩448,755 / 90일.
- **배치1 다운로드 실패**: aihubshell이 93.8GB를 통짜 `download.tar`로 받았으나(전송 성공/HTTP 200), **압축해제·`.part` 병합 단계가 중단**돼 0바이트 zip stub만 남음. 데이터 디스크에 없음(du 48K) → **재다운로드 필요**.
- **도구 준비**: `constgx/scripts/merge_parts.sh`(1GB `.partN` 조각 재귀 병합), `plan_batches.py`(배치 플래너).
- **방식 변경**: 통짜 대신 **filekey 1개씩 tmux에서** 받기 → 받은 뒤 `merge_parts.sh` 병합 → `unzip -t` 무결성 → GCS 업로드 → 검증(크기 일치) → 로컬삭제 → 다음 filekey.
- **속도 실측**: ~12MB/s(AI Hub throttle). 전량 414GB ≈ 다운로드만 ~10h.
- **2026-06-15 병목 해결(중요)**: 반복된 0바이트 실패의 진짜 원인 = aihubshell `merge_parts()`의 `printf %q` 한글 이스케이프 → `find -name` 0개 매칭(정렬·공간·잠자기 다 오진). aihubshell을 sudo로 패치(실제 prefix 글롭 + `sort -n`, 삭제는 `-s` 가드) → **filekey 504524 brailleBlock 15GB 다운로드 + `unzip -t` 검증 통과**. 이제 filekey 단위로 전량 진행 가능. 다음: 버킷 재생성 → 업로드 → 크기검증 → 로컬삭제 루프. (상세 원인·패치: MEMORY.md 도구특성 2026-06-15)

## 8-1. 적재 자동화 진행 (2026-06-15)
- **GCS 적재 완료**: TS 504524·504525·504526·504527(circleManhole, Cursor eval로 러너 검증완료). 다음=504528.
- **러너 eval 통과(2026-06-16)**: 504527 2회차 DONE. 1회차서 502 거짓양성 버그 발견→수정(성공판정=산출물 존재, 재사용 가드, preflight KEY/BK 검증, RATE 보정). 안전 불변식(2게이트 후 삭제) 정상.
- **단일 에이전트 러너 구축**: `constgx/scripts/aihub_ingest.sh`(회복탄력 루프: preflight→다운로드→무결성→업로드→크기검증→삭제, 유계재시도+상태파일 멱등재개+연속실패 차단기+filekey별 예상/실제시간), 정책 `INGEST-AGENT.md`(DIAGNOSIS 표). 멀티에이전트 아님(결정적 선형반복).
- **실행 모델**: 코워크 샌드박스는 한국 IP 아니라 실행 불가 → **Cursor의 Claude(맥 터미널 접근)에 인계 실행**. 먼저 504527 1건 평가(`scripts/HANDOFF-eval-504527.md`) → 성능 확인되면 전량 큐를 Cursor에서 진행. 상태파일이 DONE 기억 → 재개 안전.
- **남은 큐 순서**: TS 504527~504543 → TL 504567~504585 → VS 504608~504627 → VL 504650~504669 → 보조(굴착기/입출입/위치궤적).
- **시크릿 관리**: `KEY`(aihub)·`BK`(버킷)는 `constgx/scripts/.env`에 정의(`.gitignore` 보호). 러너가 시작 시 자동 source → export·핸드오프에 키 재명시 불필요. 템플릿 `scripts/.env.example`.

## 9. 다음 단계 (순서)
0. ✅ **리허설 완료(2026-06-15)**: brailleBlock TS/TL로 객체탐지 파이프라인 3단계 전부 통과 — Dataset(polygon→xyxy)·DataLoader(collate)·bbox 시각화 정합 확인·FasterRCNN 1epoch(loss 유한 1.674→0.716, 역전파 동작). 코드 `constgx/vision/{dataset.py,rehearse.py}`, 시각검증 `vision/_out/bbox_check.png`. 스키마 v1 확정(라벨=polygon, EXIF 미적용 stored 공간). 파이프라인 무결성 검증됨 → 본학습 진행 가능.
1. **리허설**: ~~최소 슬라이스 디버깅~~ (완료, ↑0).
2. 검증되면 **전량 다운로드**(filekey 단위, tmux 무인) → GCS 적재.
3. **오케스트레이터(멀티에이전트) 설계**: GAP-ANALYSIS 🔴 갭(AgentContext·HITL·안전필터·최소권한·MCP검증)을 템플릿 *스키마 슬롯*으로. 책 ①『이것이 멀티 에이전트다』 실습 기반 — **유저가 초안 → 에이전트는 검토·보강만**.
- SDD 초안 SPEC.md는 미착수.
- ⚠ AI Hub API 키 노출 → 재발급 필요(확인). 삭제는 업로드 검증 후에만.
