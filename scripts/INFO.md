# scripts/ 파일 안내 (Pred-FirefromElec)

> 이 폴더의 보존 파일이 무엇이고 왜 필요한지 한눈에. (로그·임시·2.74GB rag_units·corpus_dl 등은 삭제 대상이라 여기 없음. `.env`는 비밀이라 git 금지·로컬만.)
>
> **유지보수 규칙: 이 폴더에 새 파일을 만들면 즉시 아래 표에 한 줄(무엇·왜 필요) 추가한다.** info만 봐도 폴더가 이해되게 유지.

## AI Hub 데이터셋 지도·스키마 (재조회 비용 커서 필수 보존)
| 파일 | 무엇 | 왜 필요 |
|---|---|---|
| `aihub-71918-filekey-map.md` | 71918(배터리 열폭주) filekey 맵 | 적재 큐의 출처. `-mode l` 재조회가 비용이라 박제본이 유일 지도 |
| `aihub-71921-filekey-map.md` | 71921(산불 확산 추론) filekey 맵 | 〃 |
| `aihub-71918-filekeys.tsv`, `aihub-71921-filekeys.tsv` | 위 맵의 머신리더블 전체 목록 | 적재 큐를 코드로 생성할 때 입력 |
| `aihub-71918-label-schema.md`, `aihub-71921-label-schema.md` | 각 데이터셋 라벨/구조 스키마(실측) | 임베딩 필드 선정·후속 학습의 근거 |

## 적재 산출물·정책
| 파일 | 무엇 | 왜 필요 |
|---|---|---|
| `aihub-ingest-status.md` | 적재 현황(어디에·얼마나 들어갔나) | 재조회 없이 상태 확인, 재적재 방지 |
| `aihub-rag-sources-manifest.md` | 외부 RAG 출처 7종(물성·가연환경, 직접 URL·라이선스) | AI Hub 밖 코퍼스의 출처·적재 근거 |
| `INGEST-AGENT.md` | 적재 러너 정책(루프·DIAGNOSIS·차단기·HITL) | 적재 워크플로의 명세 |

## 적재 러너(재사용 도구)
| 파일 | 무엇 | 왜 필요 |
|---|---|---|
| `aihub_ingest.sh` | 적재 메인 러너 | AI Hub→GCS 적재 자동화 |
| `dl_to_gcs_loop.sh` | 다운로드→검증→업로드→삭제 게이트 루프 | size-match 통과 후에만 삭제(안전 적재) |
| `merge_parts.sh` | `.part` 조각 병합(한글 0바이트 버그 패치 방식) | 큰 파일 무결 복원 |
| `RUNBOOK-download.md` | 다운로드 런북(맥/한국 IP) | AI Hub는 한국 IP에서만 — 실행 절차 |

## RAG 구축 파이프라인 코드 (활성)
| 파일 | 무엇 | 왜 필요 |
|---|---|---|
| `build_rag_units.py` | 71921 → 임베딩 단위 정제(질문+추론만, 수치 제외) | RAG 색인 입력 생성 |
| `measure_corpus_tokens.py` | 코퍼스 토큰·청크 실측 | 색인 규모·점유 산정 |
| `build_eval_set.py` | 검색 평가셋 생성(층화 known-item + 패러프레이즈 템플릿) | 청킹·PQ를 측정으로 정하기 위함 |
| `eval_matrix.py` | 청킹×인덱스 행렬 평가 → recall@k 비교표 | 설정 확정의 핵심 측정 도구 |
| `eval_recall.py` | recall@k·MRR 채점기 | 임의 검색결과 채점 |
| `eval_set_auto.jsonl` | 생성된 자동 평가셋(120) | eval_matrix 입력 |
| `eval_curated_template.jsonl` | 손으로 채울 패러프레이즈 질의 틀 | 진짜 의미검색 평가(누설 없는) |
| `build_rag_index.py` | 전량 RAG 인덱스 빌더(스트리밍 2-pass: tot 청킹→BGE-m3→IVF-PQ→저장/GCS업로드) | 색인 러너. 맥은 faiss 멀티스레드 세그폴트라 darwin은 1스레드 자동 |
| `vm_embed_startup.sh` | 자가종료 GPU 배치 VM startup(범용·메타데이터 주입식: gcs-in/gcs-out/run-cmd). 본문에 프로젝트 값 없음 | 맥 발열 회피용 클라우드 임베딩 패턴. 프로젝트 값은 VM 생성 시 --metadata로 주입(재사용·오염방지) |
| `search_preview.py` | 저장된 색인표를 직접 검색(embed/search 2단계 분리=맥 torch+faiss 세그폴트 회피). 결과는 eval_recall 형식 | 색인 품질 미리보기·orc retriever 기반. nprobe 검색시점 조절 가능 |
| `build_index_compare.py` | 압축 비교용 스모크 빌더 — 임베딩 1회 후 여러 faiss index_factory(PQ/OPQ/SQ) 동시 생성·크기측정 | "품질 살고 작은" 압축을 1회 GPU 스모크로 선택(전량 색인 전 게이트) |

## 기타
- `.env.example` — 환경변수 템플릿(키 형식 안내). `.env`(실제 키)는 git 금지·로컬만.
