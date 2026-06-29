# 체크포인트 — RAG 인덱스 구축 이어가기 (Pred-FirefromElec)

> **이 세션은 Cursor의 Claude Code 에이전트에서 이어간다.** Cowork 앱이 아니라 로컬(맥)이므로
> 코워크 샌드박스에서 막히던 작업(HF 모델 다운로드·AI Hub·실모델 임베딩)을 **직접 실행할 수 있다.**
> 부팅: `~/.claude/CLAUDE.md`(= `/Users/karla/cowork/CLAUDE.md` 심볼릭링크) → SOUL/LOOP/MEMORY/USER → 이 파일.
> 작업 폴더 = `/Users/karla/Documents/Pred-FirefromElec` (구 constgx에서 이름변경). 인프라(orc)는 별도 레포 `/Users/karla/Documents/Building-Infra/agents`.

---

## ★ 완료 — RAG 전체 색인 + orc 연결 (2026-06-23~24)

**상태: 5단계(준비→스모크→품질→전체색인→orc연결) 전부 완료.** RAG가 orc 엔진의 세 번째 실작업 인스턴스로 붙어, 실제 24만 색인을 검색해 답하는 데까지 동작 확인.

**핵심 전환 — tot/IVF-PQ 폐기, casehdr/flat 채택:** 원래 계획(tot 줄단위 청킹 + IVF-PQ)은 **틀린 길이었다.** 이유: 71921은 **합성 정형 데이터**라(만 건 중 고유 첫줄 182종뿐, 한 질문이 150~200케이스에 중복; 본문 줄도 39%만 고유) ①케이스끼리 벡터가 거의 똑같아 구별 안 되고 ②케이스를 가르는 메타(연료·주제)가 색인 글에서 빠져 있었다. → **casehdr 청킹**(케이스당 글 하나 = `연료유형/주제/질문유형/목적` 헤더 + 질문 첫줄)으로 바꾸자 검색이 살아남: **연료 일치 100%, 주제 일치 ~50%(오타변형 감안 시 더 높음)**. 조각 3,477만→**24.7만**으로 급감 → 압축 불필요(flat) → 전체 빌드 6분·~$0.3.
> ⚠ 교훈: known-item auto-eval(eval_set_auto)은 **이 정형 데이터에선 무효**(정답 질문이 수백 케이스에 중복 → R@1≈1/중복수). 상한이 0.007로 무너진 걸 처음엔 "PQ 압축 탓"으로 **오진**했고(비교 스모크 ~$0.7 헛씀), 진짜 원인은 데이터 중복. 평가셋은 **중복도부터 재고** 신뢰할 것. 품질은 상황형 질의(`eval_situational`)로 주제·연료 일치율을 본다.

**산출 위치:** 전체 색인 = `gs://constgx_electrofire/rag_index/full/idx_full/`(index.faiss 1.0GB flat + chunk_case_idx.npy + case_ids.json + case_meta.jsonl + manifest). 입력 = `gs://constgx_electrofire/rag_build/`(rag_units.jsonl 2.74GB + 러너들). **시험 찌꺼기(smoke·compare)는 삭제함.** 버킷 18.5GiB.

**비용:** 컴퓨팅 과금 0(VM·디스크·IP 전무, 전부 자가종료 확인). 스토리지만 ~$0.37/월.

**검증된 VM 레시피 (그대로 유효):** g2-standard-8 + nvidia-l4 / `--image-family=pytorch-2-9-cu129-ubuntu-2204-nvidia-580 --image-project=deeplearning-platform-release` / `--maintenance-policy=TERMINATE --scopes=cloud-platform --max-run-duration --instance-termination-action=DELETE` / startup=`scripts/vm_embed_startup.sh`(필수수정 4건 반영). **L4 STOCKOUT 잦음 → 여러 zone 자동 순회로 자리 찾기**(zsh는 배열로, 공백분할 안 됨). 이번엔 us-east1-d·us-central1-a 성공.

**전체 빌드 run-cmd(재현용):**
```bash
python build_rag_index.py rag_units.jsonl --out idx_full --device cuda \
  --model BAAI/bge-m3 --chunking casehdr --index flat --batch 1024 \
  --gcs-out gs://constgx_electrofire/rag_index/full/
```

**핵심 파일:**
- `scripts/build_rag_index.py` — `--chunking casehdr`(메타헤더+질문, 케이스당 1조각) + `--index flat`(압축없는 정확검색) 추가.
- `scripts/search_preview.py` — 저장 색인 검색. **embed/search 2단계 분리**(맥 torch+faiss 한 프로세스=libomp 세그폴트 회피). orc retriever가 하위프로세스로 호출.
- `scripts/build_index_compare.py` — 압축 비교용(이번 오진 때 만듦; 정형데이터엔 불필요했음. 다른 데이터셋엔 재사용 가능).
- `Building-Infra/agents/orc/handlers_retriever.py` + `specs.py`의 `RETRIEVE` — orc 세 번째 인스턴스(질의→검색→LLM근거응답). 검증: `RAG_OFFLINE=1 SLICE_OFFLINE=1 python -m orc.run retrieve`(배선·차단기), `SLICE_OFFLINE=1 …`(실검색+스텁응답).

**다음 작업 — 우선순위(하나씩):**
1. ~~★최우선 — 색인 영구 보관.~~ **완료(2026-06-29).** 색인 1GB를 고정 경로 `~/Documents/Pred-FirefromElec/rag_index/idx_full`로 내려받음(휘발 /tmp 폐기). RETRIEVE spec `index_dir`을 이 경로로 변경 + `gcs_index` 추가 → 폴더 휘발 시 `handlers_retriever._ensure_index`가 버킷에서 자동 재다운로드. 검증: `SLICE_OFFLINE=1 python3.12 -m orc.run retrieve` 실검색 5건 적중, 연료 일치 5/5·주제 '우선순위' 3/5. 무과금.
2. ~~orc 실제 답변 완성.~~ **완료(2026-06-29).** 실 키(`CLAUDE_KEY`, scripts/.env, git 미게시) 연결 + 사례 본문(rag_units.jsonl 2.6GB 버킷서 받음) 근거 주입. 코드: `handlers_retriever._load_bodies`(검색 id로 본문 text 조회, 조기종료) + `_rag_answer`가 hits에 text 붙여 LLM 전달, `llm.py` rag_answer 프롬프트 본문 우선 인용·근거부족 명시, `specs.py` definition에 `corpus` 추가. 검증: 실 LLM이 혼효림+고풍속 질의에 '주거지 우선' 답+본문 인용+출처 id+관광지근거는 '검색 근거 부족' 표기. ⚠ **`python -m orc.run` 통짜 실행은 매 실행 BGE-m3 2GB+faiss 1GB 재로딩 → 맥 저메모리 시 스왑 경합으로 멈춤**(코드 아닌 자원 문제). llm.py에 timeout=60·max_retries=2 가드 추가. 검색(1순위)·답변 분리 검증. LLM 호출 ~수센트.
3. ~~주제 정확도 ↑.~~ **완료(2026-06-29).** 오타 3쌍 통일(피혜예상→피해예상, 제확산→재확산, 진화벙법→진화방법) — `build_rag_units.py`의 SUBJ_FIX 맵. v2 재색인에 반영.
4. ~~수치 조건 포함.~~ **완료(2026-06-29).** 원본 71921 라벨링(Training+Validation 28zip, 버킷서 받음)에서 L0_context 수치(풍속·습도·기온·경사·고도·가뭄·화염장) 추출해 헤더에 추가. ⚠ Training은 W/T/O 축약키, Validation은 weather_conditions 전체키 → 두 스키마 호환 처리해야 수치 100% 채움(처음 88.9%→고침). `build_rag_units.extract_conditions` + `build_rag_index.py` casehdr에 `| 조건:` + case_meta에 conditions. GPU L4(us-central1-b, STOCKOUT로 zone순회) 24.7만 재임베딩 ~10분 $≈0.3, 자동삭제. 새 색인=`gs://constgx_electrofire/rag_index/full_v2/idx_full`, 로컬 `rag_index/idx_full_v2`. RETRIEVE spec을 v2로 승격(index_dir·gcs_index·corpus=rag_units_v2). 검증: '급경사·고온' 질의에 첫 결과 경사31도·기온19도로 정합(단 임베딩 숫자추론 약해 개선폭은 modest, 핵심이득=수치가 근거에 노출).
5. **외부 코퍼스 7종 비교.** 합성 데이터(71921) 대신 실지식 코퍼스(물성·발화·확산)가 검색에 더 맞는지 점검. 방향 재검토.
6. **평가셋 보강.** 손으로 쓴 패러프레이즈 시험셋(`eval_curated` 비어 있음)으로 품질 측정 신뢰도 ↑.

---

## (이력·완료) e5 접두어 버그 수정·재측정

**직전 세션(Cowork) 발견:** `scripts/eval_matrix_e5.log`의 매트릭스 표는 **무효다.**
원인 = `eval_matrix.py`가 BGE-m3용으로 작성됐는데(기본 모델·주석 전부 bge-m3, 접두어 부착 없음)
e5-small로 돌렸음. **e5 계열은 `query:`/`passage:` 접두어가 필수** — 빠지면 검색이 거의 무작위로 붕괴.
증상이 정확히 일치: 정답이 풀에 항상 포함된 **상한(auto_known_item)인데도** 최고 case/flat R@5=0.18,
tot/flat R@1=0.000. 정상 임베더면 known-item 상한은 R@5 0.6+ 나와야 한다 → 품질 아닌 파이프라인 버그.

**수정 완료:** `eval_matrix.py`에 모델별 접두어 처리 추가 — e5면 `query:`/`passage:` 자동 부착,
bge-m3는 그대로(하위호환). 함수 `e5_prefixes(model_name)` + `embed(model, texts, prefix, bs)`.
실행 시 `[prefix] e5 감지 → query:/passage: 부착`이 찍히면 적용된 것.
(배선은 Cowork 샌드박스에서 검증함 — 접두어가 실제 부착됨/직접 부착과 동일. 단 **실모델 recall은
HF 프록시 차단으로 못 돌림** → 여기 맥에서 재측정해 확인.)

**1) 먼저 재측정(맥, constgx/scripts에서):**
```
cd /Users/karla/Documents/constgx/scripts
python3 eval_matrix.py rag_units.jsonl eval_set_auto.jsonl --pool 2000 \
  --model intfloat/multilingual-e5-small --chunkings case tot win --indexes flat ivfpq \
  2>&1 | tee eval_matrix_e5_fixed.log
```
(이전과 달리 `--curated`는 뺐다 — 아래 curated 누락 참조.)

**2) 표 해석 분기:**
- auto known-item R@5가 건강한 범위(대략 0.6+)로 뛰면 → 파이프라인 정상. **이제** curated 기준으로 청킹/PQ 확정 단계로.
- 접두어 부착 후에도 여전히 낮으면 → 그때 비로소 분기 A(쿼리재작성/HyDE·rerank·임베딩모델 재검토)가 진짜 질문. (그 전엔 분기 A로 가지 말 것 — 직전에 무효표로 분기할 뻔했음.)

**curated 누락(분기 전 필수):** `eval_curated.jsonl`이 **없다.** `eval_curated_template.jsonl`(15행)은 전부
플레이스홀더(`<...>`)라 채점에 0행 쓰임. 체크포인트 분기는 curated(패러프레이즈) recall 기준이므로,
템플릿을 실제 사용자 말투 질문 + 정답 case id(rag_units.jsonl에서 찾아 기입)로 채워
`eval_curated.jsonl`로 저장한 뒤 `--curated eval_curated.jsonl`를 붙여 재측정해야 분기 가능.

## 청킹/PQ 확정 후 → 전량 색인 러너
- 청킹 = curated recall 최고인 것. PQ = 같은 청킹에서 flat 대비 ivfpq recall 갭 작으면 IVF-PQ 채택(점유 이득), 크게 하락하면 flat 유지 또는 PQ 파라미터(m·nlist·nprobe) 완화 후 재측정.
- 러너(`scripts/build_rag_index.py`): rag_units.jsonl 전량 → 확정 청킹 → **BGE-m3** 임베딩(CPU+KMP, batch) → IVF-PQ 인덱스 → 인덱스 버킷 적재 → raw(corpus_dl)·rag_units.jsonl 로컬 삭제.
  - 주의: 최종은 BGE-m3(접두어 불요)라 `eval_matrix.py`가 자동으로 접두어 안 붙임. 색인 러너도 같은 규칙 — e5 쓰면 접두어, bge면 미부착.
- (색인 완료 후) **orc 인스턴스 장착**: 검색 도구(retriever) + 질의→검색→LLM 추론→보고를 orc/ 세 번째 인스턴스로(= compare·ingest에 이은 실작업 인스턴스).

## 환경 주의 (반복 함정)
- **Cursor=맥이므로 HF 모델 다운로드·AI Hub·실모델 임베딩 직접 가능.** (Cowork 샌드박스는 huggingface.co 403 차단·AI Hub 해외차단이라 거기선 못 했음.)
- **임베딩 CPU 고정**: bge-m3+torch MPS = 세그폴트 → CPU + `os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")`(torch import 전, eval_matrix.py 상단에 박제됨). CPU ~11s/배치라 느림 → 결정은 작은 풀/가벼운 모델(e5-small), BGE-m3는 최종 색인.
- **AI Hub 다운로드·`-mode l`은 맥(한국 IP)에서만.** 재조회 금지: `aihubshell -mode l`(맵 박제됨), 적재현황(상태문서).
- **로컬 점유**: rag_units.jsonl(2.74GB)·corpus_dl은 재생성 가능 → 색인 후 삭제.

## 데이터 현황
- 적재 완료(버킷 `gs://constgx_electrofire`): aihub-71918(583)·aihub-71921(56)·rag-corpus(외부 7종). 639건 0실패.
- RAG 코퍼스 = rag-corpus + 71921. 71921 정제 = 246,789 case / 643M 토큰(수치·메타 제외, build_rag_units.py).

## 다른 스레드 상태 (인프라 — Building-Infra, 참고)
- orc 엔진 **v0.5 범용화 완료**: 작업 specifics를 `TaskSpec`(agents/orc/specs.py)으로 분리, 엔진(state/nodes/orchestrator)은 작업 지식 0. 같은 build_app이 두 spec(compare/ingest_demo)을 돌려 검증(A=DONE/B=FAILED). 상세 = `agents/SPEC.md` v0.5, `agents/orc/README.md`, `agents/docs/2026-06-20-checkpoint-인프라.md`.
- `agents/orc/handlers_ingest.py`에 실 AI Hub/URL 적재 액션 확장됨(aihub_download/integrity/upload/sizecheck/delete, url_download/integrity). **단 specs.py에 INGEST_AIHUB/RAG TaskSpec은 아직 미추가** — 그 스레드 이어가면 spec 정의 + diagnosis 매핑부터.

## 레포·폴더 (3분할)
- **cowork-agent**(IKWHI-OSS/cowork-agent) = `/Users/karla/cowork`: 에이전트 메모리·스킬.
- **Building-Infra** = `constgx/agents`: orc 엔진·SPEC·env·런북. 빌드로그는 git 미게시·로컬.
- **Pred-FirefromElec** = `constgx/scripts·vision·knowledge`: 데이터 맵·스키마·RAG 코드·복기노트.
- 라우팅 정본 = `cowork/REPO-MAP.md`. 각 폴더 `INFO.md`에 파일 안내(새 파일 시 즉시 갱신).

## RAG 결정 (확정)
- 오픈 임베딩(BGE-m3 1024) + ToT 구조 청킹 + IVF-PQ + 버킷보관·온디맨드. raw는 색인 후 로컬삭제.
- 단, 청킹/PQ는 **위 재측정(curated)으로 확정** — 직전 무효표의 "tot 유력" 예상은 폐기.
- 근거·복기 = `constgx/knowledge/rag-검색품질-오픈임베딩-결정-복기노트.md`(로컬 포트폴리오).

## 미푸시 / 미완 (정리)
- 삭제 대기(맥): progress.log·result.txt·*.log·.DS_Store·unknown.md·HANDOFF-eval-504527·HANDOFF-fulldataset. (단, `eval_matrix_e5_fixed.log`는 재측정 산출물이니 남길 것.)
- `.gitignore` 추가: .env, *.log, .DS_Store, corpus_dl/, rag_units.jsonl, result.txt, progress.log.
- git 일괄 push(세션 종료 시): cowork-agent(스킬·세션·메모리·USER), Pred-FirefromElec(INFO·CHECKPOINT·RAG코드·삭제), Building-Infra(INFO·orc v0.5).

## 작업 규칙
- 완료는 산출물로 판정. 근거 없는 동일 시도 반복 금지(상한부터 본다). 셸/코드 출력 이모지·특문 금지.
- 메모리 박제 승인제. 외래어·버즈워드 금지(평이한 한국어, 새 용어 즉시 정의). 미확정을 확정처럼 말하지 말 것.
- 파괴적/위험 명령(rm·gsutil rm·git push·.env/키·sudo)은 게이트. git push는 세션 종료 시 일괄.

---
_갱신 2026-06-22 (Cowork 세션) — e5 접두어 버그 발견·수정 반영. 다음 = 맥(Cursor)에서 재측정._
